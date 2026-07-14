import logging
import threading
import time

from .figures import identify, identify_all_present
from .outputs import GoveeClient, HomeAssistantClient
from .portal import Portal

log = logging.getLogger(__name__)
VIRTUAL_GROUP_SKUS = {"DreamViewScenic", "BaseGroup", "SameModeGroup"}


class Controller:
    def __init__(self, store, portal_factory=Portal):
        self.store = store
        self.portal_factory = portal_factory
        self.portal = None
        self.stop_event = threading.Event()
        self.thread = None
        self.last_slots = {}
        self.state = {
            "portal": "disconnected", "figure": None, "figures": [],
            "last_error": None, "updated_at": None,
        }

    def start(self):
        if not self.thread or not self.thread.is_alive():
            self.thread = threading.Thread(target=self.run, name="portal-reader", daemon=True)
            self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)

    def run(self):
        while not self.stop_event.is_set():
            try:
                if not self.portal:
                    self.portal = self.portal_factory()
                    self.portal.connect()
                    self.state["portal"] = "connected"
                slots = self.portal.status()
                current = {slot: self.portal.read_identity(slot) for slot in slots}
                if current and current != self.last_slots:
                    self.handle_figures(identify_all_present(list(current.values())))
                if not current and not self.last_slots and self.state["updated_at"] is None:
                    self.handle_default()
                if self.last_slots and not current:
                    self.handle_remove()
                self.last_slots = current
                time.sleep(0.25)
            except Exception as exc:
                log.exception("Portal loop error")
                self.state.update({"portal": "disconnected", "last_error": str(exc)})
                if self.portal:
                    try:
                        self.portal.close()
                    except Exception:
                        pass
                self.portal = None
                self.stop_event.wait(2)

    def _record(self, event: str, label: str, detail: str = ""):
        entry = {"at": time.time(), "event": event, "label": label, "detail": detail}
        history = self.store.data.setdefault("history", [])
        history.insert(0, entry)
        del history[50:]
        try:
            self.store.save()
        except Exception:
            log.exception("Could not save history")

    def _remember(self, figure: dict):
        key = "recent_powerups" if figure.get("kind") == "power_up" else "recent_figures"
        recent = self.store.data.setdefault(key, [])
        character_id = figure["id"]
        recent[:] = [item for item in recent if item != character_id]
        recent.insert(0, character_id)
        del recent[12:]

    def _activate_ha(self, scene: str):
        scene = (scene or "").strip()
        ha = self.store.data["home_assistant"]
        if scene and ha["url"] and ha["token"]:
            HomeAssistantClient(ha["url"], ha["token"]).activate_scene(scene)

    def _individual_devices(self):
        return [
            device for device in self.store.data["govee"]["devices"]
            if device.get("sku") not in VIRTUAL_GROUP_SKUS
        ]

    def _dreamview_targets(self):
        return [
            device for device in self.store.data["govee"]["devices"]
            if device.get("sku") == "DreamViewScenic" or any(
                capability.get("instance") == "dreamViewToggle"
                for capability in device.get("capabilities", [])
            )
        ]

    def _apply_outputs(self, base_color: str, outputs: dict):
        config = self.store.data
        if not config["govee"]["api_key"]:
            return []
        client = GoveeClient(config["govee"]["api_key"])
        errors = []
        for device in self._individual_devices():
            try:
                output = outputs.get(device["device"], {})
                if output.get("mode") in ("scene", "music") and output.get("capability"):
                    client.set_capability(device, output["capability"])
                else:
                    client.set_color(
                        device, output.get("color") or base_color,
                        int(output.get("brightness", config["govee"]["brightness"])),
                    )
            except Exception as exc:
                name = device.get("deviceName") or device.get("sku") or device["device"]
                log.exception("Govee output error for %s", name)
                errors.append(f"{name}: {exc}")
        return errors

    def _activate_dreamview(self, device_id: str):
        config = self.store.data
        if not config["govee"]["api_key"]:
            return ["Configure a Govee API key first."], ""
        targets = self._dreamview_targets()
        target = next((device for device in targets if str(device.get("device")) == str(device_id)), None)
        if not target:
            return ["Select an available DreamView group."], ""
        if target.get("sku") == "DreamViewScenic":
            toggle = next((
                capability for capability in target.get("capabilities", [])
                if capability.get("instance") == "powerSwitch"
            ), {
                "type": "devices.capabilities.on_off", "instance": "powerSwitch",
                "parameters": {"dataType": "ENUM", "options": []},
            })
        else:
            toggle = next(
                capability for capability in target.get("capabilities", [])
                if capability.get("instance") == "dreamViewToggle"
            )
        capability = {
            "type": toggle["type"], "instance": toggle["instance"], "value": 1,
        }
        try:
            GoveeClient(config["govee"]["api_key"]).set_capability(target, capability, power_on=False)
            return [], target.get("deviceName") or "DreamView"
        except Exception as exc:
            log.exception("DreamView output error")
            return [f"DreamView: {exc}"], target.get("deviceName") or "DreamView"

    def _activate_palette(self, label: str, color: str, outputs: dict, action: dict, event="palette"):
        errors = []
        mode = action.get("action_mode")
        if not mode:
            mode = "home_assistant" if action.get("lights_enabled") is False else "govee"
        detail = ""
        if mode == "home_assistant":
            detail = action.get("ha_scene", "")
            try:
                self._activate_ha(detail)
            except Exception as exc:
                log.exception("Home Assistant output error")
                errors.append(f"Home Assistant: {exc}")
        elif mode == "dreamview":
            dreamview_errors, detail = self._activate_dreamview(action.get("dreamview_device", ""))
            errors.extend(dreamview_errors)
        else:
            errors.extend(self._apply_outputs(color, outputs))
        self.state["last_error"] = "; ".join(errors) if errors else None
        self._record(event, label, detail)

    def handle_figure(self, character_id: int, variant_id: int = 0, figure=None):
        figure = dict(figure or identify(character_id, variant_id))
        config = self.store.data
        self._remember(figure)
        collection = config.setdefault("powerup_palettes" if figure.get("kind") == "power_up" else "figure_palettes", {})
        profile = collection.get(str(character_id))
        legacy = config.get("figure_overrides", {}).get(str(character_id), {})
        if profile:
            color = profile.get("color") or config["element_colors"].get(figure["element"]) or config["element_colors"].get("unknown", "#708090")
            outputs = profile.get("outputs", {})
            action = profile
            label = f"{figure['name']} palette"
        else:
            color = legacy.get("color") or config["element_colors"].get(figure["element"]) or config["element_colors"].get("unknown", "#708090")
            outputs = config["element_outputs"].get(figure["element"], {})
            action = dict(config.get("element_actions", {}).get(figure["element"], {}))
            if legacy.get("ha_scene"):
                action["ha_scene"] = legacy["ha_scene"]
            label = f"{figure['element'].title()} palette"
        figure["color"] = color
        self.state.update({"figure": figure, "figures": [figure], "updated_at": time.time()})
        if self.portal:
            self.portal.set_color(color)
        self._activate_palette(label, color, outputs, action, "power_up" if figure.get("kind") == "power_up" else "figure")

    def handle_figures(self, figures: list[dict]):
        if not figures:
            return
        self.state["figures"] = figures
        for figure in figures:
            self._remember(figure)
        powerups = [figure for figure in figures if figure.get("kind") == "power_up"]
        if powerups:
            self.handle_figure(powerups[0]["id"], powerups[0].get("variant_id", 0), powerups[0])
            self.state["figures"] = figures
            return
        config = self.store.data
        devices = self._individual_devices()
        distinct_elements = []
        for figure in figures:
            if figure["element"] not in distinct_elements:
                distinct_elements.append(figure["element"])
        if len(devices) < 2 or len(distinct_elements) < 2:
            first = figures[0]
            self.handle_figure(first["id"], first.get("variant_id", 0), first)
            self.state["figures"] = figures
            return
        elements = sorted(distinct_elements[:2])
        key = "+".join(elements)
        combo = config.get("element_combos", {}).get(key, {})
        colors = combo.get("colors", {})
        display = {
            "id": figures[0]["id"], "variant_id": figures[0].get("variant_id", 0),
            "name": " + ".join(figure["name"] for figure in figures),
            "element": " + ".join(elements), "elements": elements, "combo": True,
            "color": colors.get(elements[0]) or config["element_colors"][elements[0]],
        }
        self.state.update({"figure": display, "figures": figures, "updated_at": time.time()})
        if self.portal:
            self.portal.set_color(display["color"])
        outputs = combo.get("outputs", {})
        split = (len(devices) + 1) // 2
        resolved = {}
        for index, device in enumerate(devices):
            assigned = elements[0] if index < split else elements[1]
            resolved[device["device"]] = dict(outputs.get(device["device"], {}))
            resolved[device["device"]].setdefault("color", colors.get(assigned) or config["element_colors"][assigned])
        self._activate_palette(f"{elements[0].title()} + {elements[1].title()}", display["color"], resolved, combo, "combo")

    def handle_default(self):
        config = self.store.data
        profile = config.get("default_palette", {})
        color = profile.get("color") or config["element_colors"]["default"]
        if self.portal:
            self.portal.set_color(color)
        self.state.update({"figure": None, "figures": [], "updated_at": time.time()})
        self._activate_palette("No Skylander", color, profile.get("outputs", {}), profile, "default")

    def preview_element(self, element: str):
        config = self.store.data
        color = config["element_colors"].get(element, config["element_colors"].get("unknown", "#708090"))
        preview = {
            "id": -1, "variant_id": 0, "name": f"{element.title()} preview",
            "element": element, "color": color, "preview": True,
        }
        self.state.update({"figure": preview, "figures": [], "updated_at": time.time()})
        if self.portal:
            self.portal.set_color(color)
        self._activate_palette(
            f"{element.title()} preview", color,
            config.get("element_outputs", {}).get(element, {}),
            config.get("element_actions", {}).get(element, {}), "preview",
        )

    def handle_remove(self):
        self.handle_default()
