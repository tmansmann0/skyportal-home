from skyportal import controller as controller_module
from skyportal.controller import Controller


class Store:
    def __init__(self, devices):
        self.data = {
            "govee": {"api_key": "test", "devices": devices, "brightness": 75},
            "home_assistant": {"url": "", "token": ""},
            "element_colors": {"air": "#AAAAAA", "fire": "#FF0000"},
            "element_outputs": {}, "element_combos": {}, "figure_overrides": {},
            "behavior": {"on_remove": "leave"},
        }


class FakeGovee:
    calls = []

    def __init__(self, api_key):
        self.api_key = api_key

    def set_color(self, device, color, brightness):
        self.calls.append((device["device"], color, brightness))

    def set_capability(self, device, capability):
        self.calls.append((device["device"], capability, None))


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


def test_single_light_uses_standard_behavior(monkeypatch):
    monkeypatch.setattr(controller_module, "GoveeClient", FakeGovee)
    FakeGovee.calls = []
    controller = Controller(Store([{"device": "only"}]))

    controller.handle_figures(figures())

    assert FakeGovee.calls == [("only", "#AAAAAA", 75)]
    assert "combo" not in controller.state["figure"]
