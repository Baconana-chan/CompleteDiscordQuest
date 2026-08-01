"""Generate a 1024x1024 app icon (blurple rounded square + gamepad glyph)
using only the Python standard library. No PIL required.

Usage:  python scripts/gen_icon.py
Output: app-icon.png
"""
import struct
import zlib

SIZE = 1024


def inside_round_rect(x, y, x0, y0, x1, y1, r):
    if x < x0 or x > x1 or y < y0 or y > y1:
        return False
    cx = min(max(x, x0 + r), x1 - r)
    cy = min(max(y, y0 + r), y1 - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def inside_circle(x, y, cx, cy, r):
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def build_rows():
    rows = []
    for y in range(SIZE):
        row = bytearray()
        t = y / SIZE
        for x in range(SIZE):
            # blurple vertical gradient
            r = int(0x58 + (0x3C - 0x58) * t)
            g = int(0x65 + (0x45 - 0x65) * t)
            b = int(0xF2 + (0xBF - 0xF2) * t)
            a = 255
            if not inside_round_rect(x, y, 36, 36, SIZE - 36, SIZE - 36, 190):
                a = 0  # transparent outside the rounded square
            else:
                # gamepad body (white rounded rect)
                if inside_round_rect(x, y, 200, 330, 824, 694, 96):
                    r, g, b = 255, 255, 255
                    # dpad cross (dark)
                    if (
                        inside_round_rect(x, y, 412, 430, 478, 594, 22)
                        or inside_round_rect(x, y, 352, 490, 538, 534, 22)
                    ):
                        r, g, b = 0x23, 0x25, 0x2B
                    # two buttons (dark)
                    if inside_circle(x, y, 662, 452, 46) or inside_circle(x, y, 662, 572, 46):
                        r, g, b = 0x23, 0x25, 0x2B
            row += bytes((r, g, b, a))
        rows.append(bytes(row))
    return rows


def write_png(path, rows):
    def chunk(tag, data):
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0)
    raw = b"".join(b"\x00" + row for row in rows)  # filter 0 per scanline
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    with open(path, "wb") as f:
        f.write(png)


if __name__ == "__main__":
    write_png("app-icon.png", build_rows())
    print("wrote app-icon.png")
