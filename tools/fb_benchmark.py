#!/usr/bin/env python3
"""Benchmark full-frame RGB565 writes to a Linux framebuffer."""

import argparse
import mmap
import os
import struct
import time


WIDTH = 320
HEIGHT = 240
BYTES_PER_PIXEL = 2
FRAME_BYTES = WIDTH * HEIGHT * BYTES_PER_PIXEL


def rgb565(red: int, green: int, blue: int) -> int:
    return ((red & 0xF8) << 8) | ((green & 0xFC) << 3) | (blue >> 3)


def solid_frame(red: int, green: int, blue: int) -> bytes:
    pixel = struct.pack("<H", rgb565(red, green, blue))
    return pixel * (WIDTH * HEIGHT)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default="/dev/fb0")
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--target-fps", type=float, default=30.0)
    args = parser.parse_args()

    frames = [
        solid_frame(255, 0, 0),
        solid_frame(0, 255, 0),
        solid_frame(0, 0, 255),
        solid_frame(255, 255, 255),
        solid_frame(0, 0, 0),
    ]

    fd = os.open(args.device, os.O_RDWR)
    fb = mmap.mmap(fd, FRAME_BYTES, access=mmap.ACCESS_WRITE)
    original = fb[:FRAME_BYTES]
    interval = 1.0 / args.target_fps
    count = 0
    late = 0
    start = time.perf_counter()
    deadline = start

    try:
        while True:
            now = time.perf_counter()
            if now - start >= args.seconds:
                break
            fb.seek(0)
            fb.write(frames[count % len(frames)])
            count += 1
            deadline += interval
            remaining = deadline - time.perf_counter()
            if remaining > 0:
                time.sleep(remaining)
            else:
                late += 1
    finally:
        elapsed = time.perf_counter() - start
        fb.seek(0)
        fb.write(original)
        fb.flush()
        fb.close()
        os.close(fd)

    mib = count * FRAME_BYTES / 1024 / 1024
    print(f"frames={count}")
    print(f"elapsed_seconds={elapsed:.4f}")
    print(f"application_fps={count / elapsed:.2f}")
    print(f"framebuffer_mib_per_second={mib / elapsed:.2f}")
    print(f"late_frames={late}")


if __name__ == "__main__":
    main()
