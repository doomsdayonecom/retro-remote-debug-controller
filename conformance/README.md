# Conformance suite

pytest tests (15 of them) that assert an emulator correctly implements the
control contract (`../SPEC.md`, 0.3.x). Point them at any emulator — the
reference x16emu, FAB, the Neo6502, the PC-FX (Mednafen) fork — and they check
the same surface. Tests gated above the emulator's advertised contract skip
automatically, so a 0.1-only backend still passes. Platform-agnostic:
framebuffer dimensions come from the PPM header, addresses use `$0000`, and
`bank` is exercised without requiring the platform to have banking.

## Run

Attach to an already-running emulator:

```
RRDC_PORT=8080 pytest -v
```

Or let the suite launch one (`{port}` is substituted into the command):

```
RRDC_EMU_CMD="SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy \
    /path/to/x16emu -rom rom.bin -warp -controlport {port}" \
RRDC_PORT=8391 pytest -v
```

If nothing is listening and no `RRDC_EMU_CMD` is set, the tests **skip** (a bare
`pytest` in CI without an emulator is a skip, not a failure).

## What it checks

- `/status` — required keys present, contract MAJOR matches, sane types.
- `/regs` — a non-empty JSON object of integer registers.
- `/mem` — returns exactly `len` bytes; honours `bank`.
- `/screenshot` — a well-formed PPM whose body size matches its dimensions.
- `/step` — deterministic: equal steps advance the frame counter by equal,
  positive amounts, and `/step` returns the halted counter.
- `/pause` + `/resume` — toggle the paused state.
- `/key` *(0.2)* — accepts `text=`/`code=` with optional `down=`, rejects a
  request with neither; is POST-only.
- `/reset` *(0.2)* — resets and returns `{"reset":true}`.
- `POST /mem` *(0.3)* — write→read round-trips; is POST-only.
- `/audio` *(0.3)* — returns a well-formed PCM WAV.
- Errors — unknown path → 404; `GET /step` / `GET /key` → 405.

## Environment

| Var | Default | Meaning |
|---|---|---|
| `RRDC_PORT` | `8080` | control port to attach to / launch on |
| `RRDC_EMU_CMD` | — | shell command to launch an emulator (`{port}` substituted) |
| `RRDC_BOOT_TIMEOUT` | `20` | seconds to wait for `/status` |

Requires `pytest`. Nothing else — the client is stdlib-only (Pillow is optional
and unused here).
