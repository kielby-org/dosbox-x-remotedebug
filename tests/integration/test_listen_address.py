#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pytest>=8.0",
# ]
# ///
"""Which interfaces the GDB and QMP servers listen on.

Neither server authenticates, so by default both bind loopback only.
`gdbserver address` and `qmpserver address` widen that on request.

Run: uv run tests/integration/test_listen_address.py
"""

import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from launcher import Emulator, port_is_listening


def non_loopback_address():
    """This host's address on its default route, or None.

    Connecting a UDP socket sends nothing; it only makes the kernel pick
    the source address it would use.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("192.0.2.1", 9))
        except OSError:
            return None
        address = s.getsockname()[0]
    return None if address.startswith("127.") else address


@pytest.fixture
def external_address():
    address = non_loopback_address()
    if address is None:
        pytest.skip("host has no non-loopback IPv4 address")
    return address


def test_both_servers_listen_on_loopback_by_default(emulator):
    assert port_is_listening(emulator.gdb_port, "127.0.0.1")
    assert port_is_listening(emulator.qmp_port, "127.0.0.1")


def test_both_servers_refuse_a_non_loopback_address_by_default(
        emulator, external_address):
    assert not port_is_listening(emulator.gdb_port, external_address)
    assert not port_is_listening(emulator.qmp_port, external_address)


def test_configured_addresses_widen_the_listeners(external_address):
    extra = ("[dosbox]\n"
             "gdbserver address = 0.0.0.0\n"
             "qmpserver address = 0.0.0.0\n")
    with Emulator(extra_conf=extra) as emu:
        assert port_is_listening(emu.gdb_port, external_address)
        assert port_is_listening(emu.qmp_port, external_address)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
