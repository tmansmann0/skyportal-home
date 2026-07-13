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
    assert b"settings.js" in response.data

    dashboard = web.get("/")
    assert b'href="/settings"' in dashboard.data
    assert b'id="goveeKey"' not in dashboard.data


def test_login_next_rejects_external_redirect(tmp_path):
    web, store = client(tmp_path)
    response = web.post(
        "/login",
        data={"token": store.data["setup_token"], "next": "//example.com"},
    )
    assert response.headers["Location"] == "/"
