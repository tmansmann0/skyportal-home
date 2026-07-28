from skyportal import app as app_module
from skyportal.app import create_app
from skyportal.config import ConfigStore


def client(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    app = create_app(store=store, start_controller=False)
    app.config["TESTING"] = True
    return app.test_client(), store


def test_settings_are_on_a_separate_authenticated_page(tmp_path):
    web, store = client(tmp_path)

    response = web.get("/settings")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login?next=/settings")

    response = web.post(
        "/login?next=/settings",
        data={"token": store.data["setup_token"], "next": "/settings"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b'id="goveeKey"' in response.data
    assert b'id="haUrl"' in response.data
    assert b'id="portalConfidence"' in response.data
    assert b'value="1.25"' in response.data
    assert b"settings.js" in response.data

    dashboard = web.get("/")
    assert b'href="/settings"' in dashboard.data
    assert b'id="goveeKey"' not in dashboard.data
    assert b'id="previewCustomize"' in dashboard.data


def test_login_next_rejects_external_redirect(tmp_path):
    web, store = client(tmp_path)
    response = web.post(
        "/login",
        data={"token": store.data["setup_token"], "next": "//example.com"},
    )
    assert response.headers["Location"] == "/"


def test_palette_preview_endpoints(tmp_path):
    web, store = client(tmp_path)
    with web.session_transaction() as session:
        session["authenticated"] = True

    response = web.post("/api/test/fire")
    assert response.get_json()["ok"]

    response = web.post("/api/test-figure/figure/0")
    assert response.get_json()["ok"]

    response = web.post("/api/test-figure/not-a-kind/0")
    assert response.status_code == 404


def test_discovery_includes_only_individual_color_lights(tmp_path, monkeypatch):
    class FakeGovee:
        def __init__(self, api_key):
            self.api_key = api_key

        def discover(self):
            return [
                {"device": "group", "sku": "DreamViewScenic", "capabilities": [{
                    "type": "devices.capabilities.on_off", "instance": "powerSwitch",
                }]},
                {"device": "dream", "sku": "H1", "capabilities": [{
                    "type": "devices.capabilities.toggle", "instance": "dreamViewToggle",
                }]},
                {"device": "light", "sku": "H2", "capabilities": [{
                    "type": "devices.capabilities.color_setting", "instance": "colorRgb",
                }]},
                {"device": "sensor", "sku": "H3", "capabilities": []},
            ]

    monkeypatch.setattr(app_module, "GoveeClient", FakeGovee)
    web, store = client(tmp_path)
    store.data["govee"]["api_key"] = "test"
    with web.session_transaction() as session:
        session["authenticated"] = True

    response = web.post("/api/govee/discover", json={})

    assert response.status_code == 200
    payload = response.get_json()
    assert [device["device"] for device in payload["devices"]] == ["light"]
    assert payload["scene_devices"] == 0


def test_legacy_dreamview_configuration_migrates_to_govee(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('''{
      "govee": {"devices": [
        {"device": "group", "sku": "DreamViewScenic"},
        {"device": "light", "sku": "H1"}
      ]},
      "element_actions": {
        "fire": {"action_mode": "dreamview", "dreamview_device": "group"}
      }
    }''')

    store = ConfigStore(path)

    assert [device["device"] for device in store.data["govee"]["devices"]] == ["light"]
    assert store.data["element_actions"]["fire"] == {"action_mode": "govee"}


def test_lifx_discovery_is_local_and_requires_authentication(tmp_path, monkeypatch):
    class FakeLifx:
        def discover(self):
            return [{
                "serial": "d073d5123456", "label": "Kitchen",
                "ip": "192.168.1.44", "port": 56700,
            }]

    monkeypatch.setattr(app_module, "LifxLanClient", FakeLifx)
    web, _ = client(tmp_path)

    assert web.post("/api/lifx/discover").status_code == 302
    with web.session_transaction() as session:
        session["authenticated"] = True

    response = web.post("/api/lifx/discover")

    assert response.status_code == 200
    assert response.get_json()["devices"][0]["label"] == "Kitchen"


def test_lifx_settings_store_only_normalized_device_metadata(tmp_path):
    web, store = client(tmp_path)
    with web.session_transaction() as session:
        session["authenticated"] = True

    response = web.post("/api/settings", json={
        "lifx": {
            "brightness": 42,
            "devices": [
                {
                    "serial": "D0:73:D5:12:34:56", "label": "Kitchen",
                    "ip": "192.168.1.44", "port": "56700", "untrusted": "discard me",
                },
                {"serial": "bad", "label": "Invalid", "ip": "not-an-ip", "port": 0},
            ],
        },
    })

    assert response.status_code == 200
    assert store.data["lifx"] == {
        "brightness": 42,
        "devices": [{
            "serial": "d073d5123456", "label": "Kitchen",
            "ip": "192.168.1.44", "port": 56700,
        }],
    }


def test_portal_confidence_setting_is_clamped_and_persisted(tmp_path):
    web, store = client(tmp_path)
    with web.session_transaction() as session:
        session["authenticated"] = True

    response = web.post("/api/settings", json={
        "behavior": {"portal_confidence_seconds": 10},
    })

    assert response.status_code == 200
    assert store.data["behavior"]["portal_confidence_seconds"] == 5.0
    assert ConfigStore(store.path).data["behavior"]["portal_confidence_seconds"] == 5.0
