from skyportal import controller as controller_module
from skyportal.controller import Controller
from skyportal.figures import identify_all_present


class Store:
    def __init__(self, devices):
        self.data = {
            "govee": {"api_key": "test", "devices": devices, "brightness": 75},
            "home_assistant": {"url": "", "token": ""},
            "element_colors": {"air": "#AAAAAA", "fire": "#FF0000", "water": "#168CFF"},
            "element_outputs": {}, "element_combos": {}, "figure_overrides": {},
            "element_actions": {}, "figure_palettes": {}, "powerup_palettes": {},
            "default_palette": {}, "recent_figures": [], "recent_powerups": [], "history": [],
            "behavior": {"on_remove": "leave"},
        }

    def save(self):
        pass


class FakeGovee:
    calls = []

    def __init__(self, api_key):
        self.api_key = api_key

    def set_color(self, device, color, brightness):
        self.calls.append((device["device"], color, brightness))

    def set_capability(self, device, capability, power_on=True):
        self.calls.append((device["device"], capability, power_on))

    def set_white(self, device, kelvin, brightness):
        self.calls.append((device["device"], "white", kelvin, brightness))


class FakeHomeAssistant:
    calls = []

    def __init__(self, url, token):
        pass

    def activate_scene(self, scene):
        self.calls.append(scene)


class FakeLifx:
    calls = []

    def set_color(self, device, color, brightness):
        self.calls.append((device["serial"], color, brightness))

    def set_white(self, device, kelvin, brightness):
        self.calls.append((device["serial"], "white", kelvin, brightness))


class FakeWled:
    calls = []

    def set_color(self, device, color, brightness):
        self.calls.append((device["id"], "color", color, brightness))

    def set_white(self, device, kelvin, brightness):
        self.calls.append((device["id"], "white", kelvin, brightness))

    def set_preset(self, device, preset_id):
        self.calls.append((device["id"], "preset", preset_id))


def figures():
    return [
        {"id": 1, "variant_id": 0, "name": "Air One", "element": "air"},
        {"id": 2, "variant_id": 0, "name": "Fire Two", "element": "fire"},
    ]


def test_transient_portal_identity_is_rejected_before_switching():
    controller = Controller(Store([]), confidence_seconds=1.25)
    controller.last_slots = {0: (15, 0)}

    assert controller._transition_confirmed({0: (1, 0)}, now=10.0) is False
    assert controller._transition_confirmed({0: (1, 0)}, now=10.9) is False
    assert controller._transition_confirmed({0: (15, 0)}, now=11.0) is False
    assert controller.pending_slots is None


def test_stable_portal_identity_is_confirmed_after_confidence_window():
    controller = Controller(Store([]), confidence_seconds=1.25)
    controller.last_slots = {0: (15, 0)}

    assert controller._transition_confirmed({0: (1, 0)}, now=20.0) is False
    assert controller._transition_confirmed({0: (1, 0)}, now=21.0) is False
    assert controller._transition_confirmed({0: (1, 0)}, now=21.25) is True
    assert controller.pending_slots is None


def test_portal_confidence_setting_takes_effect_without_restarting_controller():
    store = Store([])
    controller = Controller(store)
    controller.last_slots = {0: (15, 0)}

    assert controller._transition_confirmed({0: (1, 0)}, now=20.0) is False
    assert controller._transition_confirmed({0: (1, 0)}, now=20.5) is False

    store.data["behavior"]["portal_confidence_seconds"] = 0.5

    assert controller._transition_confirmed({0: (1, 0)}, now=20.5) is True


def test_zero_portal_confidence_accepts_first_reading_immediately():
    store = Store([])
    store.data["behavior"]["portal_confidence_seconds"] = 0
    controller = Controller(store)
    controller.last_slots = {0: (15, 0)}

    assert controller._transition_confirmed({0: (1, 0)}, now=20.0) is True
    assert controller.pending_slots is None


def test_combo_splits_lights_as_evenly_as_possible(monkeypatch):
    monkeypatch.setattr(controller_module, "GoveeClient", FakeGovee)
    FakeGovee.calls = []
    devices = [{"device": str(index), "deviceName": str(index)} for index in range(3)]
    controller = Controller(Store(devices))

    controller.handle_figures(figures())

    assert FakeGovee.calls == [
        ("0", "#AAAAAA", 75), ("1", "#AAAAAA", 75), ("2", "#FF0000", 75),
    ]
    assert controller.state["figure"]["combo"] is True


def test_mixed_swap_halves_activate_an_element_combo(monkeypatch):
    monkeypatch.setattr(controller_module, "GoveeClient", FakeGovee)
    FakeGovee.calls = []
    devices = [{"device": "left"}, {"device": "right"}]
    controller = Controller(Store(devices))

    controller.handle_figures(identify_all_present([(2004, 8192), (1015, 8192)]))

    assert FakeGovee.calls == [("left", "#FF0000", 75), ("right", "#168CFF", 75)]
    assert controller.state["figure"]["name"] == "Blast + Buckler"
    assert controller.state["figure"]["combo"] is True


def test_combo_profile_controls_individual_brightness(monkeypatch):
    monkeypatch.setattr(controller_module, "GoveeClient", FakeGovee)
    FakeGovee.calls = []
    devices = [{"device": "left"}, {"device": "right"}]
    store = Store(devices)
    store.data["element_combos"] = {
        "air+fire": {
            "elements": ["air", "fire"], "colors": {},
            "outputs": {"right": {"mode": "color", "color": "#123456", "brightness": 22}},
        }
    }

    Controller(store).handle_figures(figures())

    assert FakeGovee.calls == [("left", "#AAAAAA", 75), ("right", "#123456", 22)]


def test_lifx_bulbs_join_palette_outputs_and_combo_counts(monkeypatch):
    monkeypatch.setattr(controller_module, "GoveeClient", FakeGovee)
    monkeypatch.setattr(controller_module, "LifxLanClient", FakeLifx)
    FakeGovee.calls = []
    FakeLifx.calls = []
    store = Store([{"device": "govee"}])
    store.data["lifx"] = {
        "brightness": 64,
        "devices": [{
            "serial": "d073d5123456", "label": "Desk",
            "ip": "192.168.1.44", "port": 56700,
        }],
    }

    controller = Controller(store)
    controller.handle_figures(figures())

    assert controller.state["figure"]["combo"] is True
    assert FakeGovee.calls == [("govee", "#AAAAAA", 75)]
    assert FakeLifx.calls == [("d073d5123456", "#FF0000", 64)]


def test_white_profiles_dispatch_native_govee_and_lifx_temperature(monkeypatch):
    monkeypatch.setattr(controller_module, "GoveeClient", FakeGovee)
    monkeypatch.setattr(controller_module, "LifxLanClient", FakeLifx)
    FakeGovee.calls = []
    FakeLifx.calls = []
    store = Store([{
        "device": "govee",
        "capabilities": [{"instance": "colorTemperatureK"}],
    }])
    store.data["lifx"] = {
        "brightness": 64,
        "devices": [{
            "serial": "d073d5123456", "label": "Desk",
            "ip": "192.168.1.44", "port": 56700,
            "temperature_range": [2500, 9000],
        }],
    }
    store.data["element_outputs"] = {"air": {
        "govee": {"mode": "white", "kelvin": 4200, "brightness": 55},
        "lifx:d073d5123456": {"mode": "white", "kelvin": 3200, "brightness": 45},
    }}

    Controller(store).handle_figure(1, figure=figures()[0])

    assert FakeGovee.calls == [("govee", "white", 4200, 55)]
    assert FakeLifx.calls == [("d073d5123456", "white", 3200, 45)]


def test_wled_devices_dispatch_color_white_and_presets(monkeypatch):
    monkeypatch.setattr(controller_module, "WledClient", FakeWled)
    FakeWled.calls = []
    store = Store([])
    store.data["wled"] = {
        "brightness": 70,
        "devices": [
            {"id": "rgb", "name": "RGB", "address": "192.168.1.80"},
            {"id": "white", "name": "White", "address": "192.168.1.81"},
            {"id": "preset", "name": "Preset", "address": "192.168.1.82"},
        ],
    }

    errors = Controller(store)._apply_outputs("#123456", {
        "wled:rgb": {"mode": "color", "brightness": 30},
        "wled:white": {"mode": "white", "kelvin": 4200, "brightness": 45},
        "wled:preset": {"mode": "preset", "preset": 7},
    })

    assert errors == []
    assert FakeWled.calls == [
        ("rgb", "color", "#123456", 30),
        ("white", "white", 4200, 45),
        ("preset", "preset", 7),
    ]


def test_govee_mode_does_not_also_activate_home_assistant(monkeypatch):
    monkeypatch.setattr(controller_module, "GoveeClient", FakeGovee)
    monkeypatch.setattr(controller_module, "HomeAssistantClient", FakeHomeAssistant)
    FakeGovee.calls = []
    FakeHomeAssistant.calls = []
    store = Store([{"device": "only", "sku": "H1"}])
    store.data["home_assistant"] = {"url": "http://ha", "token": "token"}
    store.data["element_actions"] = {"air": {
        "action_mode": "govee", "ha_scene": "scene.should_not_run",
    }}

    Controller(store).handle_figure(1, figure=figures()[0])

    assert FakeGovee.calls == [("only", "#AAAAAA", 75)]
    assert FakeHomeAssistant.calls == []


def test_single_light_uses_standard_behavior(monkeypatch):
    monkeypatch.setattr(controller_module, "GoveeClient", FakeGovee)
    FakeGovee.calls = []
    controller = Controller(Store([{"device": "only"}]))

    controller.handle_figures(figures())

    assert FakeGovee.calls == [("only", "#AAAAAA", 75)]
    assert "combo" not in controller.state["figure"]


def test_default_palette_runs_when_portal_is_empty(monkeypatch):
    monkeypatch.setattr(controller_module, "GoveeClient", FakeGovee)
    FakeGovee.calls = []
    store = Store([{"device": "only"}])
    store.data["element_colors"]["default"] = "#101010"

    Controller(store).handle_default()

    assert FakeGovee.calls == [("only", "#101010", 75)]


def test_figure_palette_can_trigger_only_home_assistant(monkeypatch):
    monkeypatch.setattr(controller_module, "GoveeClient", FakeGovee)
    monkeypatch.setattr(controller_module, "HomeAssistantClient", FakeHomeAssistant)
    FakeGovee.calls = []
    FakeHomeAssistant.calls = []
    store = Store([{"device": "only"}])
    store.data["home_assistant"] = {"url": "http://ha", "token": "token"}
    store.data["figure_palettes"] = {"1": {"lights_enabled": False, "ha_scene": "scene.spyro"}}

    Controller(store).handle_figure(1, figure={"id": 1, "variant_id": 0, "name": "Spyro", "element": "air", "kind": "figure"})

    assert FakeHomeAssistant.calls == ["scene.spyro"]
    assert FakeGovee.calls == []
