import socket
import struct

from skyportal.outputs import GoveeClient, GoveeSceneCache, LifxLanClient, OutputError


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


def test_govee_scene_cache_only_refreshes_when_forced():
    client = GoveeClient("secret", SceneSession())
    cache = GoveeSceneCache()
    device = {"sku": "H123", "device": "AA:BB"}

    first = cache.get(client, device)
    second = cache.get(client, device)
    refreshed = cache.get(client, device, force=True)

    assert first == second == refreshed
    assert len(client.session.calls) == 4


class LifxSocket:
    def __init__(self, source=2):
        self.source = source
        self.calls = []
        self.responses = []

    def setsockopt(self, *args): pass
    def bind(self, *args): pass
    def settimeout(self, *args): pass
    def close(self): pass

    def response(self, packet_type, serial, payload=b""):
        target = bytes.fromhex(serial) + b"\0\0"
        header = struct.pack(
            "<HHI8s6sBB8sHH", 36 + len(payload), 0x1400, self.source,
            target, b"\0" * 6, 0, 0, b"\0" * 8, packet_type, 0,
        )
        return header + payload

    def sendto(self, packet, address):
        self.calls.append((packet, address))
        packet_type = struct.unpack_from("<H", packet, 32)[0]
        if packet_type == LifxLanClient.GET_SERVICE:
            payload = struct.pack("<BI", LifxLanClient.UDP_SERVICE, 56700)
            self.responses.append((self.response(3, "d073d5123456", payload), ("192.168.1.44", 56700)))
        elif packet_type == LifxLanClient.GET_LABEL:
            payload = b"Kitchen Lamp\0".ljust(32, b"\0")
            self.responses.append((self.response(25, "d073d5123456", payload), ("192.168.1.44", 56700)))

    def recvfrom(self, _size):
        if not self.responses:
            raise socket.timeout
        return self.responses.pop(0)


def test_lifx_lan_discovery_uses_service_port_and_reads_label():
    sock = LifxSocket()
    client = LifxLanClient(socket_factory=lambda *_args: sock, source=2)

    devices = client.discover(timeout=0.01)

    assert devices == [{
        "serial": "d073d5123456", "label": "Kitchen Lamp",
        "ip": "192.168.1.44", "port": 56700,
    }]
    discovery_packet, destination = sock.calls[0]
    assert destination == ("255.255.255.255", 56700)
    assert struct.unpack_from("<H", discovery_packet, 2)[0] & 0x2000
    assert struct.unpack_from("<H", discovery_packet, 32)[0] == 2


def test_lifx_set_color_sends_hsbk_then_power_on():
    sock = LifxSocket()
    client = LifxLanClient(socket_factory=lambda *_args: sock, source=2)
    device = {"serial": "d073d5123456", "label": "Kitchen", "ip": "192.168.1.44", "port": 56700}

    client.set_color(device, "#00FF00", brightness=40, duration_ms=300)

    assert [struct.unpack_from("<H", packet, 32)[0] for packet, _ in sock.calls] == [102, 117]
    color = struct.unpack_from("<BHHHHI", sock.calls[0][0], 36)
    assert color == (0, 21845, 65535, round(0.4 * 65535), 3500, 300)
    assert struct.unpack_from("<HI", sock.calls[1][0], 36) == (65535, 300)
    assert all(destination == ("192.168.1.44", 56700) for _, destination in sock.calls)


def test_lifx_device_metadata_is_strictly_normalized():
    assert LifxLanClient.normalize_device({
        "serial": "D0:73:D5:12:34:56", "label": "  Office  ",
        "ip": "192.168.1.1", "port": "56700", "ignored": "value",
    }) == {
        "serial": "d073d5123456", "label": "Office",
        "ip": "192.168.1.1", "port": 56700,
    }

    try:
        LifxLanClient.normalize_device({"serial": "../../bad", "ip": "::1"})
    except OutputError:
        pass
    else:
        raise AssertionError("invalid metadata should be rejected")
