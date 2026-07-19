# retro-remote-debug-controller

A tiny, portable **HTTP control API for retro-platform emulators**, and the
shared tooling that speaks it. One contract → one test harness across every
Doomsday One port.

An emulator launched with a control-port flag exposes a localhost HTTP server:

| Endpoint | Returns |
|---|---|
| `GET /status` | contract version, platform, frame counter, paused state |
| `GET /screenshot` | PPM image of the live screen |
| `GET /mem?addr=&len=&bank=` | raw memory bytes |
| `GET /regs` | CPU registers (JSON) |
| `POST /step?frames=` | advance N frames deterministically |
| `POST /key`, `/reset` | *(0.2)* inject input |

## Why

Every one of these ports (Pac-Man on X16, Neo6502, Agon; and whatever's next) is
chasing **frame-exact** arcade fidelity, and every one had its own fragile,
platform-specific way to check state headless (write to the SD card, dump 64 KB
of RAM on a magic jump, grep stdout — which lies). This replaces all of that
with one contract:

- **`GET /mem`** → assert game state (sprite table, actor positions).
- **`GET /screenshot`** → Pillow → assert pixels, or just catch "nothing
  rendered" (the exact class of bug that costs an afternoon otherwise).
- **`POST /step`** → deterministic, frame-addressable capture, so CI diffs don't
  flake against a free-running 60 Hz loop.

The payoff is uniformity: the same `emu_control.py` and the same pytest patterns
drive the X16, Neo6502, and Agon emulators.

## Layout

```
SPEC.md                 the normative HTTP contract (start here)
core/retro_control.h    portable backend vtable each emulator implements
core/retro_control.c    shared server: sockets, HTTP, PPM/JSON, marshalling  [next]
client/emu_control.py   shared pytest client
conformance/            tests an emulator runs to prove it conforms          [next]
```

## Adopting it in an emulator (the shape)

Write the server once, adapt per fork. Each fork vendors `core/` and implements
~5 callbacks, then calls the server:

```c
#include "retro_control.h"

static retro_control_backend_t backend = {
    .platform       = "x16",
    .read_mem       = x16_read_mem,      /* debug-read, no side effects */
    .get_regs_json  = x16_get_regs_json,
    .get_framebuffer= x16_get_framebuffer,
    .step_frames    = x16_step_frames,
    .get_frame_count= x16_get_frame_count,
};

if (control_port)              /* set by -controlport / --control-port */
    retro_control_start(control_port, &backend);
```

The socket loop, HTTP parsing, PPM encoding, JSON framing, and the
enqueue-to-emulator-thread marshalling live in the shared core — not in three
different codebases.

## Status

Early. `SPEC.md` (0.1.0) and the interfaces below are the stable target the
forks build against; the server `.c` and conformance suite are landing next.
Reference implementation: the Commander X16 fork (`x16-emulator`).
