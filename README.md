# retro-remote-debug-controller

A tiny, portable **HTTP control API for retro-platform emulators**, and the
shared tooling that speaks it. One contract → one test harness across every
Doomsday One port.

An emulator launched with a control-port flag exposes a localhost HTTP server:

| Endpoint | Returns | Since |
|---|---|---|
| `GET /status` | contract version, platform, frame counter, paused/running | 0.1 |
| `GET /screenshot` | PPM image of the live screen | 0.1 |
| `GET /mem?addr=&len=&bank=` | raw memory bytes | 0.1 |
| `GET /regs` | CPU registers (JSON) | 0.1 |
| `POST /step?frames=` | advance N frames deterministically | 0.1 |
| `POST /pause` / `POST /resume` | halt / resume the machine | 0.1 |
| `POST /key`, `POST /reset` | inject input / reset | 0.2 |
| `POST /mem?addr=&bank=` | write (poke) memory | 0.3 |
| `GET /audio` | drain synthesised PCM as a WAV | 0.3 |

Current contract: **0.3.0**. Minors are purely additive (a missing capability
returns 501 and lowers the advertised contract), so a client reads
`/status.contract` and fails fast only on a MAJOR mismatch. See [SPEC.md](SPEC.md).

## Why

Every one of these ports (Pac-Man on X16, Neo6502, Agon, and NEC PC-FX; and
whatever's next) is chasing **frame-exact** arcade fidelity, and every one had
its own fragile, platform-specific way to check state headless (write to the SD
card, dump 64 KB of RAM on a magic jump, grep stdout — which lies). This
replaces all of that with one contract:

- **`GET /mem`** → assert game state (sprite table, actor positions);
  **`POST /mem`** pokes it back for setup.
- **`GET /screenshot`** → Pillow → assert pixels, or just catch "nothing
  rendered" (the exact class of bug that costs an afternoon otherwise).
- **`POST /step`** → deterministic, frame-addressable capture, so CI diffs don't
  flake against a free-running 60 Hz loop.
- **`POST /key`** → drive input; **`GET /audio`** → assert the sound a stepped
  window produced.

The payoff is uniformity: the same `emu_control.py` and the same pytest patterns
drive the X16, Neo6502, Agon, and PC-FX emulators.

## Layout

```
SPEC.md                 the normative HTTP contract (start here)
core/retro_control.h    portable backend vtable each emulator implements
core/retro_control.c    shared server: sockets, HTTP, PPM/JSON, marshalling
client/emu_control.py   shared pytest client (stdlib; Pillow optional)
conformance/            a platform-agnostic pytest that proves an emulator conforms
CHANGELOG.md            the additive contract history
```

## Adopting it in an emulator

Two first-class paths (both normative in [SPEC.md](SPEC.md#adoption-paths)):

- **Vendor the shared core** — for C/C++ emulators. Add this repo as a git
  submodule, compile `core/retro_control.c`, implement the backend callbacks,
  and wire three loop hooks. The socket loop, HTTP parsing, PPM/JSON encoding
  and pause/step control come for free.
- **Conform only** — for emulators in other languages (the FAB Agon emulator is
  Rust). Keep your own HTTP server; just match the contract and pass the
  conformance suite. Sharing the C core is an optimization, not a requirement.

The vendor path is one backend struct plus three hooks:

```c
#include "retro_control.h"

/* Four callbacks satisfy 0.1; add inject_key/reset for 0.2 and
   write_mem/capture_audio for 0.3. A NULL callback 501s its endpoint. */
static const retro_control_backend_t backend = {
    .platform        = "x16",
    .emulator        = "x16emu",
    .read_mem        = x16_read_mem,         /* debug-read, no side effects */
    .get_regs_json   = x16_get_regs_json,
    .get_framebuffer = x16_get_framebuffer,
    .get_frame_count = x16_get_frame_count,
    .inject_key      = x16_inject_key,       /* 0.2 */
    .reset           = x16_reset,            /* 0.2 */
    .write_mem       = x16_write_mem,        /* 0.3 */
    .capture_audio   = x16_capture_audio,    /* 0.3 */
};

if (control_port)                 /* set by -controlport / --control-port / env */
    retro_control_start(control_port, &backend);
```

Stepping and pausing are driven cooperatively from the emulator's main loop, not
by a callback — three hooks at a frame boundary:

```c
retro_control_service();                 /* run a pending request on the emu thread */
if (!retro_control_running()) { idle; }  /* gate advancing the machine (pause/step) */
... run one frame ...
if (frame_completed) retro_control_on_frame();   /* tick the /step budget */
```

## Status

Contract **0.3.0**, implemented across **four** emulators. The shared server and
the conformance suite (15 tests, green against the reference) are complete.
Reference implementation: the Commander X16 fork (`x16-emulator`), which vendors
`core/` as a git submodule; the NEC PC-FX fork (Mednafen) does the same, and the
FAB Agon emulator conforms directly in Rust.
