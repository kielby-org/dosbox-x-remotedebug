#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pytest>=8.0",
# ]
# ///
"""What the servers do when the port they were asked to use is already taken.

Two debug sessions on one machine will sooner or later ask for the same port.
The emulator must stay up, the other server must keep working, and the failure
must be reported once: the QMP server used to start a thread that then called
accept() on a socket that never existed, logging "accept failed" in a tight
loop, and the GDB server reported itself running without listening.

Run: uv run tests/integration/test_port_in_use.py
"""

import socket
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from launcher import Emulator, free_port

LOG_CONF = "[log]\nlogfile = server.log\n"
LOG_WAIT_SECONDS = 15.0
SETTLE_SECONDS = 1.5


@contextmanager
def port_held():
    """A listener on a loopback port, standing in for the other session.

    It never accepts, so the backlog has to be deep enough to absorb the
    launcher's readiness probes; with a backlog of one, the probes fill it and
    Windows then refuses further connections to the port."""
    with socket.socket() as holder:
        holder.bind(("127.0.0.1", 0))
        holder.listen(128)
        yield holder.getsockname()[1]


class EmulatorWithoutBootProbe(Emulator):
    """The launcher decides the emulator is ready by reading guest memory over
    GDB. A test that takes the GDB port away cannot use that probe."""

    def _wait_for_boot(self) -> None:
        pass


def read_log(emulator) -> str:
    log = emulator.workdir / "server.log"
    return log.read_text(errors="replace") if log.exists() else ""


def wait_for_log(emulator, text: str) -> str:
    deadline = time.time() + LOG_WAIT_SECONDS
    while time.time() < deadline:
        log = read_log(emulator)
        if text in log:
            return log
        time.sleep(0.1)
    pytest.fail(f"{text!r} never appeared in the emulator's log:\n"
                f"{read_log(emulator)}")


def test_a_taken_qmp_port_leaves_the_gdb_server_working():
    with port_held() as qmp_port:
        with Emulator(qmp_port=qmp_port, extra_conf=LOG_CONF) as emu:
            wait_for_log(emu, "QMP: cannot listen on")
            assert emu.gdb().supported()


def test_a_taken_qmp_port_is_reported_once_not_in_a_loop():
    with port_held() as qmp_port:
        with Emulator(qmp_port=qmp_port, extra_conf=LOG_CONF) as emu:
            wait_for_log(emu, "QMP: cannot listen on")
            time.sleep(SETTLE_SECONDS)
            log = read_log(emu)
            assert log.count("QMP: cannot listen on") == 1
            assert "accept failed" not in log


def test_a_taken_gdb_port_leaves_the_qmp_server_working():
    with port_held() as gdb_port:
        with EmulatorWithoutBootProbe(gdb_port=gdb_port,
                                      extra_conf=LOG_CONF) as emu:
            wait_for_log(emu, "GDBServer: cannot listen on")
            assert emu.qmp().execute("query-status") is not None


def test_a_free_port_still_listens(emulator):
    """The control: the same setup on free ports reports no failure."""
    assert emulator.gdb().supported()
    assert emulator.qmp().execute("query-status") is not None
