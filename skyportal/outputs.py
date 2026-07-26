import colorsys
import ipaddress
import logging
import os
import socket
import struct
import threading
import time
import uuid

import requests

log = logging.getLogger(__name__)


class OutputError(RuntimeError):
    pass


class GoveeSceneCache:
    def __init__(self):
        self.entries = {}
        self.lock = threading.Lock()

    def get(self, client, device: dict, force: bool = False) -> list[dict]:
        key = (client.api_key, device.get("sku"), device.get("device"))
        with self.lock:
            cached = self.entries.get(key)
            if cached and not force:
                return cached
        scenes = client.discover_scenes(device)
        with self.lock:
            self.entries[key] = scenes
        return scenes


class GoveeClient:
    BASE = "https://openapi.api.govee.com/router/api/v1"

    def __init__(self, api_key: str, session=None):
        self.api_key = api_key
        self.session = session or requests.Session()

    @property
    def headers(self):
        return {"Govee-API-Key": self.api_key, "Content-Type": "application/json"}

    def discover(self) -> list[dict]:
        response = self.session.get(f"{self.BASE}/user/devices", headers=self.headers, timeout=12)
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 200:
            raise OutputError(payload.get("message", "Govee rejected the request"))
        return payload.get("data", [])

    def _control(self, device: dict, capability: dict):
        body = {"requestId": str(uuid.uuid4()), "payload": {
            "sku": device["sku"], "device": device["device"], "capability": capability,
        }}
        response = self.session.post(f"{self.BASE}/device/control", headers=self.headers, json=body, timeout=12)
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") not in (None, 200):
            raise OutputError(payload.get("message") or payload.get("msg") or "Govee control failed")

    def _device_request(self, device: dict, endpoint: str) -> dict:
        body = {"requestId": str(uuid.uuid4()), "payload": {
            "sku": device["sku"], "device": device["device"],
        }}
        response = self.session.post(f"{self.BASE}/{endpoint}", headers=self.headers, json=body, timeout=12)
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 200:
            raise OutputError(payload.get("message") or payload.get("msg") or "Govee request failed")
        return payload.get("payload", {})

    def discover_scenes(self, device: dict) -> list[dict]:
        scenes = []
        for endpoint in ("device/scenes", "device/diy-scenes"):
            payload = self._device_request(device, endpoint)
            for capability in payload.get("capabilities", []):
                for option in capability.get("parameters", {}).get("options", []):
                    scenes.append({
                        "name": option.get("name", "Unnamed scene"),
                        "capability": {
                            "type": capability["type"],
                            "instance": capability["instance"],
                            "value": option.get("value"),
                        },
                    })
        return scenes

    def set_capability(self, device: dict, capability: dict, power_on: bool = True):
        if power_on:
            self._control(device, {"type": "devices.capabilities.on_off", "instance": "powerSwitch", "value": 1})
        self._control(device, capability)

    def set_color(self, device: dict, hex_color: str, brightness: int = 75):
        rgb = int(hex_color.lstrip("#"), 16)
        self._control(device, {"type": "devices.capabilities.on_off", "instance": "powerSwitch", "value": 1})
        self._control(device, {"type": "devices.capabilities.color_setting", "instance": "colorRgb", "value": rgb})
        self._control(device, {"type": "devices.capabilities.range", "instance": "brightness", "value": brightness})


class LifxLanClient:
    """Small LIFX LAN protocol client for discovery and whole-bulb color."""

    DISCOVERY_PORT = 56700
    HEADER_SIZE = 36
    GET_SERVICE = 2
    STATE_SERVICE = 3
    GET_LABEL = 23
    STATE_LABEL = 25
    SET_COLOR = 102
    SET_LIGHT_POWER = 117
    UDP_SERVICE = 1

    def __init__(self, socket_factory=socket.socket, source: int | None = None):
        self.socket_factory = socket_factory
        self.source = source or int.from_bytes(os.urandom(4), "little") or 2
        if self.source in (0, 1):
            self.source = 2
        self.sequence = 0
        self.lock = threading.Lock()

    @staticmethod
    def normalize_device(device: dict) -> dict:
        serial = str(device.get("serial", "")).lower().replace(":", "")
        if len(serial) != 12:
            raise OutputError("LIFX serial must contain 12 hexadecimal characters")
        try:
            bytes.fromhex(serial)
        except ValueError as exc:
            raise OutputError("LIFX serial must contain 12 hexadecimal characters") from exc
        try:
            address = ipaddress.ip_address(str(device.get("ip", "")))
            if address.version != 4:
                raise ValueError
            ip = str(address)
        except ValueError as exc:
            raise OutputError("LIFX device has an invalid IP address") from exc
        port = int(device.get("port", LifxLanClient.DISCOVERY_PORT))
        if not 1 <= port <= 65535:
            raise OutputError("LIFX device has an invalid UDP port")
        label = str(device.get("label") or f"LIFX {serial[-6:].upper()}").strip()
        return {"serial": serial, "label": label[:64], "ip": ip, "port": port}

    def _next_sequence(self) -> int:
        with self.lock:
            sequence = self.sequence
            self.sequence = (self.sequence + 1) % 256
        return sequence

    def _packet(
        self, packet_type: int, target: bytes = b"\0" * 8, payload: bytes = b"",
        *, tagged: bool = False, ack_required: bool = False,
    ) -> bytes:
        if len(target) != 8:
            raise OutputError("LIFX target must be 8 bytes")
        frame_flags = 0x1400 | (0x2000 if tagged else 0)
        address_flags = 0x02 if ack_required else 0
        return struct.pack(
            "<HHI8s6sBB8sHH",
            self.HEADER_SIZE + len(payload), frame_flags, self.source, target,
            b"\0" * 6, address_flags, self._next_sequence(), b"\0" * 8,
            packet_type, 0,
        ) + payload

    @staticmethod
    def _decode_header(packet: bytes) -> tuple[int, bytes, int]:
        if len(packet) < LifxLanClient.HEADER_SIZE:
            raise OutputError("LIFX response was shorter than its header")
        size = struct.unpack_from("<H", packet, 0)[0]
        if size < LifxLanClient.HEADER_SIZE or size > len(packet):
            raise OutputError("LIFX response declared an invalid size")
        return struct.unpack_from("<I", packet, 4)[0], packet[8:16], struct.unpack_from("<H", packet, 32)[0]

    @staticmethod
    def _target(serial: str) -> bytes:
        return bytes.fromhex(serial) + b"\0\0"

    def discover(self, timeout: float = 1.0) -> list[dict]:
        """Discover bulbs via GetService and enrich them with their device labels."""
        sock = self.socket_factory(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind(("", 0))
            sock.settimeout(max(0.05, timeout))
            request = self._packet(self.GET_SERVICE, tagged=True)
            sock.sendto(request, ("255.255.255.255", self.DISCOVERY_PORT))
            deadline = time.monotonic() + timeout
            devices = {}
            while time.monotonic() < deadline:
                sock.settimeout(max(0.01, deadline - time.monotonic()))
                try:
                    packet, address = sock.recvfrom(1024)
                except socket.timeout:
                    break
                try:
                    source, target, packet_type = self._decode_header(packet)
                    if source != self.source or packet_type != self.STATE_SERVICE or len(packet) < 41:
                        continue
                    service, port = struct.unpack_from("<BI", packet, self.HEADER_SIZE)
                    if service != self.UDP_SERVICE:
                        continue
                    serial = target[:6].hex()
                    devices[serial] = {
                        "serial": serial, "label": f"LIFX {serial[-6:].upper()}",
                        "ip": address[0], "port": port,
                    }
                except (OutputError, struct.error):
                    continue

            if not devices:
                return []
            for device in devices.values():
                sock.sendto(
                    self._packet(self.GET_LABEL, self._target(device["serial"])),
                    (device["ip"], device["port"]),
                )
            label_deadline = time.monotonic() + min(0.5, max(0.1, timeout))
            while time.monotonic() < label_deadline:
                sock.settimeout(max(0.01, label_deadline - time.monotonic()))
                try:
                    packet, _ = sock.recvfrom(1024)
                except socket.timeout:
                    break
                try:
                    source, target, packet_type = self._decode_header(packet)
                    if source != self.source or packet_type != self.STATE_LABEL or len(packet) < 68:
                        continue
                    serial = target[:6].hex()
                    if serial in devices:
                        label = packet[self.HEADER_SIZE:self.HEADER_SIZE + 32].split(b"\0", 1)[0]
                        decoded = label.decode("utf-8", errors="replace").strip()
                        if decoded:
                            devices[serial]["label"] = decoded
                except OutputError:
                    continue
            return sorted(
                (self.normalize_device(device) for device in devices.values()),
                key=lambda device: (device["label"].lower(), device["serial"]),
            )
        finally:
            sock.close()

    def _send(self, device: dict, packet_type: int, payload: bytes):
        device = self.normalize_device(device)
        sock = self.socket_factory(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            sock.sendto(
                self._packet(packet_type, self._target(device["serial"]), payload),
                (device["ip"], device["port"]),
            )
        finally:
            sock.close()

    def set_color(self, device: dict, hex_color: str, brightness: int = 75, duration_ms: int = 250):
        value = hex_color.strip().lstrip("#")
        if len(value) != 6:
            raise OutputError("LIFX color must be a six-digit hexadecimal color")
        try:
            red, green, blue = (int(value[index:index + 2], 16) / 255 for index in (0, 2, 4))
        except ValueError as exc:
            raise OutputError("LIFX color must be a six-digit hexadecimal color") from exc
        hue, saturation, _ = colorsys.rgb_to_hsv(red, green, blue)
        brightness = max(0, min(100, int(brightness)))
        duration_ms = max(0, min(0xFFFFFFFF, int(duration_ms)))
        color_payload = struct.pack(
            "<BHHHHI", 0, round(hue * 65535), round(saturation * 65535),
            round(brightness * 65535 / 100), 3500, duration_ms,
        )
        self._send(device, self.SET_COLOR, color_payload)
        self._send(device, self.SET_LIGHT_POWER, struct.pack("<HI", 65535, duration_ms))


class HomeAssistantClient:
    def __init__(self, url: str, token: str, session=None):
        self.url = url.rstrip("/")
        self.token = token
        self.session = session or requests.Session()

    def call_service(self, domain: str, service: str, data: dict):
        response = self.session.post(
            f"{self.url}/api/services/{domain}/{service}",
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
            json=data,
            timeout=12,
        )
        response.raise_for_status()

    def activate_scene(self, entity_id: str):
        self.call_service("scene", "turn_on", {"entity_id": entity_id})
