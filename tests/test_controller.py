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


class FakeHomeAssistant:
    calls = []

    def __init__(self, url, token):
        pass

    def activate_scene(self, scene):
        self.calls.append(scene)


def figures():
    return [
        {"id": 1, "variant_id": 0, "name": "Air One", "element": "air"},
        {"id": 2, "variant_id": 0, "name": "Fire Two", "element": "fire"},
    ]


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


def test_dreamview_palette_activates_saved_group_instead_of_lights(monkeypatch):
    monkeypatch.setattr(controller_module, "GoveeClient", FakeGovee)
    FakeGovee.calls = []
    light = {"device": "light", "deviceName": "Desk light", "sku": "H1"}
    group = {
        "device": "dream-group", "deviceName": "Scenic DreamView",
        "sku": "DreamViewScenic", "capabilities": [{
            "type": "devices.capabilities.on_off", "instance": "powerSwitch",
        }],
    }
    store = Store([light, group])
    store.data["element_actions"] = {"air": {
        "action_mode": "dreamview", "dreamview_device": "dream-group",
    }}

    controller = Controller(store)
    controller.handle_figure(1, figure=figures()[0])
    controller.handle_figure(1, figure=figures()[0])

    assert FakeGovee.calls == [
        ("dream-group", {
            "type": "devices.capabilities.on_off",
            "instance": "powerSwitch",
            "value": 1,
        }, False),
        ("dream-group", {
            "type": "devices.capabilities.on_off",
            "instance": "powerSwitch",
            "value": 0,
        }, False),
        ("dream-group", {
            "type": "devices.capabilities.on_off",
            "instance": "powerSwitch",
            "value": 1,
        }, False),
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


def test_home_assistant_mode_stops_dreamview_first(monkeypatch):
    monkeypatch.setattr(controller_module, "GoveeClient", FakeGovee)
    monkeypatch.setattr(controller_module, "HomeAssistantClient", FakeHomeAssistant)
    FakeGovee.calls = []
    FakeHomeAssistant.calls = []
    group = {"device": "group", "sku": "DreamViewScenic", "deviceName": "Bonfire"}
    store = Store([group])
    store.data["home_assistant"] = {"url": "http://ha", "token": "token"}
    store.data["element_actions"] = {
        "fire": {"action_mode": "dreamview", "dreamview_device": "group"},
        "air": {
            "action_mode": "home_assistant", "ha_scene": "scene.portal",
        },
    }
    controller = Controller(store)

    controller.handle_figure(2, figure=figures()[1])
    controller.handle_figure(1, figure=figures()[0])

    assert FakeGovee.calls == [
        ("group", {
            "type": "devices.capabilities.on_off",
            "instance": "powerSwitch",
            "value": 1,
        }, False),
        ("group", {
            "type": "devices.capabilities.on_off",
            "instance": "powerSwitch",
            "value": 0,
        }, False),
    ]
    assert FakeHomeAssistant.calls == ["scene.portal"]


def test_dreamview_group_does_not_enable_two_light_combo(monkeypatch):
    monkeypatch.setattr(controller_module, "GoveeClient", FakeGovee)
    FakeGovee.calls = []
    devices = [
        {"device": "only", "sku": "H1"},
        {"device": "group", "sku": "DreamViewScenic"},
    ]
    controller = Controller(Store(devices))

    controller.handle_figures(figures())

    assert FakeGovee.calls == [("only", "#AAAAAA", 75)]
    assert "combo" not in controller.state["figure"]


def test_govee_transition_stops_only_an_active_dreamview(monkeypatch):
    monkeypatch.setattr(controller_module, "GoveeClient", FakeGovee)
    FakeGovee.calls = []
    devices = [
        {"device": "light", "sku": "H1"},
        {"device": "group", "sku": "DreamViewScenic"},
    ]
    store = Store(devices)
    store.data["element_actions"] = {
        "fire": {"action_mode": "dreamview", "dreamview_device": "group"},
        "air": {"action_mode": "govee"},
    }
    controller = Controller(store)

    controller.handle_figure(1, figure=figures()[0])
    controller.handle_figure(1, figure=figures()[0])
    assert FakeGovee.calls == [("light", "#AAAAAA", 75), ("light", "#AAAAAA", 75)]

    FakeGovee.calls = []
    controller.handle_figure(2, figure=figures()[1])
    controller.handle_figure(1, figure=figures()[0])

    assert FakeGovee.calls == [
        ("group", {
            "type": "devices.capabilities.on_off",
            "instance": "powerSwitch",
            "value": 1,
        }, False),
        ("group", {
            "type": "devices.capabilities.on_off",
            "instance": "powerSwitch",
            "value": 0,
        }, False),
        ("light", "#AAAAAA", 75),
    ]


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
