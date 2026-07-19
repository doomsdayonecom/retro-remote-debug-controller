/* retro_control.h — portable emulator control server (see ../SPEC.md).
 *
 * A retro-platform emulator implements the small read-only backend below and
 * calls retro_control_start(). The shared server (retro_control.c) owns the
 * socket loop, HTTP parsing, PPM/JSON encoding, and control flow
 * (pause / step / free-run). It always binds 127.0.0.1. Contract 0.1.0.
 *
 * Integration is three calls in the emulator's main loop:
 *   retro_control_service();                 // once per iteration (cheap)
 *   if (!retro_control_running()) { idle; }  // gate advancing the machine
 *   ... run one instruction / frame ...
 *   if (frame_completed) retro_control_on_frame();
 *
 * Threading: the server runs on its own thread but never touches machine state
 * there. State-reading endpoints (/mem, /regs, /screenshot) are executed inside
 * retro_control_service() ON THE EMULATOR THREAD, so every read is consistent.
 * The backend callbacks are therefore called from the emulator thread (except
 * get_frame_count, which the server may also read for /status — make it a plain
 * atomic-ish counter read).
 */
#ifndef RETRO_CONTROL_H
#define RETRO_CONTROL_H

#include <stdint.h>
#include <stddef.h>

#define RETRO_CONTROL_CONTRACT "0.1.0"

/* Native framebuffer pixel layout; the server swizzles to PPM RGB. */
typedef enum {
    RETRO_PIX_RGB888 = 0,   /* 3 bytes/px: R,G,B                       */
    RETRO_PIX_RGBA8888,     /* 4 bytes/px: R,G,B,A                     */
    RETRO_PIX_BGRA8888      /* 4 bytes/px: B,G,R,A (x16 framebuffer)   */
} retro_pix_fmt_t;

typedef struct {
    const uint8_t *pixels;  /* start of the current complete frame     */
    int width;
    int height;
    retro_pix_fmt_t fmt;
} retro_framebuffer_t;

/* The emulator implements these. Any may be NULL: the matching endpoint then
 * returns 501 Not Implemented. */
typedef struct retro_control_backend {
    const char *platform;   /* "x16" | "neo6502" | "agon" | ...        */
    const char *emulator;   /* human name, e.g. "x16emu"               */

    /* Debug-read up to min(len, out_cap) bytes at addr into out, side-effect
     * free. bank is the optional bank selector (<0 = current bank). Returns the
     * number of bytes written. */
    uint32_t (*read_mem)(uint32_t addr, int32_t bank, uint32_t len,
                         uint8_t *out, uint32_t out_cap);

    /* Write a JSON object of registers into buf (NUL-terminated). */
    void (*get_regs_json)(char *buf, size_t cap);

    /* Report the current complete-frame framebuffer. */
    void (*get_framebuffer)(retro_framebuffer_t *out);

    /* Monotonic completed-frame counter. */
    uint64_t (*get_frame_count)(void);
} retro_control_backend_t;

/* Start the server thread bound to 127.0.0.1:port. Non-blocking; 0 on success,
 * negative on error. backend must outlive the server. */
int  retro_control_start(int port, const retro_control_backend_t *backend);

/* Drain a pending control request. Call once per main-loop iteration, at an
 * instruction/frame boundary. Cheap no-op when idle and when control is off. */
void retro_control_service(void);

/* Nonzero => the machine should advance this iteration. Returns 1 always when
 * control is off or the machine is free-running; 0 when paused with no steps
 * left. */
int  retro_control_running(void);

/* Call when a video frame completes. Drives /step (decrements the step budget,
 * halts and answers when it reaches zero). No-op when control is off. */
void retro_control_on_frame(void);

/* Stop the server (optional; process exit is fine too). */
void retro_control_stop(void);

#endif /* RETRO_CONTROL_H */
