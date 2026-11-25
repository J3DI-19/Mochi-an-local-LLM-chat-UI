"""Draws the Mochi app icon (mochi.ico) with Pillow - run once with any Python that has Pillow."""
import sys
from PIL import Image, ImageDraw, ImageFilter
S = 1024
def lerp(a, b, t): return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
# body gradient (diagonal violet -> pink -> peach)
grad = Image.new("RGBA", (S, S)); px = grad.load()
c1, c2, c3 = (186, 168, 255), (255, 126, 182), (255, 165, 122)
for y in range(S):
    for x in range(0, S, 4):
        t = min(1, max(0, (x * .45 + y * .75) / (S * 1.05)))
        col = lerp(c1, c2, t / .65) if t < .65 else lerp(c2, c3, (t - .65) / .35)
        for k in range(4): px[x + k, y] = col + (255,)
mask = Image.new("L", (S, S), 0); m = ImageDraw.Draw(mask)
m.ellipse([110, 200, 914, 940], fill=255)
img.paste(grad, (0, 0), mask)
d = ImageDraw.Draw(img)
d.line([(512, 210), (500, 140), (560, 85)], fill=(154, 124, 255, 255), width=34, joint="curve")
glow = Image.new("RGBA", (S, S), (0, 0, 0, 0)); ImageDraw.Draw(glow).ellipse([510, 20, 650, 160], fill=(255, 211, 110, 200))
img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(18))); d = ImageDraw.Draw(img)
d.ellipse([540, 50, 620, 130], fill=(255, 211, 110, 255))
hl = Image.new("RGBA", (S, S), (0, 0, 0, 0)); ImageDraw.Draw(hl).ellipse([250, 300, 430, 390], fill=(255, 255, 255, 90))
img = Image.alpha_composite(img, hl.rotate(28, center=(340, 345)).filter(ImageFilter.GaussianBlur(6))); d = ImageDraw.Draw(img)
ink = (27, 21, 48, 255)
for cx in (380, 644):
    d.ellipse([cx - 56, 470, cx + 56, 620], fill=ink); d.ellipse([cx - 8, 492, cx + 36, 536], fill=(255, 255, 255, 255))
for cx in (290, 734): d.ellipse([cx - 52, 640, cx + 52, 690], fill=(255, 94, 154, 120))
d.arc([440, 600, 584, 720], 20, 160, fill=ink, width=30)
img = img.resize((256, 256), Image.LANCZOS)
out = sys.argv[1] if len(sys.argv) > 1 else "mochi.ico"
img.save(out, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]); img.save(out.replace(".ico", ".png"))
print("ok", out)
