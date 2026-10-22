"""Draws the LifeLog app icon (1024x1024) without external assets.

Usage: python3 scripts/make_icon.py
"""
from PIL import Image, ImageDraw, ImageFilter
import os

S = 1024
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def gradient(w, h, top, bottom):
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            t = (0.65 * y + 0.35 * x) / (0.65 * h + 0.35 * w)
            px[x, y] = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
    return img


def draw():
    img = gradient(S, S, (88, 86, 214), (32, 178, 170)).convert("RGBA")
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    # Three log rows: a dot and a bar each, like a timeline of entries.
    rows = [(330, 520, 255), (512, 420, 235), (694, 600, 215)]
    # Connecting spine behind the dots.
    d.rounded_rectangle((250 - 12, 330, 250 + 12, 694), radius=12, fill=(255, 255, 255, 120))
    for y, length, alpha in rows:
        d.ellipse((250 - 58, y - 58, 250 + 58, y + 58), fill=(255, 255, 255, alpha))
        d.rounded_rectangle((350, y - 40, 350 + length * 0.83, y + 40), radius=40, fill=(255, 255, 255, alpha - 40))
    shadow = layer.filter(ImageFilter.GaussianBlur(18))
    shadow_tinted = Image.new("RGBA", (S, S), (20, 20, 60, 0))
    shadow_tinted.putalpha(shadow.getchannel("A").point(lambda a: int(a * 0.35)))
    img.alpha_composite(shadow_tinted, (0, 10))
    img.alpha_composite(layer)
    return img.convert("RGB")


if __name__ == "__main__":
    icon = draw()
    for target in ["App/iOS/Assets.xcassets/AppIcon.appiconset", "App/Watch/Assets.xcassets/AppIcon.appiconset"]:
        path = os.path.join(ROOT, target)
        os.makedirs(path, exist_ok=True)
        icon.save(os.path.join(path, "AppIcon.png"))
    print("ok")
