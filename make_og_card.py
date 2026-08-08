#!/usr/bin/env python3
"""Generate assets/og-card.jpg — the 1200x630 social-share card.

Reads the live metrics out of data/publications.json so the card can never go
stale: re-run this after `fetch_scholar.py` and the citation numbers on the
card match the numbers on the page.

    python3 make_og_card.py

Pure stdlib + Pillow. No network. Safe to re-run.
"""
import json
import os
import sys

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit("Pillow is required:  pip3 install Pillow")

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data", "publications.json")
OUT = os.path.join(ROOT, "assets", "og-card.jpg")

W, H = 1200, 630
BG = "#f4f4f5"
CARD = "#ffffff"
BORDER = "#dedfe2"
ACCENT = "#1a1a1d"
INK = "#111114"
INK2 = "#4d5057"
INK3 = "#6c6f76"
INK4 = "#8a8c90"
RULE = "#e3e4e7"

# Font candidates, first hit wins. Inter/JetBrains match the site; Helvetica is
# the macOS fallback so this still renders on a machine without them installed.
HOME = os.path.expanduser("~")
SANS_BOLD = [
    f"{HOME}/Library/Fonts/Inter-ExtraBold.ttf",
    f"{HOME}/Library/Fonts/Inter-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]
SANS = [
    f"{HOME}/Library/Fonts/Inter-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]
CJK = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
]
MONO_BOLD = [
    f"{HOME}/Library/Fonts/JetBrainsMonoNerdFont-Bold.ttf",
    f"{HOME}/Library/Fonts/JetBrainsMono-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Courier New Bold.ttf",
]


def font(candidates, size):
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def tracked(draw, xy, text, fnt, fill, spacing=0):
    """Draw text with manual letter-spacing; returns the width consumed."""
    x, y = xy
    start = x
    for ch in text:
        draw.text((x, y), ch, font=fnt, fill=fill)
        x += draw.textlength(ch, font=fnt) + spacing
    return x - start - (spacing if text else 0)


def main():
    with open(DATA, encoding="utf-8") as fh:
        data = json.load(fh)
    a = data.get("author", {})

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # Card + left accent stripe
    d.rectangle([40, 40, W - 40, H - 40], fill=CARD, outline=BORDER, width=2)
    d.rectangle([40, 40, 46, H - 40], fill=ACCENT)

    LX = 104
    tracked(d, (LX, 122), "ALGORITHM LEAD · AIGC CODE GENERATION",
            font(MONO_BOLD, 21), INK3, spacing=2.2)

    d.text((LX - 3, 190), a.get("name", "Dongming Han"), font=font(SANS_BOLD, 92), fill=INK)
    d.text((LX, 292), a.get("name_zh", "韩东明"), font=font(CJK, 38), fill=INK2)

    # Subtitle: fit inside the card by dropping trailing interests, then shrinking.
    interests = list(a.get("interests") or []) or ["Visual Analytics"]
    max_w = (W - LX) - LX
    sub_f, subtitle = None, ""
    for count in range(len(interests), 0, -1):
        candidate = " · ".join(interests[:count])
        for size in (27, 26, 25, 24, 23, 22):
            f = font(SANS, size)
            if d.textlength(candidate, font=f) <= max_w:
                sub_f, subtitle = f, candidate
                break
        if sub_f:
            break
    d.text((LX, 356), subtitle, font=sub_f or font(SANS, 22), fill=INK3)

    d.line([(LX, 438), (W - LX, 438)], fill=RULE, width=1)

    metrics = [
        (str(a.get("citedby") or ""), "CITATIONS"),
        (str(a.get("hindex") or ""), "H-INDEX"),
        (str(a.get("i10index") or ""), "i10"),
    ]
    mx = LX
    num_f, lab_f = font(MONO_BOLD, 52), font(MONO_BOLD, 18)
    for num, label in metrics:
        if not num or num == "0":
            continue
        d.text((mx, 462), num, font=num_f, fill=INK)
        nw = d.textlength(num, font=num_f)
        lw = tracked(d, (mx, 526), label, lab_f, INK3, spacing=1.8)
        mx += max(nw, lw) + 74

    # Keep the baseline clear of the card border at y=H-40 (590): a 22px face drawn
    # at y=574 puts its descenders past the stroke and the border cuts the text.
    d.text((LX, 556), a.get("affiliation", ""), font=font(SANS, 22), fill=INK4)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    img.save(OUT, "JPEG", quality=92, optimize=True)
    shown = ", ".join(f"{n} {l}" for n, l in metrics if n and n != "0")
    print(f"[og-card] wrote {OUT} ({os.path.getsize(OUT) // 1024} KB) — {shown}")


if __name__ == "__main__":
    main()
