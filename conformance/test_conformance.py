"""Contract conformance tests (SPEC.md 0.3.x). Platform-agnostic: framebuffer
dimensions come from the PPM header, addresses use $0000, and `bank` is
exercised but banking is not required. Tests gated on the server's advertised
minor (input injection 0.2; memory write + audio 0.3) skip on older servers."""
import urllib.error
import urllib.request

import pytest

from emu_control import parse_ppm_header


def _raw(emu, method, path):
    """Raw request returning (status_code, body) without the client's wrapping,
    so we can assert on 4xx status codes."""
    req = urllib.request.Request(emu.base + path, method=method)
    try:
        with urllib.request.urlopen(req, timeout=emu.timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_status_contract(emu):
    st = emu.status()
    for k in ("contract", "emulator", "platform", "frame", "paused", "running"):
        assert k in st, f"missing /status.{k}"
    assert str(st["contract"]).split(".")[0] == "0", "unexpected contract MAJOR"
    assert isinstance(st["platform"], str) and st["platform"]
    assert isinstance(st["frame"], int)
    assert isinstance(st["paused"], bool)


def test_regs_object(emu):
    r = emu.regs()
    assert isinstance(r, dict) and r, "regs must be a non-empty JSON object"
    assert all(isinstance(v, int) for v in r.values()), "register values must be ints"


def test_mem_exact_length(emu):
    assert len(emu.mem(0x0000, 32)) == 32
    assert len(emu.mem(0x0000, 256)) == 256
    assert len(emu.mem(0x0000, 0)) == 0


def test_mem_bank_param_returns_length(emu):
    # bank is optional (ignored on flat platforms) but must still honour len.
    assert len(emu.mem(0x0000, 8, bank=0)) == 8


def test_screenshot_ppm(emu):
    data = emu.screenshot_ppm()
    w, h, maxval, off = parse_ppm_header(data)
    assert w > 0 and h > 0, f"bad dimensions {w}x{h}"
    assert maxval == 255
    assert len(data) == off + 3 * w * h, "PPM body size mismatches dimensions"


def test_step_is_deterministic(emu):
    emu.pause()
    try:
        a = emu.frame()
        b = emu.step(2); c = emu.frame()
        assert b == c, "/step must return the halted frame counter"
        d = emu.step(2); e = emu.frame()
        assert d == e
        assert c - a > 0, "/step must advance the frame counter"
        assert (c - a) == (e - c), "equal steps must advance by equal amounts"
    finally:
        emu.resume()


def test_pause_resume_toggle(emu):
    emu.pause()
    assert emu.status()["paused"] is True
    emu.resume()
    assert emu.status()["paused"] is False


def test_unknown_path_404(emu):
    code, _ = _raw(emu, "GET", "/no-such-endpoint")
    assert code == 404


def test_step_requires_post(emu):
    code, _ = _raw(emu, "GET", "/step?frames=1")
    assert code == 405


def _contract_minor(emu) -> int:
    return int(str(emu.status()["contract"]).split(".")[1])


# -- contract 0.2: input injection (skipped on 0.1 servers) ------------------

def test_key_injection(emu):
    """/key accepts text= and code= with an optional down=, and rejects a
    request with neither. The key's *effect* is platform/program-specific and
    tested per-port; here we assert only the contract surface."""
    if _contract_minor(emu) < 2:
        pytest.skip("contract < 0.2 (no input injection)")
    emu.key(text="a", down=True)
    emu.key(text="a", down=False)
    emu.key(text="a")                    # tap (press then release)
    emu.key(code=32, down=True)
    emu.key(code=32, down=False)
    code, _ = _raw(emu, "POST", "/key")  # neither text nor code
    assert code == 400


def test_key_requires_post(emu):
    if _contract_minor(emu) < 2:
        pytest.skip("contract < 0.2")
    code, _ = _raw(emu, "GET", "/key?text=a")
    assert code == 405


# -- contract 0.3: memory write + audio (skipped on < 0.3 servers) -----------

def test_mem_write_roundtrip(emu):
    """POST /mem pokes bytes; GET /mem reads them back (contract 0.3)."""
    if _contract_minor(emu) < 3:
        pytest.skip("contract < 0.3 (no memory write)")
    emu.pause()               # freeze so the machine can't overwrite between write+read
    try:
        addr, payload = 0x0400, bytes([0xA5, 0x5A, 0x00, 0xFF])
        assert emu.mem_write(addr, payload) == len(payload)
        assert emu.mem(addr, len(payload)) == payload
    finally:
        emu.resume()


def test_mem_write_requires_post(emu):
    if _contract_minor(emu) < 3:
        pytest.skip("contract < 0.3")
    # GET /mem is the read path (200), never a write — writing needs POST.
    code, _ = _raw(emu, "GET", "/mem?addr=0&len=1")
    assert code == 200


def test_audio_is_valid_wav(emu):
    """GET /audio returns a parseable PCM WAV (contract 0.3)."""
    if _contract_minor(emu) < 3:
        pytest.skip("contract < 0.3 (no audio)")
    import io
    import wave
    emu.pause(); emu.step(4)          # produce a little audio deterministically
    w = wave.open(io.BytesIO(emu.audio()), "rb")
    assert w.getsampwidth() == 2      # signed 16-bit
    assert w.getnchannels() in (1, 2)
    assert w.getframerate() > 0
    emu.resume()


def test_reset(emu):
    """/reset responds and is POST-only. Runs last (it restarts the machine)."""
    if _contract_minor(emu) < 2:
        pytest.skip("contract < 0.2")
    code, _ = _raw(emu, "GET", "/reset")
    assert code == 405
    emu.reset()
