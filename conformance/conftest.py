"""Conformance harness fixtures.

Provides an `emu` fixture (an EmuControl client). Two modes:

- Attach: point RRDC_PORT at an already-running emulator's control port.
- Launch: set RRDC_EMU_CMD to a shell command that starts one (the literal
  {port} is substituted). The suite spawns it, waits for /status, and tears it
  down afterward.

If nothing is listening and no RRDC_EMU_CMD is set, the tests SKIP (so a bare
`pytest` in CI without an emulator is a skip, not a failure).
"""
import os
import signal
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "client"))

from emu_control import EmuControl  # noqa: E402


def _kill(proc):
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(os.getpgid(proc.pid), sig)
            proc.wait(timeout=5)
            return
        except Exception:
            continue


@pytest.fixture(scope="session")
def emu():
    port = int(os.environ.get("RRDC_PORT", "8080"))
    cmd = os.environ.get("RRDC_EMU_CMD")
    proc = None
    if cmd:
        proc = subprocess.Popen(
            cmd.replace("{port}", str(port)), shell=True, start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

    client = EmuControl(port)
    try:
        timeout = float(os.environ.get("RRDC_BOOT_TIMEOUT", "20"))
        client.wait_ready(tries=max(1, int(timeout / 0.1)), delay=0.1)
    except Exception as ex:
        if proc is not None:
            _kill(proc)
        pytest.skip(f"no emulator on control port {port}: {ex} "
                    f"(set RRDC_EMU_CMD to launch one, or RRDC_PORT to attach)")

    yield client

    if proc is not None:
        _kill(proc)
