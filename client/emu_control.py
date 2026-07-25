"""emu_control.py — shared client for the Retro Remote Debug Controller.

One client for every port's pytest suite. Speaks the HTTP contract in
../SPEC.md (0.4.x). Depends only on the stdlib; Pillow is optional and only
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
import urllib.parse
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

    def _post(self, path: str, body: bytes = b"") -> bytes:
        req = urllib.request.Request(self.base + path, method="POST", data=body)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            raise EmuControlError(f"POST {path} -> {e.code}: {e.read()!r}") from e

    # -- endpoints ---------------------------------------------------------
    def status(self) -> dict:
        """GET /status — liveness + contract dict; raises on a MAJOR mismatch."""
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
        """Current completed-frame counter (the determinism anchor)."""
        return int(self.status()["frame"])

    def regs(self) -> dict:
        """GET /regs — CPU registers as a dict (keys are platform-specific)."""
        body, _ = self._get("/regs")
        return json.loads(body)

    def mem(self, addr: int, length: int, bank: int | None = None) -> bytes:
        """GET /mem — read `length` bytes at `addr` (optional `bank`)."""
        path = f"/mem?addr={addr}&len={length}"
        if bank is not None:
            path += f"&bank={bank}"
        body, _ = self._get(path)
        return body

    def step(self, frames: int = 1) -> int:
        """POST /step — advance `frames` complete frames, halt; returns the new
        frame counter. Meaningful once paused."""
        body = self._post(f"/step?frames={frames}")
        return int(json.loads(body)["frame"])

    def pause(self) -> None:
        """POST /pause — halt the machine (advances only via step())."""
        self._post("/pause")

    def resume(self) -> None:
        """POST /resume — return the machine to free-running."""
        self._post("/resume")

    def key(self, text: str | None = None, code: int | None = None,
            down: bool | None = None) -> None:
        """Inject a key (contract 0.2). Provide `text` (a single character) or
        `code` (a raw platform key code). down=True presses/holds, False
        releases, None taps (press then release). Hold across step() frames for
        a program that samples input each frame."""
        parts = []
        if text is not None:
            # Percent-encode so a '+' isn't decoded to a space and '&'/'#'/'%'
            # don't truncate or corrupt the value. safe="" encodes '+' too.
            parts.append(f"text={urllib.parse.quote(text, safe='')}")
        if code is not None:
            parts.append(f"code={code}")
        if down is not None:
            parts.append(f"down={1 if down else 0}")
        if not parts:
            raise EmuControlError("key() needs text= or code=")
        self._post("/key?" + "&".join(parts))

    def reset(self) -> None:
        """Soft/cold reset the machine (contract 0.2)."""
        self._post("/reset")

    def mem_write(self, addr: int, data: bytes, bank: int | None = None) -> int:
        """Write/poke bytes at addr (contract 0.3). Returns the number written."""
        path = f"/mem?addr={addr}"
        if bank is not None:
            path += f"&bank={bank}"
        return int(json.loads(self._post(path, bytes(data)))["written"])

    def audio(self) -> bytes:
        """Raw WAV (PCM) of audio synthesized since the last call (contract 0.3).
        Drain regularly (e.g. after each step) so the ring doesn't overflow."""
        body, _ = self._get("/audio")
        return body

    def pointer(self, x: int | None = None, y: int | None = None,
                dx: int | None = None, dy: int | None = None,
                buttons: int | None = None) -> None:
        """Inject a pointer move/click (contract 0.4). Give absolute (x, y) or
        relative (dx, dy). `buttons` is a bitmask (bit0=primary, bit1=secondary);
        omit it for a pure move (leaves the button state unchanged). Hold buttons
        across step() frames for a program that samples the pointer each frame."""
        parts = []
        if x is not None and y is not None:
            parts.append(f"x={x}")
            parts.append(f"y={y}")
        elif dx is not None or dy is not None:
            parts.append(f"dx={dx if dx is not None else 0}")
            parts.append(f"dy={dy if dy is not None else 0}")
        else:
            raise EmuControlError("pointer() needs x= and y=, or dx=/dy=")
        if buttons is not None:
            parts.append(f"buttons={buttons}")
        self._post("/pointer?" + "&".join(parts))

    def pointer_get(self) -> dict:
        """GET /pointer — the current pointer as {x, y, buttons} (contract 0.4).
        `buttons` uses the same bitmask as pointer()."""
        body, _ = self._get("/pointer")
        return json.loads(body)

    # Canonical pad bitmask (SPEC "Canonical button layout"). The SNES /
    # Neo6502 native order, fixed across platforms so a test written on one
    # machine reads the same on another.
    PAD_LEFT   = 0x0001
    PAD_RIGHT  = 0x0002
    PAD_UP     = 0x0004
    PAD_DOWN   = 0x0008
    PAD_A      = 0x0010
    PAD_B      = 0x0020
    PAD_X      = 0x0040
    PAD_Y      = 0x0080
    PAD_START  = 0x0100
    PAD_SELECT = 0x0200
    PAD_L      = 0x0400
    PAD_R      = 0x0800

    def pad(self, buttons: int | None = None, index: int = 0,
            connected: bool | None = None) -> None:
        """Present a virtual controller and set what is held (contract 0.5).

        `buttons` is a mask of PAD_* — omit to leave the held state alone.
        `connected=False` unplugs the pad, which is testable behaviour in its
        own right: a program that asks whether a controller is present before
        offering two-player needs both answers.

        Unlike key(), a pad is a LEVEL: the state persists across step()
        frames until changed, so a press does not need re-asserting. Release
        with pad(0)."""
        parts = [f"index={index}"]
        if buttons is not None:
            parts.append(f"buttons={buttons}")
        if connected is not None:
            parts.append(f"connected={1 if connected else 0}")
        self._post("/pad?" + "&".join(parts))

    def pad_get(self, index: int = 0) -> dict:
        """GET /pad — {index, connected, buttons} (contract 0.5). Distinguishes
        'the input never arrived' from 'it arrived and was ignored'."""
        body, _ = self._get(f"/pad?index={index}")
        return json.loads(body)

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
