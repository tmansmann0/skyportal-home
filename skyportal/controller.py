import logging
import threading
import time

from .figures import identify, identify_all_present
from .outputs import GoveeClient, HomeAssistantClient
from .portal import Portal

log = logging.getLogger(__name__)


class Controller:
    def __init__(self, store, portal_factory=Portal):
        self.store = store
        self.portal_factory = portal_factory
        self.portal = None
        self.stop_event = threading.Event()
        self.thread = None
        self.last_slots = {}
        self.state = {"portal": "disconnected", "figure": None, "last_error": None, "updated_at": None}

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
                current = {}
                for slot in slots:
                    identity = self.portal.read_identity(slot)
                    current[slot] = identity
                if current and current != self.last_slots:
                    self.handle_figures(identify_all_present(list(current.values())))
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

    def handle_figure(self, character_id: int, variant_id: int = 0, figure=None):
        figure = dict(figure or identify(character_id, variant_id))
        config = self.store.data
        override = config["figure_overrides"].get(str(character_id), {})
        color = override.get("color") or config["element_colors"][figure["element"]]
        figure["color"] = color
        self.state.update({"figure": figure, "last_error": None, "updated_at": time.time()})
        try:
            if self.portal:
                self.portal.set_color(color)
            scene = override.get("ha_scene", "").strip()
            ha = config["home_assistant"]
            if scene and ha["url"] and ha["token"]:
                HomeAssistantClient(ha["url"], ha["token"]).activate_scene(scene)
            if config["govee"]["api_key"]:
                client = GoveeClient(config["govee"]["api_key"])
                element_outputs = config.get("element_outputs", {}).get(figure["element"], {})
                device_errors = []
                for device in config["govee"]["devices"]:
                    try:
                        output = element_outputs.get(device["device"], {})
                        mode = output.get("mode", "color")
                        if mode in ("scene", "music") and output.get("capability"):
                            client.set_capability(device, output["capability"])
                        else:
                            client.set_color(
                                device, output.get("color") or color,
                                int(output.get("brightness", config["govee"]["brightness"])),
                            )
                    except Exception as exc:
                        name = device.get("deviceName") or device.get("sku") or device["device"]
                        log.exception("Govee output error for %s", name)
                        device_errors.append(f"{name}: {exc}")
                if device_errors:
                    self.state["last_error"] = "; ".join(device_errors)
        except Exception as exc:
            log.exception("Output error")
            self.state["last_error"] = str(exc)

    def handle_figures(self, figures: list[dict]):
        if not figures:
            return
        config = self.store.data
        devices = config["govee"]["devices"]
        distinct_elements = []
        for figure in figures:
            if figure["element"] not in distinct_elements:
                distinct_elements.append(figure["element"])
        if len(devices) < 2 or len(distinct_elements) < 2:
            first = figures[0]
            self.handle_figure(first["id"], first.get("variant_id", 0), first)
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
        self.state.update({"figure": display, "figures": figures, "last_error": None, "updated_at": time.time()})
        try:
            if self.portal:
                self.portal.set_color(display["color"])
            if not config["govee"]["api_key"]:
                return
            client = GoveeClient(config["govee"]["api_key"])
            outputs = combo.get("outputs", {})
            split = (len(devices) + 1) // 2
            errors = []
            for index, device in enumerate(devices):
                assigned_element = elements[0] if index < split else elements[1]
                assigned_color = colors.get(assigned_element) or config["element_colors"][assigned_element]
                output = outputs.get(device["device"], {})
                try:
                    if output.get("mode") in ("scene", "music") and output.get("capability"):
                        client.set_capability(device, output["capability"])
                    else:
                        client.set_color(
                            device, output.get("color") or assigned_color,
                            int(output.get("brightness", config["govee"]["brightness"])),
                        )
                except Exception as exc:
                    name = device.get("deviceName") or device.get("sku") or device["device"]
                    log.exception("Govee combo output error for %s", name)
                    errors.append(f"{name}: {exc}")
            if errors:
                self.state["last_error"] = "; ".join(errors)
        except Exception as exc:
            log.exception("Combo output error")
            self.state["last_error"] = str(exc)

    def handle_remove(self):
        self.state.update({"figure": None, "updated_at": time.time()})
        config = self.store.data
        if config["behavior"]["on_remove"] == "color":
            color = config["behavior"]["remove_color"]
            try:
                client = GoveeClient(config["govee"]["api_key"])
                for device in config["govee"]["devices"]:
                    client.set_color(device, color, int(config["govee"]["brightness"]))
            except Exception as exc:
                self.state["last_error"] = str(exc)
