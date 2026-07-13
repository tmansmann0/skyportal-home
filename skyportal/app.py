import os
import time
from functools import wraps

from flask import Flask, jsonify, redirect, render_template, request, session, url_for

from .config import ConfigStore
from .controller import Controller
from .figures import CHARACTERS, ELEMENT_COLORS, FIGURES, POWER_UPS
from .outputs import GoveeClient


def create_app(store=None, start_controller=True):
    app = Flask(__name__)
    store = store or ConfigStore()
    app.secret_key = os.environ.get("SKYPORTAL_SESSION_SECRET", store.data["setup_token"])
    controller = Controller(store)
    app.extensions["skyportal_store"] = store
    app.extensions["skyportal_controller"] = controller

    if start_controller:
        controller.start()

    def authenticated(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not session.get("authenticated"):
                return redirect(url_for("login", next=request.path))
            return fn(*args, **kwargs)
        return wrapper

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        if request.method == "POST":
            if request.form.get("token") == store.data["setup_token"]:
                session["authenticated"] = True
                target = request.form.get("next") or url_for("index")
                return redirect(target if target.startswith("/") and not target.startswith("//") else url_for("index"))
            error = "That setup token is incorrect."
        return render_template("login.html", error=error)

    @app.get("/")
    @authenticated
    def index():
        return render_template(
            "index.html", config=store.public(), state=controller.state,
            elements=ELEMENT_COLORS, palette_elements=[element for element in ELEMENT_COLORS if element != "default"],
            figures=CHARACTERS, powerups=POWER_UPS,
        )

    @app.get("/settings")
    @authenticated
    def settings_page():
        return render_template("settings.html", config=store.public(), state=controller.state)

    @app.post("/api/settings")
    @authenticated
    def settings():
        data = request.get_json(force=True)
        govee = data.get("govee", {})
        ha = data.get("home_assistant", {})
        if govee.get("api_key") and govee["api_key"] != "configured":
            store.data["govee"]["api_key"] = govee["api_key"].strip()
        if "devices" in govee:
            store.data["govee"]["devices"] = govee["devices"]
        if "brightness" in govee:
            store.data["govee"]["brightness"] = max(1, min(100, int(govee["brightness"])))
        if "element_colors" in data:
            for element in ELEMENT_COLORS:
                value = data["element_colors"].get(element)
                if value and len(value) == 7 and value.startswith("#"):
                    store.data["element_colors"][element] = value.upper()
        if "element_outputs" in data:
            store.data["element_outputs"] = {
                element: outputs for element, outputs in data["element_outputs"].items()
                if element in ELEMENT_COLORS and isinstance(outputs, dict)
            }
        if "element_actions" in data:
            store.data["element_actions"] = data["element_actions"]
        if "element_combos" in data:
            store.data["element_combos"] = {
                key: combo for key, combo in data["element_combos"].items()
                if isinstance(combo, dict) and len(combo.get("elements", [])) == 2
                and all(element in ELEMENT_COLORS for element in combo["elements"])
            }
        for key in ("figure_palettes", "powerup_palettes"):
            if key in data and isinstance(data[key], dict):
                store.data[key] = data[key]
        if "default_palette" in data and isinstance(data["default_palette"], dict):
            store.data["default_palette"] = data["default_palette"]
        if ha.get("url") is not None:
            store.data["home_assistant"]["url"] = ha["url"].strip().rstrip("/")
        if ha.get("token") and ha["token"] != "configured":
            store.data["home_assistant"]["token"] = ha["token"].strip()
        if "figure_overrides" in data:
            store.data["figure_overrides"] = data["figure_overrides"]
        if "behavior" in data:
            store.data["behavior"].update(data["behavior"])
        history = store.data.setdefault("history", [])
        history.insert(0, {"at": time.time(), "event": "settings", "label": "Configuration saved", "detail": ""})
        del history[50:]
        store.save()
        return jsonify({"ok": True, "config": store.public()})

    @app.post("/api/govee/discover")
    @authenticated
    def discover_govee():
        candidate = request.get_json(silent=True) or {}
        key = candidate.get("api_key") or store.data["govee"]["api_key"]
        if not key or key == "configured":
            return jsonify({"ok": False, "error": "Enter a Govee API key first."}), 400
        try:
            devices = GoveeClient(key).discover()
            lights = [d for d in devices if any(c.get("instance") == "colorRgb" for c in d.get("capabilities", []))]
            return jsonify({"ok": True, "devices": lights})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 502

    @app.post("/api/govee/scenes")
    @authenticated
    def discover_govee_scenes():
        candidate = request.get_json(silent=True) or {}
        device_id = candidate.get("device")
        device = next((item for item in store.data["govee"]["devices"] if item.get("device") == device_id), None)
        if not device:
            return jsonify({"ok": False, "error": "Select and save this light first."}), 404
        key = store.data["govee"]["api_key"]
        if not key:
            return jsonify({"ok": False, "error": "Configure a Govee API key first."}), 400
        try:
            return jsonify({"ok": True, "scenes": GoveeClient(key).discover_scenes(device)})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 502

    @app.post("/api/test/<element>")
    @authenticated
    def test_element(element):
        if element not in ELEMENT_COLORS:
            return jsonify({"ok": False, "error": "Unknown element"}), 404
        try:
            if element == "default":
                controller.handle_default()
            else:
                controller.handle_figure(next(fid for fid, f in FIGURES.items() if f["element"] == element))
            return jsonify({"ok": True})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 502

    @app.post("/api/test-combo")
    @authenticated
    def test_combo():
        elements = (request.get_json(silent=True) or {}).get("elements", [])
        if len(elements) != 2 or any(element not in ELEMENT_COLORS or element == "default" for element in elements):
            return jsonify({"ok": False, "error": "Choose two valid elements."}), 400
        try:
            figures = [next(figure for figure in FIGURES.values() if figure["element"] == element) for element in elements]
            controller.handle_figures(figures)
            return jsonify({"ok": True})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 502

    @app.get("/api/status")
    def status():
        return jsonify({
            **controller.state,
            "recent_figures": store.data.get("recent_figures", []),
            "recent_powerups": store.data.get("recent_powerups", []),
            "history": store.data.get("history", []),
        })

    @app.get("/health")
    def health():
        return jsonify({"ok": True, "portal": controller.state["portal"]})

    return app


def main():
    from waitress import serve
    app = create_app()
    serve(app, host="0.0.0.0", port=int(os.environ.get("SKYPORTAL_PORT", "8099")), threads=4)


if __name__ == "__main__":
    main()
