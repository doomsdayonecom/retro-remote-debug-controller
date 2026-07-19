"""emu_control.py — shared client for the Retro Remote Debug Controller.

One client for every port's pytest suite. Speaks the HTTP contract in
../SPEC.md (0.1.x). Depends only on the stdlib; Pillow is optional and only
needed for .screenshot().

    from emu_control import EmuControl

    emu = EmuControl(port=8080)      # emulator started with -controlport 8080
    emu.wait_ready()
    emu.step(frames=120)
    assert emu.regs()["a"] == 0
    data = emu.mem(0x0400, 256, bank=1)
    img = emu.screenshot()           # PIL.Image (requires Pillow)
"""

from __future__ import annotations

import io
import json
import time
import urllib.error
import urllib.request

CONTRACT_MAJOR = 0


class EmuControlError(RuntimeError):
    pass


def parse_ppm_header(data: bytes):
    """Parse a binary PPM (P6) header. Returns (width, height, maxval, offset)
    where offset is the index of the first pixel byte. Raises on malformed
    input. Stdlib-only — no Pillow needed."""
    if data[:2] != b"P6":
        raise EmuControlError(f"not a P6 PPM (magic {data[:2]!r})")
    fields, i, n = [], 2, len(data)
    while len(fields) < 3 and i < n:
        while i < n and data[i:i + 1].isspace():
            i += 1
        if i < n and data[i:i + 1] == b"#":            # comment to end of line
            while i < n and data[i:i + 1] not in (b"\n", b"\r"):
                i += 1
            continue
        start = i
        while i < n and not data[i:i + 1].isspace():
            i += 1
        fields.append(int(data[start:i]))
    if len(fields) < 3:
        raise EmuControlError("truncated PPM header")
    return fields[0], fields[1], fields[2], i + 1        # +1: single whitespace


class EmuControl:
    def __init__(self, port: int, host: str = "127.0.0.1", timeout: float = 5.0):
        self.base = f"http://{host}:{port}"
        self.timeout = timeout

    # -- transport ---------------------------------------------------------
    def _get(self, path: str) -> tuple[bytes, str]:
        try:
            with urllib.request.urlopen(self.base + path, timeout=self.timeout) as r:
                return r.read(), r.headers.get_content_type()
        except urllib.error.HTTPError as e:
            raise EmuControlError(f"GET {path} -> {e.code}: {e.read()!r}") from e

    def _post(self, path: str) -> bytes:
        req = urllib.request.Request(self.base + path, method="POST", data=b"")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            raise EmuControlError(f"POST {path} -> {e.code}: {e.read()!r}") from e

    # -- endpoints ---------------------------------------------------------
    def status(self) -> dict:
        body, _ = self._get("/status")
        st = json.loads(body)
        major = int(str(st.get("contract", "0")).split(".")[0])
        if major != CONTRACT_MAJOR:
            raise EmuControlError(
                f"contract major mismatch: emulator {st.get('contract')} "
                f"vs client {CONTRACT_MAJOR}.x"
            )
        return st

    def frame(self) -> int:
        return int(self.status()["frame"])

    def regs(self) -> dict:
        body, _ = self._get("/regs")
        return json.loads(body)

    def mem(self, addr: int, length: int, bank: int | None = None) -> bytes:
        path = f"/mem?addr={addr}&len={length}"
        if bank is not None:
            path += f"&bank={bank}"
        body, _ = self._get(path)
        return body

    def step(self, frames: int = 1) -> int:
        body = self._post(f"/step?frames={frames}")
        return int(json.loads(body)["frame"])

    def pause(self) -> None:
        self._post("/pause")

    def resume(self) -> None:
        self._post("/resume")

    def screenshot_ppm(self) -> bytes:
        """Return the live screen as raw PPM (P6) bytes. Stdlib-only."""
        body, _ = self._get("/screenshot")
        return body

    def screenshot(self):
        """Return the live screen as a PIL.Image (requires Pillow)."""
        body = self.screenshot_ppm()
        try:
            from PIL import Image
        except ImportError as e:  # pragma: no cover
            raise EmuControlError("screenshot() needs Pillow (pip install pillow)") from e
        return Image.open(io.BytesIO(body))

    # -- helpers -----------------------------------------------------------
    def wait_ready(self, tries: int = 100, delay: float = 0.05) -> dict:
        """Poll /status until the server answers (emulator boot race)."""
        last = None
        for _ in range(tries):
            try:
                return self.status()
            except (EmuControlError, urllib.error.URLError, ConnectionError) as e:
                last = e
                time.sleep(delay)
        raise EmuControlError(f"emulator control port never came up: {last}")

    def run_to_frame(self, target: int) -> int:
        """Step until the frame counter reaches >= target."""
        cur = self.frame()
        if target > cur:
            self.step(frames=target - cur)
        return self.frame()
