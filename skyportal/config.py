import json
import os
import secrets
from pathlib import Path
from threading import RLock

from .figures import ELEMENT_COLORS


def migrate_legacy_config(config: dict) -> dict:
    govee = config.get("govee", {})
    govee["devices"] = [
        device for device in govee.get("devices", [])
        if device.get("sku") != "DreamViewScenic"
    ]
    actions = list(config.get("element_actions", {}).values())
    actions += list(config.get("element_combos", {}).values())
    actions += list(config.get("figure_palettes", {}).values())
    actions += list(config.get("powerup_palettes", {}).values())
    actions.append(config.get("default_palette", {}))
    for action in actions:
        if not isinstance(action, dict):
            continue
        if action.get("action_mode") == "dreamview":
            action["action_mode"] = "govee"
        action.pop("dreamview_device", None)
    return config


def default_config() -> dict:
    return {
        "setup_token": secrets.token_urlsafe(24),
        "govee": {"api_key": "", "devices": [], "brightness": 75},
        "home_assistant": {"url": "", "token": ""},
        "element_colors": dict(ELEMENT_COLORS),
        "element_outputs": {},
        "element_actions": {},
        "element_combos": {},
        "figure_palettes": {},
        "powerup_palettes": {},
        "default_palette": {},
        "recent_figures": [],
        "recent_powerups": [],
        "history": [],
        "figure_overrides": {},
        "behavior": {"on_remove": "leave", "remove_color": "#000000", "cooldown_seconds": 1.0},
    }


class ConfigStore:
    def __init__(self, path: str | None = None):
        self.path = Path(path or os.environ.get("SKYPORTAL_CONFIG", "/var/lib/skyportal-home/config.json"))
        self.lock = RLock()
        self.data = self._load()

    def _load(self) -> dict:
        base = default_config()
        if self.path.exists():
            saved = json.loads(self.path.read_text())
            for key, value in saved.items():
                if isinstance(value, dict) and isinstance(base.get(key), dict):
                    base[key].update(value)
                else:
                    base[key] = value
        return migrate_legacy_config(base)

    def save(self) -> None:
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps(self.data, indent=2) + "\n")
            os.chmod(temp, 0o600)
            temp.replace(self.path)

    def public(self) -> dict:
        result = json.loads(json.dumps(self.data))
        result["govee"]["api_key"] = "" if not result["govee"]["api_key"] else "configured"
        result["home_assistant"]["token"] = "" if not result["home_assistant"]["token"] else "configured"
        result.pop("setup_token", None)
        return result
