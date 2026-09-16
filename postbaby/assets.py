"""PostBaby asset management and geometric icon generator.

Generates and loads multi-resolution Windows ICO and PNG assets for
the PostBaby pacifier 🍼 brand identity using only Python standard library.
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

ASSETS_DIR = Path(__file__).parent


def _create_png(width: int, height: int, rgba_data: bytes) -> bytes:
    """Create a valid PNG image byte stream from RGBA pixel data."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    header = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    
    # Prepend filter byte 0 (None) to each row
    raw_rows = bytearray()
    row_bytes = width * 4
    for y in range(height):
        raw_rows.append(0)
        raw_rows.extend(rgba_data[y * row_bytes : (y + 1) * row_bytes])
    
    idat = chunk(b"IDAT", zlib.compress(bytes(raw_rows), level=9))
    iend = chunk(b"IEND", b"")
    return header + ihdr + idat + iend


def _draw_pacifier(size: int) -> bytes:
    """Render a clean, modern geometric pacifier icon with antialiasing."""
    # RGBA buffer
    pixels = bytearray(size * size * 4)
    scale = size / 64.0

    def set_pixel(x: int, y: int, r: int, g: int, b: int, a: float):
        if 0 <= x < size and 0 <= y < size and a > 0.0:
            idx = (y * size + x) * 4
            current_a = pixels[idx + 3] / 255.0
            out_a = a + current_a * (1.0 - a)
            if out_a > 0:
                out_r = (r * a + pixels[idx] * current_a * (1.0 - a)) / out_a
                out_g = (g * a + pixels[idx + 1] * current_a * (1.0 - a)) / out_a
                out_b = (b * a + pixels[idx + 2] * current_a * (1.0 - a)) / out_a
                pixels[idx] = int(min(255, max(0, out_r)))
                pixels[idx + 1] = int(min(255, max(0, out_g)))
                pixels[idx + 2] = int(min(255, max(0, out_b)))
                pixels[idx + 3] = int(min(255, max(0, out_a * 255)))

    # Centers scaled to 64x64 grid
    # Teat (top): ellipse centered at (32, 20) with rx=12, ry=14 (soft cyan/teal #2DD4BF -> #0EA5E9)
    # Shield (middle): rounded pill centered at (32, 36) with width=42, height=14 (#0284C7 / #0369A1)
    # Ring / Handle (bottom): torus ring centered at (32, 48) with outer r=11, inner r=6 (#F43F5E / #FB7185)

    for py in range(size):
        for px in range(size):
            # Supersampling (2x2 grid per pixel for smooth edges)
            for sub_y in (0.25, 0.75):
                for sub_x in (0.25, 0.75):
                    gx = (px + sub_x) / scale
                    gy = (py + sub_y) / scale
                    weight = 0.25

                    # 1. Ring / Handle (bottom)
                    ring_dx = gx - 32.0
                    ring_dy = gy - 47.0
                    ring_dist = math.hypot(ring_dx, ring_dy)
                    if 4.5 <= ring_dist <= 11.5:
                        # Soft coral ring
                        set_pixel(px, py, 244, 63, 94, weight * 0.95)

                    # 2. Teat (top bulb)
                    teat_dx = (gx - 32.0) / 11.5
                    teat_dy = (gy - 19.0) / 13.5
                    teat_dist = teat_dx * teat_dx + teat_dy * teat_dy
                    if teat_dist <= 1.0 and gy <= 35.0:
                        # Gradient from amber/gold glow to soft teal
                        alpha = min(1.0, (1.0 - teat_dist) * 4.0) * weight
                        set_pixel(px, py, 56, 189, 248, alpha)

                    # 3. Shield (middle guard)
                    shield_dx = abs(gx - 32.0)
                    shield_dy = abs(gy - 34.0)
                    # Rounded rectangle shape
                    if shield_dx <= 19.0 and shield_dy <= 6.5:
                        corner_dx = max(0.0, shield_dx - 13.0)
                        corner_dy = max(0.0, shield_dy - 2.0)
                        if corner_dx * corner_dx + corner_dy * corner_dy <= 18.0:
                            # Highlight on top of shield
                            if gy < 33.0:
                                set_pixel(px, py, 14, 165, 233, weight)
                            else:
                                set_pixel(px, py, 2, 132, 199, weight)

                    # Center button on shield
                    btn_dist = math.hypot(gx - 32.0, gy - 34.0)
                    if btn_dist <= 4.0:
                        set_pixel(px, py, 255, 255, 255, weight * 0.9)

    return bytes(pixels)


def ensure_icon_assets() -> tuple[Path, Path]:
    """Generate pacifier.ico and pacifier.png if they do not exist, and return their paths."""
    ico_path = ASSETS_DIR / "pacifier.ico"
    png_path = ASSETS_DIR / "pacifier.png"

    if ico_path.exists() and png_path.exists():
        return ico_path, png_path

    resolutions = [16, 24, 32, 48, 64, 128, 256]
    png_images: list[tuple[int, bytes]] = []

    for res in resolutions:
        rgba = _draw_pacifier(res)
        png_bytes = _create_png(res, res, rgba)
        png_images.append((res, png_bytes))
        if res == 32:
            png_path.write_bytes(png_bytes)

    # Pack into ICO format
    header = struct.pack("<HHH", 0, 1, len(png_images))
    offset = 6 + 16 * len(png_images)
    entries = bytearray()
    image_data = bytearray()

    for res, png_bytes in png_images:
        w = 0 if res >= 256 else res
        h = 0 if res >= 256 else res
        size = len(png_bytes)
        entries.extend(struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, size, offset))
        image_data.extend(png_bytes)
        offset += size

    ico_bytes = header + bytes(entries) + bytes(image_data)
    ico_path.write_bytes(ico_bytes)

    # Also place a copy at the project root for PyInstaller and Inno Setup
    root_ico = ASSETS_DIR.parent / "pacifier.ico"
    root_ico.write_bytes(ico_bytes)

    return ico_path, png_path


if __name__ == "__main__":
    ensure_icon_assets()
