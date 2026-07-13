from skyportal.outputs import GoveeClient


class Response:
    def __init__(self, payload=None): self.payload = payload or {"code": 200, "message": "success"}
    def raise_for_status(self): pass
    def json(self): return self.payload


class Session:
    def __init__(self): self.calls = []
    def post(self, url, **kwargs): self.calls.append((url, kwargs)); return Response()


def test_govee_rgb_conversion():
    session = Session()
    GoveeClient("secret", session).set_color({"sku": "H123", "device": "AA:BB"}, "#12ABEF", 80)
    assert len(session.calls) == 3
    color = session.calls[1][1]["json"]["payload"]["capability"]
    assert color["value"] == 0x12ABEF
    assert session.calls[2][1]["json"]["payload"]["capability"]["value"] == 80


def test_govee_capability_control_powers_on_first():
    session = Session()
    capability = {"type": "devices.capabilities.dynamic_scene", "instance": "lightScene", "value": 42}
    GoveeClient("secret", session).set_capability({"sku": "H123", "device": "AA:BB"}, capability)
    assert len(session.calls) == 2
    assert session.calls[1][1]["json"]["payload"]["capability"] == capability


class SceneSession(Session):
    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        instance = "diyScene" if url.endswith("diy-scenes") else "lightScene"
        return Response({"code": 200, "payload": {"capabilities": [{
            "type": "devices.capabilities.dynamic_scene", "instance": instance,
            "parameters": {"options": [{"name": instance, "value": 7}]},
        }]}})


def test_govee_scene_discovery_normalizes_capabilities():
    scenes = GoveeClient("secret", SceneSession()).discover_scenes({"sku": "H123", "device": "AA:BB"})
    assert [scene["name"] for scene in scenes] == ["lightScene", "diyScene"]
    assert scenes[0]["capability"]["value"] == 7
