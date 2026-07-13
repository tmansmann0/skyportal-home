import logging
import struct
import time

log = logging.getLogger(__name__)


class PortalError(RuntimeError):
    pass


class Portal:
    VID = 0x1430
    PID = 0x0150

    def __init__(self, device=None):
        self.device = device
        self._usb = False
        self._usb_core = None
        self._usb_util = None
        self._detached_kernel_driver = False

    def connect(self):
        if self.device:
            return
        import usb.core
        import usb.util

        device = usb.core.find(idVendor=self.VID, idProduct=self.PID)
        if device is None:
            raise PortalError("No supported Portal of Power found")

        try:
            if device.is_kernel_driver_active(0):
                device.detach_kernel_driver(0)
                self._detached_kernel_driver = True
            usb.util.claim_interface(device, 0)
            self.device = device
            self._usb = True
            self._usb_core = usb.core
            self._usb_util = usb.util
            self.ready()
            self.activate()
            log.info("Portal connected")
        except Exception:
            self.close()
            raise

    def close(self):
        device = self.device
        self.device = None
        if not device:
            return
        if self._usb:
            try:
                self._usb_util.release_interface(device, 0)
            except Exception:
                pass
            if self._detached_kernel_driver:
                try:
                    device.attach_kernel_driver(0)
                except Exception:
                    pass
        else:
            device.close()
        self._usb = False
        self._detached_kernel_driver = False

    @staticmethod
    def _report(command: str, *values: int) -> list[int]:
        report = [0] * 33
        report[1] = ord(command)
        report[2:2 + len(values)] = values
        return report

    def _write(self, command: str, *values: int):
        if not self.device:
            raise PortalError("Portal is disconnected")
        if self._usb:
            # These portals accept HID output reports via SET_REPORT on the
            # control endpoint. Linux interrupt/hidraw writes are stalled by
            # some 1430:0150 variants, including the Swap Force portal.
            report = bytes([ord(command), *values]).ljust(32, b"\0")
            written = self.device.ctrl_transfer(0x21, 0x09, 0x0200, 0, report)
            if written != len(report):
                raise PortalError(f"Short portal write: {written}/{len(report)} bytes")
        else:
            self.device.write(self._report(command, *values))

    def _read_for(self, command: str, timeout_ms: int = 1000) -> bytes:
        deadline = time.monotonic() + timeout_ms / 1000
        expected = ord(command)
        while time.monotonic() < deadline:
            if self._usb:
                try:
                    data = bytes(self.device.read(0x81, 32, timeout=100))
                except self._usb_core.USBTimeoutError:
                    continue
            else:
                data = bytes(self.device.read(32, 100))
            if data and data[0] == expected:
                return data
        raise PortalError(f"Portal did not answer {command!r}")

    def ready(self):
        self._write("R")
        return self._read_for("R")

    def activate(self):
        self._write("A", 1)
        return self._read_for("A")

    def status(self) -> list[int]:
        # Each of four slots occupies two status bits: present, then changed.
        for _ in range(4):
            self._write("S")
            data = self._read_for("S")
            flags = data[1]
            if not any(flags & (1 << bit) for bit in (1, 3, 5, 7)):
                return [slot for slot in range(4) if flags & (1 << (slot * 2))]
            time.sleep(0.05)
        return []

    def query(self, slot: int, block: int) -> bytes:
        for _ in range(3):
            # Portal query indexes are 0x10..0x13. Responses use 0x20..0x23,
            # so compare only the low nibble when matching a slot.
            self._write("Q", 0x10 + slot, block)
            data = self._read_for("Q")
            if len(data) >= 19 and data[1] != 0x01 and data[1] % 0x10 == slot and data[2] == block:
                return data[3:19]
        raise PortalError("Invalid query response")

    def read_identity(self, slot: int) -> tuple[int, int]:
        block = self.query(slot, 1)
        return struct.unpack_from("<HH", block, 0)

    def set_color(self, hex_color: str):
        color = hex_color.lstrip("#")
        self._write("C", *(int(color[i:i + 2], 16) for i in (0, 2, 4)))
