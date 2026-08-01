import colorsys
from concurrent.futures import ThreadPoolExecutor, as_completed
import ipaddress
import logging
import os
import re
import socket
import struct
import threading
import time
import uuid
from urllib.parse import urlsplit

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

    def set_white(self, device: dict, kelvin: int = 4000, brightness: int = 75):
        capability = next((
            item for item in device.get("capabilities", [])
            if item.get("instance") == "colorTemperatureK"
        ), None)
        if not capability:
            raise OutputError("This Govee device does not advertise white-temperature control")
        value_range = capability.get("parameters", {}).get("range", {})
        try:
            minimum = int(value_range["min"])
            maximum = int(value_range["max"])
            precision = max(1, int(value_range.get("precision", 1)))
        except (KeyError, TypeError, ValueError) as exc:
            raise OutputError("Govee returned an invalid white-temperature range") from exc
        kelvin = max(minimum, min(maximum, int(kelvin)))
        kelvin = minimum + round((kelvin - minimum) / precision) * precision
        kelvin = max(minimum, min(maximum, kelvin))
        self._control(device, {"type": "devices.capabilities.on_off", "instance": "powerSwitch", "value": 1})
        self._control(device, {
            "type": capability.get("type", "devices.capabilities.color_setting"),
            "instance": "colorTemperatureK",
            "value": kelvin,
        })
        self._control(device, {
            "type": "devices.capabilities.range",
            "instance": "brightness",
            "value": max(1, min(100, int(brightness))),
        })


class LifxLanClient:
    """Small LIFX LAN protocol client for discovery and whole-bulb color/white."""

    DISCOVERY_PORT = 56700
    PRODUCT_REGISTRY_URL = "https://raw.githubusercontent.com/LIFX/products/master/products.json"
    HEADER_SIZE = 36
    GET_SERVICE = 2
    STATE_SERVICE = 3
    GET_HOST_FIRMWARE = 14
    STATE_HOST_FIRMWARE = 15
    GET_LABEL = 23
    STATE_LABEL = 25
    GET_VERSION = 32
    STATE_VERSION = 33
    SET_COLOR = 102
    SET_LIGHT_POWER = 117
    UDP_SERVICE = 1
    _registry_cache = None
    _registry_lock = threading.Lock()

    def __init__(
        self, socket_factory=socket.socket, source: int | None = None,
        registry_loader=None,
    ):
        self.socket_factory = socket_factory
        self.source = source or int.from_bytes(os.urandom(4), "little") or 2
        if self.source in (0, 1):
            self.source = 2
        self.sequence = 0
        self.lock = threading.Lock()
        self.registry_loader = registry_loader or self._download_product_registry

    @classmethod
    def _download_product_registry(cls) -> list[dict]:
        with cls._registry_lock:
            if cls._registry_cache is not None:
                return cls._registry_cache
            response = requests.get(cls.PRODUCT_REGISTRY_URL, timeout=5)
            response.raise_for_status()
            cls._registry_cache = response.json()
            return cls._registry_cache

    @staticmethod
    def _product_features(
        registry: list[dict], vendor_id: int, product_id: int,
        firmware_major: int, firmware_minor: int,
    ) -> dict | None:
        for vendor in registry:
            if vendor.get("vid") != vendor_id:
                continue
            features = dict(vendor.get("defaults") or vendor.get("default") or {})
            for product in vendor.get("products", []):
                if product.get("pid") != product_id:
                    continue
                features.update(product.get("features", {}))
                for upgrade in product.get("upgrades", []):
                    required = (int(upgrade.get("major", 0)), int(upgrade.get("minor", 0)))
                    if (firmware_major, firmware_minor) >= required:
                        features.update(upgrade.get("features", {}))
                return {
                    "product_name": product.get("name", f"LIFX product {product_id}"),
                    "color": bool(features.get("color", False)),
                    "temperature_range": features.get("temperature_range"),
                }
        return None

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
        normalized = {"serial": serial, "label": label[:64], "ip": ip, "port": port}
        for key in ("vendor_id", "product_id", "firmware_major", "firmware_minor"):
            if key in device:
                try:
                    normalized[key] = max(0, int(device[key]))
                except (TypeError, ValueError):
                    pass
        if "product_name" in device:
            normalized["product_name"] = str(device["product_name"])[:80]
        if "color" in device:
            normalized["color"] = bool(device["color"])
        if "temperature_range" in device:
            temperature_range = device["temperature_range"]
            if temperature_range is None:
                normalized["temperature_range"] = None
            elif (
                isinstance(temperature_range, (list, tuple))
                and len(temperature_range) == 2
            ):
                try:
                    minimum, maximum = (int(value) for value in temperature_range)
                    if 1000 <= minimum <= maximum <= 10000:
                        normalized["temperature_range"] = [minimum, maximum]
                except (TypeError, ValueError):
                    pass
        return normalized

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
                target = self._target(device["serial"])
                destination = (device["ip"], device["port"])
                for packet_type in (self.GET_LABEL, self.GET_VERSION, self.GET_HOST_FIRMWARE):
                    sock.sendto(self._packet(packet_type, target), destination)
            detail_deadline = time.monotonic() + min(0.75, max(0.15, timeout))
            while time.monotonic() < detail_deadline:
                sock.settimeout(max(0.01, detail_deadline - time.monotonic()))
                try:
                    packet, _ = sock.recvfrom(1024)
                except socket.timeout:
                    break
                try:
                    source, target, packet_type = self._decode_header(packet)
                    if source != self.source:
                        continue
                    serial = target[:6].hex()
                    if serial not in devices:
                        continue
                    if packet_type == self.STATE_LABEL and len(packet) >= 68:
                        label = packet[self.HEADER_SIZE:self.HEADER_SIZE + 32].split(b"\0", 1)[0]
                        decoded = label.decode("utf-8", errors="replace").strip()
                        if decoded:
                            devices[serial]["label"] = decoded
                    elif packet_type == self.STATE_VERSION and len(packet) >= 48:
                        vendor_id, product_id = struct.unpack_from("<II", packet, self.HEADER_SIZE)
                        devices[serial].update({
                            "vendor_id": vendor_id,
                            "product_id": product_id,
                        })
                    elif packet_type == self.STATE_HOST_FIRMWARE and len(packet) >= 56:
                        minor, major = struct.unpack_from("<HH", packet, self.HEADER_SIZE + 16)
                        devices[serial].update({
                            "firmware_major": major,
                            "firmware_minor": minor,
                        })
                except (OutputError, struct.error):
                    continue
            versioned = [
                device for device in devices.values()
                if "vendor_id" in device and "product_id" in device
            ]
            if versioned:
                try:
                    registry = self.registry_loader()
                    for device in versioned:
                        features = self._product_features(
                            registry, device["vendor_id"], device["product_id"],
                            device.get("firmware_major", 0),
                            device.get("firmware_minor", 0),
                        )
                        if features:
                            device.update(features)
                except Exception:
                    log.warning("Could not load the LIFX product registry", exc_info=True)
            return sorted(
                (
                    self.normalize_device(device) for device in devices.values()
                    if device.get("color", True)
                    or device.get("temperature_range", [1500, 9000]) is not None
                ),
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

    def _set_hsbk(
        self, device: dict, hue: int, saturation: int, brightness: int,
        kelvin: int, duration_ms: int,
    ):
        brightness = max(0, min(100, int(brightness)))
        duration_ms = max(0, min(0xFFFFFFFF, int(duration_ms)))
        color_payload = struct.pack(
            "<BHHHHI", 0, max(0, min(65535, int(hue))),
            max(0, min(65535, int(saturation))),
            round(brightness * 65535 / 100), int(kelvin), duration_ms,
        )
        self._send(device, self.SET_COLOR, color_payload)
        self._send(device, self.SET_LIGHT_POWER, struct.pack("<HI", 65535, duration_ms))

    def set_color(self, device: dict, hex_color: str, brightness: int = 75, duration_ms: int = 250):
        value = hex_color.strip().lstrip("#")
        if len(value) != 6:
            raise OutputError("LIFX color must be a six-digit hexadecimal color")
        try:
            red, green, blue = (int(value[index:index + 2], 16) / 255 for index in (0, 2, 4))
        except ValueError as exc:
            raise OutputError("LIFX color must be a six-digit hexadecimal color") from exc
        hue, saturation, _ = colorsys.rgb_to_hsv(red, green, blue)
        self._set_hsbk(
            device, round(hue * 65535), round(saturation * 65535),
            brightness, 3500, duration_ms,
        )

    def set_white(
        self, device: dict, kelvin: int = 3500, brightness: int = 75,
        duration_ms: int = 250,
    ):
        normalized = self.normalize_device(device)
        temperature_range = normalized.get("temperature_range") or [1500, 9000]
        minimum, maximum = temperature_range
        kelvin = max(minimum, min(maximum, int(kelvin)))
        self._set_hsbk(normalized, 0, 0, brightness, kelvin, duration_ms)


class WledClient:
    """Local WLED JSON API client with mDNS and manual-address discovery."""

    SERVICE_TYPE = "_wled._tcp.local."

    def __init__(self, session=None):
        self.session = session or requests.Session()

    @staticmethod
    def normalize_address(address: str) -> str:
        raw = str(address or "").strip()
        if not raw:
            raise OutputError("Enter a WLED hostname or IP address")
        parsed = urlsplit(raw if "://" in raw else f"http://{raw}")
        if (
            parsed.scheme.lower() != "http" or not parsed.hostname
            or parsed.username or parsed.password
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment
        ):
            raise OutputError("WLED address must be a local HTTP hostname or IP address")
        hostname = parsed.hostname.lower().rstrip(".")
        try:
            address_value = ipaddress.ip_address(hostname)
            if not (address_value.is_private or address_value.is_link_local or address_value.is_loopback):
                raise OutputError("WLED IP address must be on the local network")
            hostname = str(address_value)
        except ValueError:
            if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", hostname):
                raise OutputError("WLED hostname is invalid")
        try:
            port = parsed.port or 80
        except ValueError as exc:
            raise OutputError("WLED port is invalid") from exc
        if not 1 <= port <= 65535:
            raise OutputError("WLED port is invalid")
        return hostname if port == 80 else f"{hostname}:{port}"

    @classmethod
    def normalize_device(cls, device: dict) -> dict:
        address = cls.normalize_address(device.get("address", ""))
        mac = re.sub(r"[^0-9a-f]", "", str(device.get("mac", "")).lower())
        if len(mac) != 12:
            mac = ""
        identifier = mac or str(device.get("id") or address).strip()[:80]
        name = str(device.get("name") or f"WLED {identifier[-6:].upper()}").strip()[:80]
        normalized = {
            "id": identifier,
            "name": name,
            "address": address,
            "mac": mac,
            "version": str(device.get("version") or "")[:32],
            "arch": str(device.get("arch") or "")[:32],
            "led_count": max(0, min(100000, int(device.get("led_count", 0) or 0))),
            "rgb": bool(device.get("rgb", True)),
            "white": bool(device.get("white", False)),
            "cct": bool(device.get("cct", False)),
        }
        segments = []
        for segment in device.get("segments", []):
            try:
                segment_id = int(segment.get("id"))
                light_capabilities = max(0, min(255, int(segment.get("lc", 0))))
            except (AttributeError, TypeError, ValueError):
                continue
            if 0 <= segment_id <= 255 and segment_id not in [item["id"] for item in segments]:
                segments.append({"id": segment_id, "lc": light_capabilities})
        normalized["segments"] = segments or [{"id": 0, "lc": 0}]
        presets = []
        for preset in device.get("presets", []):
            try:
                preset_id = int(preset.get("id"))
            except (AttributeError, TypeError, ValueError):
                continue
            if 1 <= preset_id <= 250:
                presets.append({
                    "id": preset_id,
                    "name": str(preset.get("name") or f"Preset {preset_id}")[:80],
                })
        normalized["presets"] = sorted(presets, key=lambda item: item["id"])
        return normalized

    @staticmethod
    def _brightness(value: int) -> int:
        return max(1, min(255, round(int(value) * 255 / 100)))

    @staticmethod
    def _segment_updates(device: dict, capability_bit: int, values: dict) -> list[dict]:
        updates = []
        for segment in device.get("segments", []) or [{"id": 0, "lc": 0}]:
            capabilities = int(segment.get("lc", 0))
            if capabilities and not capabilities & capability_bit:
                continue
            updates.append({"id": int(segment.get("id", 0)), **values})
        if not updates:
            raise OutputError("No WLED segments support this light mode")
        return updates

    def _post_state(self, device: dict, state: dict):
        device = self.normalize_device(device)
        response = self.session.post(
            f"http://{device['address']}/json/state", json=state, timeout=5,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and payload.get("error"):
            raise OutputError(str(payload["error"]))

    def set_color(self, device: dict, hex_color: str, brightness: int = 75):
        value = hex_color.strip().lstrip("#")
        if len(value) != 6:
            raise OutputError("WLED color must be a six-digit hexadecimal color")
        try:
            red, green, blue = (int(value[index:index + 2], 16) for index in (0, 2, 4))
        except ValueError as exc:
            raise OutputError("WLED color must be a six-digit hexadecimal color") from exc
        device = self.normalize_device(device)
        segments = self._segment_updates(
            device, 1, {"fx": 0, "col": [[red, green, blue, 0]]},
        )
        self._post_state(device, {
            "on": True, "bri": self._brightness(brightness), "tt": 3,
            "seg": segments,
        })

    def set_white(self, device: dict, kelvin: int = 4000, brightness: int = 75):
        device = self.normalize_device(device)
        if device["cct"]:
            kelvin = max(2700, min(6500, int(kelvin)))
            relative_cct = round((kelvin - 2700) * 255 / (6500 - 2700))
            values = {"fx": 0, "cct": relative_cct, "col": [[0, 0, 0, 255]]}
            capability_bit = 4
        elif device["white"]:
            values = {"fx": 0, "col": [[0, 0, 0, 255]]}
            capability_bit = 2
        else:
            raise OutputError("This WLED device does not have a native white channel")
        self._post_state(device, {
            "on": True, "bri": self._brightness(brightness), "tt": 3,
            "seg": self._segment_updates(device, capability_bit, values),
        })

    def set_preset(self, device: dict, preset_id: int):
        preset_id = int(preset_id)
        if not 1 <= preset_id <= 250:
            raise OutputError("WLED preset ID must be from 1 to 250")
        self._post_state(device, {"on": True, "ps": preset_id})

    def probe(self, address: str) -> dict:
        address = self.normalize_address(address)
        response = self.session.get(f"http://{address}/json", timeout=5)
        response.raise_for_status()
        payload = response.json()
        info = payload.get("info", {}) if isinstance(payload, dict) else {}
        state = payload.get("state", {}) if isinstance(payload, dict) else {}
        if not info or not info.get("ver"):
            raise OutputError(f"{address} did not return WLED device information")
        leds = info.get("leds", {})
        segment_capabilities = leds.get("seglc") or []
        segments = []
        for index, segment in enumerate(state.get("seg", [])):
            segment_id = int(segment.get("id", index))
            light_capabilities = int(
                segment_capabilities[segment_id]
                if segment_id < len(segment_capabilities)
                else leds.get("lc", 0) or 0
            )
            segments.append({"id": segment_id, "lc": light_capabilities})
        combined_capabilities = 0
        for light_capabilities in segment_capabilities:
            combined_capabilities |= int(light_capabilities)
        combined_capabilities |= int(leds.get("lc", 0) or 0)
        modern_capabilities = bool(segment_capabilities) or "lc" in leds
        rgb = bool(combined_capabilities & 1) if modern_capabilities else True
        white = bool(combined_capabilities & 2) if modern_capabilities else bool(
            leds.get("rgbw") or leds.get("wv")
        )
        cct = bool(combined_capabilities & 4) if modern_capabilities else bool(leds.get("cct"))
        presets = []
        try:
            preset_response = self.session.get(f"http://{address}/presets.json", timeout=5)
            preset_response.raise_for_status()
            for preset_id, preset in preset_response.json().items():
                if str(preset_id).isdigit() and isinstance(preset, dict):
                    presets.append({"id": int(preset_id), "name": preset.get("n")})
        except Exception:
            log.info("Could not read WLED presets from %s", address, exc_info=True)
        return self.normalize_device({
            "id": info.get("device_id"),
            "name": info.get("name"),
            "address": info.get("ip") or address,
            "mac": info.get("mac"),
            "version": info.get("ver"),
            "arch": info.get("arch"),
            "led_count": leds.get("count", 0),
            "rgb": rgb,
            "white": white or cct,
            "cct": cct,
            "segments": segments,
            "presets": presets,
        })

    @classmethod
    def _mdns_addresses(cls, timeout: float) -> list[str]:
        try:
            from zeroconf import ServiceBrowser, ServiceListener, Zeroconf
        except ImportError as exc:
            raise OutputError("WLED discovery support is not installed") from exc

        found = set()
        lock = threading.Lock()

        class Listener(ServiceListener):
            def add_service(self, zeroconf, service_type, name):
                info = zeroconf.get_service_info(service_type, name, timeout=1500)
                if not info:
                    return
                with lock:
                    for address in info.parsed_scoped_addresses():
                        try:
                            parsed = ipaddress.ip_address(address.split("%", 1)[0])
                        except ValueError:
                            continue
                        if parsed.version == 4:
                            found.add(str(parsed) if info.port == 80 else f"{parsed}:{info.port}")

            def update_service(self, zeroconf, service_type, name):
                self.add_service(zeroconf, service_type, name)

            def remove_service(self, zeroconf, service_type, name):
                pass

        zeroconf = Zeroconf()
        browser = ServiceBrowser(zeroconf, cls.SERVICE_TYPE, Listener())
        try:
            time.sleep(max(0.1, min(5.0, float(timeout))))
        finally:
            browser.cancel()
            zeroconf.close()
        return sorted(found)

    def discover(
        self, addresses: list[str] | None = None, address: str | None = None,
        timeout: float = 2.0,
    ) -> list[dict]:
        candidates = {
            self.normalize_address(candidate) for candidate in (addresses or [])
            if str(candidate or "").strip()
        }
        if address:
            candidates.add(self.normalize_address(address))
        else:
            try:
                candidates.update(self._mdns_addresses(timeout))
            except Exception:
                if not candidates:
                    raise
                log.warning("WLED mDNS discovery failed; refreshing saved addresses only", exc_info=True)
        if not candidates:
            return []
        devices = {}
        errors = []
        with ThreadPoolExecutor(max_workers=min(8, len(candidates))) as executor:
            pending = {executor.submit(self.probe, candidate): candidate for candidate in candidates}
            for future in as_completed(pending):
                try:
                    device = future.result()
                    devices[device["id"]] = device
                except Exception as exc:
                    errors.append(f"{pending[future]}: {exc}")
        if address and not devices:
            raise OutputError(errors[0] if errors else "WLED device was not found")
        return sorted(devices.values(), key=lambda device: (device["name"].lower(), device["id"]))


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
