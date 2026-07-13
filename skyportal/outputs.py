import logging
import uuid

import requests

log = logging.getLogger(__name__)


class OutputError(RuntimeError):
    pass


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
