# Changelog

Contract versions of the Retro Remote Debug Controller (see [SPEC.md](SPEC.md)).
Semantic versioning: MAJOR = breaking change to an existing endpoint, MINOR =
additive (new endpoint / optional field), PATCH = clarification. Every minor so
far has been purely additive — older clients keep working, and a server
advertises the highest level whose backend callbacks are all present via
`/status.contract`.

## 0.4.0
- `POST /pointer?x=&y=[&buttons=]` (absolute) or `?dx=&dy=[&buttons=]` (relative)
  — inject a pointer move/click through the platform's native mouse path.
  `buttons` is a bitmask (bit0=primary, bit1=secondary); omit for a pure move.
  Backend callback: `set_pointer`.
- `GET /pointer` — read back the current pointer `{x, y, buttons}`, so a test can
  tell "input never arrived" from "wrong output drawn". Backend callback:
  `get_pointer`.
- First consumer: the Neo6502 fork (drives the firmware mouse), unblocking the
  pointer floor of the `rstar-api` RWM/RGM toolkit.

## 0.3.0
- `POST /mem?addr=&bank=` — write (poke) memory; bytes in the request body,
  returns `{"written":n}`. Backend callback: `write_mem`.
- `GET /audio` — drain synthesised PCM since the last call as a self-describing
  WAV (the audio analogue of `/screenshot`); `X-Rrdc-Audio-Dropped` header on
  ring overflow. Backend callback: `capture_audio`.
- The NEC PC-FX (Mednafen) fork joins as the fourth conforming emulator, the
  second to vendor the C core as a git submodule.

## 0.2.0
- `POST /key?text=|code=[&down=]` — inject input (press / release / tap).
  Backend callback: `inject_key`.
- `POST /reset` — soft/cold reset. Backend callback: `reset`.
- Contract gating introduced: a NULL callback returns 501 for its endpoint and
  lowers the advertised contract, keeping partial backends honest.

## 0.1.0
- Initial contract: `GET /status`, `GET /screenshot` (PPM), `GET /mem`,
  `GET /regs`, `POST /step`, `POST /pause` / `POST /resume`.
- Shared C core (`core/retro_control.{c,h}`) — sockets, HTTP, PPM/JSON encoding,
  and cooperative pause/step, driven by three loop hooks. Backend callbacks:
  `read_mem`, `get_regs_json`, `get_framebuffer`, `get_frame_count`.
- Shared pytest client (`client/emu_control.py`) and the platform-agnostic
  conformance suite. Reference implementation: the Commander X16 fork.
