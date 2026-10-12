#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pytest>=8.0",
# ]
# ///
"""The conf option names are `gdbserver port` and `qmpserver port`, with a
space (dosbox.cpp:1726 and :1732). The spaceless spellings are not options
at all: they are ignored, the server falls back to 2159/4444, and a client
that thinks it asked for its own port connects to another emulator."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from launcher import Emulator, port_is_listening


def test_the_requested_ports_are_the_ports_that_listen(emulator):
    assert port_is_listening(emulator.gdb_port)
    assert port_is_listening(emulator.qmp_port)


def test_the_stock_ports_are_not_bound_by_our_emulator(emulator):
    """If the conf were ignored the emulator would be on 2159/4444. This
    can only false-pass when a foreign emulator holds those ports, so it
    asserts our own ports are elsewhere too."""
    assert emulator.gdb_port != 2159
    assert emulator.qmp_port != 4444
    gdb = emulator.gdb()
    assert "PacketSize=" in gdb.supported()


def test_the_spaceless_option_names_are_silently_ignored(tmp_path):
    """Documents the trap. `gdbport` is accepted by the parser and does
    nothing, so an emulator configured with it lands on the default port."""
    if port_is_listening(2159):
        pytest.skip("2159 already in use")
    emu = Emulator()
    emu._allocate_ports()
    requested = emu.gdb_port
    emu.workdir = tmp_path
    conf = tmp_path / "bad.conf"
    conf.write_text(
        # Software output, as the launcher's own conf uses: asked for its
        # default, the emulator first tries to create an OpenGL context, which
        # is slow to fail on a CI runner with no GPU.
        "[sdl]\n"
        "output = surface\n"
        "[dosbox]\n"
        "quit warning = false\n"
        "gdbserver = true\n"
        f"gdbport = {requested}\n"
        "qmpserver = true\n"
        f"qmpport = {emu.qmp_port}\n"
        "[log]\n"
        f"logfile = {tmp_path / 'server.log'}\n"
    )
    emu.conf_path = conf
    try:
        emu._spawn()
        # The emulator comes up on 2159/4444, not on what was requested.
        import time
        # Probe until it answers, and keep that answer. The GDB server takes
        # one client and only accepts once the emulator's main loop is running,
        # so a second probe straight after the first can find the backlog full
        # and time out, which says nothing about whether it is listening.
        deadline = time.time() + Emulator.START_TIMEOUT
        listening = False
        while time.time() < deadline and not listening:
            listening = port_is_listening(2159)
            if not listening:
                time.sleep(0.1)
        log = tmp_path / "server.log"
        assert listening, (
            "expected the ignored option to leave the server on its default "
            "port; if this fails the option names may have been fixed\n"
            "emulator log:\n" + (log.read_text(errors="replace")
                                 if log.exists() else "<none>"))
        assert not port_is_listening(requested)
    finally:
        emu.stop()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
