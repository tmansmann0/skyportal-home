from skyportal.outputs import GoveeClient


class Response:
    def raise_for_status(self): pass
    def json(self): return {"code": 200, "message": "success"}


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
