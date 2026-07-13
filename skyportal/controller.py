import logging
import threading
import time

from .figures import identify, identify_present
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
                    figure = identify_present(list(current.values()))
                    self.handle_figure(figure["id"], figure["variant_id"], figure)
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
                for device in config["govee"]["devices"]:
                    client.set_color(device, color, int(config["govee"]["brightness"]))
        except Exception as exc:
            log.exception("Output error")
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
