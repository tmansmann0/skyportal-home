import os
from functools import wraps

from flask import Flask, jsonify, redirect, render_template, request, session, url_for

from .config import ConfigStore
from .controller import Controller
from .figures import ELEMENT_COLORS, FIGURES
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
                return redirect(url_for("index"))
            error = "That setup token is incorrect."
        return render_template("login.html", error=error)

    @app.get("/")
    @authenticated
    def index():
        return render_template(
            "index.html", config=store.data, state=controller.state,
            elements=ELEMENT_COLORS, figures=FIGURES,
        )

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
        if ha.get("url") is not None:
            store.data["home_assistant"]["url"] = ha["url"].strip().rstrip("/")
        if ha.get("token") and ha["token"] != "configured":
            store.data["home_assistant"]["token"] = ha["token"].strip()
        if "figure_overrides" in data:
            store.data["figure_overrides"] = data["figure_overrides"]
        if "behavior" in data:
            store.data["behavior"].update(data["behavior"])
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

    @app.post("/api/test/<element>")
    @authenticated
    def test_element(element):
        if element not in ELEMENT_COLORS:
            return jsonify({"ok": False, "error": "Unknown element"}), 404
        try:
            controller.handle_figure(next(fid for fid, f in FIGURES.items() if f["element"] == element))
            return jsonify({"ok": True})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 502

    @app.get("/api/status")
    def status():
        return jsonify(controller.state)

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
