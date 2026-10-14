"""Draw the app icon (a burst train on a dark tile) as a PNG using only the standard library.

Usage: python make_icon.py out.png
"""
import math
import struct
import sys
import zlib

W = H = 1024
R = 190  # corner radius
BG = (22, 78, 99)
FG = (255, 255, 255)
ACCENT = (120, 220, 200)


def tile_alpha(x, y):
    if R <= x < W - R or R <= y < H - R:
        return 1.0
    cx = R if x < R else W - R - 1
    cy = R if y < R else H - R - 1
    d = math.hypot(x - cx, y - cy)
    return max(0.0, min(1.0, R - d + 0.5))


def wave_y(x):
    """Burst train: 3-cycle sine bursts separated by flat gaps."""
    left, right = 150, 874
    if not left <= x <= right:
        return None
    period = (right - left) / 2.0           # two bursts
    t = (x - left) % period
    burst_len = period * 0.55
    cy = H / 2
    if t < burst_len:
        return cy - 190 * math.sin(2 * math.pi * 3 * t / burst_len)
    return cy


def main(path):
    pix = [[(0, 0, 0, 0)] * W for _ in range(H)]
    for y in range(H):
        row = pix[y]
        for x in range(W):
            a = tile_alpha(x, y)
            if a > 0:
                row[x] = (BG[0], BG[1], BG[2], int(255 * a))

    # Stamp anti-aliased discs along the curve; keep the maximum coverage per pixel.
    radius = 15.0
    span = int(radius) + 2
    cov_sine = [[0.0] * W for _ in range(H)]
    cov_flat = [[0.0] * W for _ in range(H)]
    x = 150.0
    while x <= 874.0:
        yc = wave_y(x)
        flat = abs(yc - H / 2) < 1e-6
        buf = cov_flat if flat else cov_sine
        for yy in range(int(yc) - span, int(yc) + span + 1):
            if not 0 <= yy < H:
                continue
            for xx in range(int(x) - span, int(x) + span + 1):
                if not 0 <= xx < W:
                    continue
                d = math.hypot(xx - x, yy - yc)
                c = radius - d + 0.5
                if c > 0:
                    c = min(1.0, c)
                    if c > buf[yy][xx]:
                        buf[yy][xx] = c
        x += 0.25

    for y in range(H):
        for x in range(W):
            r, g, b, a = pix[y][x]
            for buf, col in ((cov_flat, ACCENT), (cov_sine, FG)):
                c = buf[y][x]
                if c > 0:
                    r, g, b = int(r + (col[0] - r) * c), int(g + (col[1] - g) * c), int(b + (col[2] - b) * c)
            pix[y][x] = (r, g, b, a)
    raw = b"".join(b"\x00" + b"".join(struct.pack("4B", *p) for p in row) for row in pix)

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    with open(path, "wb") as fh:
        fh.write(png)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "icon.png")
