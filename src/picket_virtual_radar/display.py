from __future__ import annotations

import mmap
import os
from typing import Any


class FramebufferDisplay:
    """RGB565 Pygame surface backed by a Linux framebuffer."""

    def __init__(self, device: str, width: int, height: int) -> None:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        import pygame

        self._pygame: Any = pygame
        pygame.init()
        pygame.display.set_mode((width, height))
        self.surface = pygame.Surface(
            (width, height), depth=16, masks=(0xF800, 0x07E0, 0x001F, 0)
        )
        self._frame_bytes = width * height * 2
        self._width = width
        self._height = height
        self._fd = os.open(device, os.O_RDWR)
        self._fb = mmap.mmap(self._fd, self._frame_bytes, access=mmap.ACCESS_WRITE)
        self._closed = False
        self.frames_presented = 0
        self.bytes_presented = 0

    @property
    def pygame(self) -> Any:
        return self._pygame

    def present(self, rectangles: list[Any] | None = None) -> None:
        raw = self.surface.get_view("0").raw
        if rectangles is None:
            self._fb.seek(0)
            self._fb.write(raw)
            written = self._frame_bytes
        else:
            written = 0
            bounds = self._pygame.Rect(0, 0, self._width, self._height)
            for rectangle in rectangles:
                clipped = self._pygame.Rect(rectangle).clip(bounds)
                if clipped.width == 0 or clipped.height == 0:
                    continue
                row_bytes = clipped.width * 2
                for y in range(clipped.top, clipped.bottom):
                    offset = (y * self._width + clipped.left) * 2
                    self._fb.seek(offset)
                    self._fb.write(raw[offset : offset + row_bytes])
                    written += row_bytes
        self.frames_presented += 1
        self.bytes_presented += written

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.surface.fill((0, 0, 0))
        self.present()
        self._fb.flush()
        self._fb.close()
        os.close(self._fd)
        self._pygame.quit()

    def __enter__(self) -> "FramebufferDisplay":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
