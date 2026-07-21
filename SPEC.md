# Retro Remote Debug Controller — HTTP Control Contract

**Contract version: 0.3.0** (semver; clients assert on the MAJOR). 0.3 adds
memory write (`POST /mem`) and an audio drain (`GET /audio`); 0.2 added input
injection (`POST /key`, `POST /reset`). Every minor is purely additive, so older
clients keep working and servers advertise the highest level whose callbacks are
all present via `/status.contract`.

A minimal, portable HTTP API that a retro-platform emulator exposes so an
external harness can screenshot the screen, read memory and registers, step the
machine deterministically, and inject input. The same contract is implemented
by the forked FAB Agon Emulator, the Neo6502 emulator, and the Commander X16
emulator, so **one** pytest harness drives all three ports.

## Principles

- **Opt-in.** The server is OFF by default and starts only when the emulator is
  launched with a control-port flag. Zero cost to normal use.
- **Localhost only.** The server MUST bind `127.0.0.1` (never `0.0.0.0`).
  `/mem` and input injection are a memory-read / remote-control surface; they do
  not leave the machine.
- **The contract is the HTTP surface, not the flag.** Each emulator names its
  launch flag idiomatically (x16emu: `-controlport N`; FAB: `--control-port N`).
  Only the endpoints below are normative.
- **Determinism is a first-class requirement.** These are frame-exact ports.
  Every state read (`/mem`, `/regs`, `/screenshot`) MUST observe a consistent
  machine state — captured at an instruction/frame boundary on the emulator
  thread, never a torn mid-instruction read from the HTTP thread. See
  *Consistency* below.

## Conventions

- JSON responses are `application/json; charset=utf-8`.
- Binary responses use the stated content-type; no chunked encoding required.
- Errors: HTTP 4xx/5xx with body `{"error":"<message>"}`.
- Numbers in JSON are decimal unless a field is documented as a hex string.
- Methods are exactly as listed (`GET`/`POST`). Unknown path → 404. Unknown
  method on a known path → 405.

## Endpoints

### `GET /status`
Liveness + contract negotiation. Always available.
```json
{
  "contract": "0.3.0",
  "emulator": "x16emu",
  "platform": "x16",
  "frame": 12345,
  "paused": true,
  "running": true
}
```
- `contract` — this document's version. Clients MUST reject a mismatched MAJOR.
- `platform` — one of `x16`, `neo6502`, `agon` (extensible). Tells the client
  the memory/register model (see *Per-platform* appendix).
- `frame` — monotonic completed-frame counter since boot. The determinism
  anchor: a screenshot taken at `frame == N` shows the state after N complete
  frames.
- `paused` — true if the machine is halted (only advances via `/step`).

### `GET /screenshot`
The live screen as a Portable Pixmap.
- Response: `image/x-portable-pixmap`, binary **PPM P6**, 8-bit RGB, no alpha.
- Pixels are the most recent COMPLETE frame (never a half-scanned frame). The
  emulator keeps a snapshot the render thread fills at frame end; the HTTP
  thread serves that snapshot.
- Dimensions are the platform's native framebuffer (appendix). Clients read
  `width`/`height` from the PPM header — do not hardcode.
- Reserved: `?frame=N` (block until frame N) — not required in 0.1.

### `GET /mem?addr=<a>&len=<n>[&bank=<b>]`
Raw memory bytes.
- `addr` — start address, decimal or `0x`-hex. Interpreted in the platform's
  address space (appendix).
- `len` — byte count, decimal. Servers MAY cap `len` (recommend ≥ 65536); a
  capped request returns what it can with `Content-Length` telling the truth.
- `bank` — OPTIONAL bank selector for banked platforms (X16). Omitted → the
  machine's currently-selected bank. Ignored by flat-memory platforms.
- Response: `application/octet-stream`, exactly the requested bytes.
- Reads go through the emulator's debug-read path (no side effects, no I/O
  triggers, no access-flag mutation).

### `POST /mem?addr=<a>[&bank=<b>]`  *(0.3)*
Write (poke) memory. The write-sibling of `GET /mem`; same address/bank model.
- `addr`, `bank` — as for the read form. `len` is NOT a query param: the byte
  count is the request **body** length.
- Body — `application/octet-stream`, the raw bytes to write starting at `addr`.
  Servers MAY cap the body (recommend ≥ 65536).
- Response: `{ "written": <n> }` — bytes actually written. A server MAY write
  fewer than requested (e.g. it stops at a ROM/unwritable boundary); the count
  tells the truth.
- Writes go through the emulator's CPU write path. Intended for RAM/state
  fixup (force lives, seed a level, restore a snapshot). Writing an I/O register
  MAY trigger device side effects — that is the caller's responsibility.
- Determinism: poke while `paused` so the machine can't overwrite between the
  write and a subsequent read.

### `GET /regs`
CPU registers as JSON. Keys are platform-specific (appendix); values are decimal
unless suffixed `_hex`. Example (x16 / 65C02):
```json
{ "a":0, "x":16, "y":2, "sp":505, "pc":49152, "status":32,
  "ram_bank":1, "rom_bank":0 }
```

### `POST /step?frames=<n>`  *(recommended; required for frame-exact tests)*
Advance the machine by exactly `n` complete frames (default 1), then halt.
- Only meaningful when the machine is paused (see `/pause`). On a free-running
  machine, servers SHOULD pause, run `n` frames, and stay paused.
- Response: `{ "frame": <new frame counter> }`.
- `POST /step?cycles=<n>` MAY be offered for sub-frame stepping.

### `POST /pause` / `POST /resume`  *(recommended)*
Halt / free-run. `{ "paused": true|false }`. A machine launched with a
`--control-pause`-style option SHOULD boot paused so tests are deterministic
from frame 0.

### `POST /key?text=<char> | ?code=<n>  [&down=0|1]`  *(0.2)*
Inject a key. Query params (like `/mem` and `/step`), no body:
- `text` — a single character, mapped to the platform's keyboard.
- `code` — a raw platform key code (e.g. fabgl virtual key on Agon, an SDL/PS2
  code on others). `text` and `code` are alternatives; provide one.
- `down` — `1` presses (holds), `0` releases; **omitted taps** (press then
  release). Holding across `/step` frames is how a program that samples input
  each frame (e.g. a game) actually sees the key.
- Response: `{ "injected": true }`. Missing/unmapped key → 400.

Injection plus `/step` retires scripted-autoexec input: press → step → assert →
release, deterministically.

### `POST /reset`  *(0.2)*
Soft/cold reset the machine. Response `{ "reset": true }`. The `frame` counter
MAY reset here (the one case `/status.frame` is allowed to go backwards).

### `GET /audio`  *(0.3)*
Drain the audio the emulator has synthesised since the last `/audio` call — the
audio analogue of `/screenshot`, but a *window* (everything since last drain)
rather than a snapshot.
- Response: `audio/wav`, a self-describing **PCM WAV** (RIFF, 16-bit signed,
  interleaved). The header carries the sample rate and channel count; clients
  read them from the WAV — do not hardcode (appendix lists native rates).
- The server keeps a bounded ring of mixed output samples, teed from the same
  buffer that feeds the sound device. Each call empties the ring and returns it;
  an empty ring returns a valid zero-frame WAV.
- Determinism: under `/pause` + `/step`, the drain covers exactly the audio of
  the stepped frames, so a test can `pause → step(n) → GET /audio` and get the
  sound of those `n` frames reproducibly.
- `X-Rrdc-Audio-Dropped: <n>` — samples the ring dropped (oldest-first) to
  overflow since the last drain. Non-zero means drain more often. `0` when clean.

## Consistency (normative)

- `/mem`, `/regs`, and `/step` MUST be serviced on the emulator thread at an
  instruction boundary — e.g. the HTTP handler enqueues a command that the main
  loop drains between instructions/frames and signals back. The HTTP thread MUST
  NOT read CPU/RAM state directly while the CPU is executing.
- `/screenshot` MUST serve a complete-frame snapshot (double-buffer: render
  thread writes the back buffer, swaps under a lock at frame end; HTTP thread
  reads the front buffer).
- `frame` in `/status` MUST increment once per completed video frame and never
  go backwards (except across `/reset`).

## Versioning

- Semantic. MAJOR bump = breaking change to an existing endpoint's
  request/response. MINOR = additive (new endpoint / optional field). PATCH =
  clarification.
- Clients read `/status.contract` and fail fast on a MAJOR mismatch.

---

## Per-platform appendix

### Commander X16 — `x16emu`
- Flag: `-controlport <N>` (single-dash, matching x16emu's `-dump` style).
- Framebuffer: **640×480**, native order BGRA8888 (`framebuffer[i*4+2]=R`,
  `+1=G`, `+0=B`); the server swizzles to PPM RGB.
- Address space: 16-bit CPU (`0x0000–0xFFFF`). The banked window `0xA000–0xBFFF`
  is selected by `bank` → the emulator's `read6502(addr, bank)` / banked RAM
  (`BRAM`). `addr < 0xA000` or `≥ 0xC000` ignores `bank`.
- Registers: `a x y` (8), `sp pc` (16), `status` (8), plus `ram_bank`,
  `rom_bank`. Source: the `regs` struct + `memory_get_ram_bank/rom_bank()`.
- Frame source: `video.c` `frame_count`.
- Audio: stereo (2 ch), native rate `25000000/512` ≈ **48828 Hz**, teed from the
  mixed `audio_render()` output.

### Neo6502 — neo6502 emulator
- Flag: `--control-port <N>`.
- Address space: flat 64 KB; `bank` ignored.
- Registers: 6502 `a x y sp pc status`.
- Framebuffer: native resolution per the emulator's video mode.

### Agon (Console8 / Light 2) — FAB Agon Emulator
- **Adoption:** conform-only (Rust emulator — keeps its own HTTP server, matches
  this contract rather than vendoring the C core).
- Flag: `--control-port <N>`.
- Address space: eZ80 24-bit, flat 16 MB (`addr` up to `0xFFFFFF`); `bank`
  tolerated and ignored. Program load base `0x040000`.
- Registers (ADL) — `/regs` example (16-bit regs; `mbase` 8-bit; `adl` 0/1):
  ```json
  { "af":0, "bc":0, "de":0, "hl":0, "ix":0, "iy":0,
    "sp":0, "pc":262144, "mbase":0, "adl":1 }
  ```
- Framebuffer: from `vgabuf` (the VDP output); the offscreen path already keeps
  video alive (the FAB equivalent of x16's `SDL_VIDEODRIVER=dummy`).
- Input: `/key?text=c` maps the char to a fabgl virtual key (`ascii2vk`) and
  delivers it via `sendVKeyEventToFabgl`; `?code=<vk>` passes a raw fabgl vkey.
  The control thread queues events; the render thread delivers them (same
  thread as normal keyboard input). `/reset` triggers the soft-reset atomic.

### NEC PC-FX — `mednafen` (Doomsday One fork)
- **Adoption:** vendors the shared core as a git submodule
  (`src/extern/retro-remote-debug-controller`), built in with `./configure
  --enable-rrdc`. Dispatched per running console, so PC Engine and Saturn can
  reuse the same core once their backends land.
- Control port: the `MEDNAFEN_CONTROLPORT=<N>` environment variable (Mednafen
  exposes no free-form CLI flag for a driver add-on). Unset ⇒ server off.
- Address space: V810, flat **2 MB** main RAM (`0x000000–0x1FFFFF`); `addr`
  wraps in that space and `bank` is ignored.
- Registers: `pc` + `r0`–`r31` (33 × 32-bit), from the V810 core.
- Framebuffer: the active display rect (typically 256×240), decoded to RGB888
  by the fork with the surface's channel shifts, so it is correct regardless of
  Mednafen's display-dependent pixel order.
- Audio: stereo, at Mednafen's configured output rate (`espec.SoundRate`),
  teed from the per-frame `SoundBuf`.
- Input: the PC-FX has a gamepad, not a keyboard, so `/key?text=<c>` and
  `/key?code=<n>` are both read as a character over a WASD-style pad map —
  `w/a/s/d` = up/left/down/right, space or Enter = RUN (start), `c` = SELECT,
  `1`–`6` = buttons I–VI. A held button is re-asserted each frame (the frontend
  rewrites the pad from physical input every frame), so holds persist across
  `/step`. `/reset` power-cycles the machine.

---

## Adoption paths

An emulator conforms by exposing exactly the HTTP surface above — nothing else
is required. Two ways to get there:

- **Vendor the shared core** (`core/retro_control.c` + `.h`) — for C/C++
  emulators. Implement the backend callbacks (four are enough for 0.1; add
  `inject_key`/`reset` for 0.2 and `write_mem`/`capture_audio` for 0.3 — a NULL
  callback makes its endpoint return 501 and lowers the advertised contract),
  wire three loop hooks, call `retro_control_start(port, &backend)`; the socket
  loop, HTTP parsing, PPM/JSON encoding and pause/step control come for free.
  The Commander X16 fork does this.
- **Conform directly** — for emulators in other languages (the FAB Agon emulator
  is Rust). Keep your own HTTP server; just match the contract and pass the
  conformance suite. Sharing the C core is an optimization, not a requirement —
  the contract is the asset.

Either way, `conformance/` is the arbiter: pass it and you conform.

## In this repo

- `core/retro_control.{c,h}` — portable server + backend vtable (vendor path).
- `client/emu_control.py` — the shared pytest client.
- `conformance/` — a platform-agnostic pytest that proves an emulator conforms.
