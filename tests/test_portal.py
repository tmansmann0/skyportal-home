from skyportal.portal import Portal


class FakeDevice:
    def __init__(self):
        self.writes = []
        self.responses = []

    def write(self, data):
        self.writes.append(data)

    def read(self, length, timeout):
        return self.responses.pop(0) if self.responses else []


def test_report_format():
    report = Portal._report("C", 1, 2, 3)
    assert len(report) == 33
    assert report[:5] == [0, ord("C"), 1, 2, 3]


def test_identity_is_little_endian():
    portal = Portal(FakeDevice())
    portal.query = lambda slot, block: bytes([16, 0, 1, 24, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    assert portal.read_identity(0) == (16, 6145)


def test_query_uses_portal_slot_index():
    device = FakeDevice()
    device.responses.append(bytes([ord("Q"), 0x22, 1]) + bytes(range(16)) + bytes(13))
    portal = Portal(device)

    assert portal.query(2, 1) == bytes(range(16))
    assert device.writes[0][1:4] == [ord("Q"), 0x12, 1]


def test_usb_close_disposes_stale_resources():
    class UsbDevice:
        attached = False

        def attach_kernel_driver(self, interface):
            self.attached = interface == 0

    class UsbUtil:
        released = False
        disposed = False

        def release_interface(self, device, interface):
            self.released = interface == 0

        def dispose_resources(self, device):
            self.disposed = True

    device = UsbDevice()
    util = UsbUtil()
    portal = Portal()
    portal.device = device
    portal._usb = True
    portal._usb_util = util
    portal._detached_kernel_driver = True

    portal.close()

    assert util.released is True
    assert util.disposed is True
    assert device.attached is True
    assert portal.device is None
    assert portal._usb_util is None
