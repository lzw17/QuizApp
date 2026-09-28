# -*- coding: utf-8 -*-
"""Process generated app icons:
1. Remove the bottom-right "AI generated" watermark by vertical gradient extrapolation.
2. Export WeChat-compliant sizes (1024 / 512 / 144).
3. Build a 2x2 circular-crop preview sheet for picking.

Run with the system python that has pillow installed.
"""
import os
import sys
from PIL import Image, ImageDraw, ImageFont

RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "raw")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "clean")

SOURCES = [
    ("Flat_vector_app_icon_for_a_stu_2026-09-28T06-18-25.png", "A-book-bulb"),
    ("Flat_vector_app_icon_for_an_AI_2026-09-28T06-18-25.png", "B-book-spark"),
    ("Minimal_flat_vector_app_icon___2026-09-28T06-18-25.png", "C-docs-spark"),
    ("Flat_vector_app_icon_for_a_qui_2026-09-28T06-18-24.png", "D-book-check"),
]


def find_watermark_bbox(img):
    """Locate the bright watermark pixels in the bottom-right corner."""
    w, h = img.size
    px = img.convert("RGB").load()
    # search window: bottom-right quadrant corner
    x_start = int(w * 0.75)
    y_start = int(h * 0.90)
    xs, ys = [], []
    for y in range(y_start, h):
        for x in range(x_start, w):
            r, g, b = px[x, y]
            # watermark is semi-transparent white over a dark gradient:
            # text pixels have min-channel ~145-150 while background stays below 60
            bright_white = min(r, g, b) > 120
            cyan = b > 150 and g > 150 and r < 160 and (g - r) > 30
            if bright_white or cyan:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    m = 10  # safety margin
    return (max(0, min(xs) - m), max(0, min(ys) - m),
            min(w, max(xs) + m), min(h, max(ys) + m))


def heal_vertical(img, bbox):
    """Fill bbox by extrapolating the vertical gradient from rows just above it."""
    px = img.load()
    w, h = img.size
    x0, y0, x1, y1 = bbox
    y1 = max(y1, h)          # watermark touches the bottom edge
    y_ref_a = y0 - 3         # nearer reference row band
    y_ref_b = y0 - 14        # farther reference row band
    if y_ref_b < 0:
        y_ref_b = 0
    for x in range(x0, x1):
        ca = px[x, max(0, y_ref_a)]
        cb = px[x, max(0, y_ref_b)]
        span = max(1, y_ref_a - y_ref_b)
        # per-channel gradient, clamped to keep it subtle
        for y in range(y0, y1):
            t = (y - y_ref_a) / span
            px[x, y] = tuple(
                max(0, min(255, int(c + (ca[i] - cb[i]) * t)))
                for i, c in enumerate(ca)
            )
    return img


def smooth_patch(img, bbox, radius=3):
    """Blur only the healed region to hide extrapolation streaks."""
    from PIL import ImageFilter

    x0, y0, x1, y1 = bbox
    y1 = max(y1, img.size[1])
    region = img.crop((x0, y0, x1, y1)).filter(ImageFilter.GaussianBlur(radius))
    img.paste(region, (x0, y0))
    return img


def circle_crop(img, size):
    """Return a square RGBA image masked to the largest inscribed circle."""
    im = img.resize((size, size), Image.LANCZOS).convert("RGBA")
    mask = Image.new("L", (size * 4, size * 4), 0)  # 4x supersample for smooth edge
    ImageDraw.Draw(mask).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
    mask = mask.resize((size, size), Image.LANCZOS)
    im.putalpha(mask)
    return im


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    cleaned = {}
    for fname, tag in SOURCES:
        path = os.path.join(RAW_DIR, fname)
        img = Image.open(path).convert("RGB")
        bbox = find_watermark_bbox(img)
        if bbox:
            img = heal_vertical(img, bbox)
            img = smooth_patch(img, bbox)
            print("%s: healed watermark bbox=%s" % (tag, bbox))
        else:
            print("%s: no watermark found" % tag)
        cleaned[tag] = img
        # export standard sizes
        for size in (1024, 512, 144):
            out = os.path.join(OUT_DIR, "icon-%s-%d.png" % (tag, size))
            img.resize((size, size), Image.LANCZOS).save(out, optimize=True)
        print("  exported 1024/512/144 -> %s" % OUT_DIR)

    # 2x2 circular preview sheet
    cell, pad = 360, 40
    sheet = Image.new("RGB", (cell * 2 + pad * 3, cell * 2 + pad * 3), (245, 245, 248))
    for i, (tag, img) in enumerate(cleaned.items()):
        cx = pad + (i % 2) * (cell + pad)
        cy = pad + (i // 2) * (cell + pad)
        circ = circle_crop(img, cell)
        sheet.paste(circ, (cx, cy), circ)
        label = tag.split("-")[0]
        try:
            font = ImageFont.truetype("arial.ttf", 44)
        except Exception:
            font = ImageFont.load_default()
        ImageDraw.Draw(sheet).text((cx + cell // 2 - 10, cy + cell + 4), label,
                                   fill=(60, 60, 70), font=font)
    preview = os.path.join(OUT_DIR, "preview-circle-crop.png")
    sheet.save(preview, optimize=True)
    print("preview sheet ->", preview)


if __name__ == "__main__":
    sys.exit(main())
