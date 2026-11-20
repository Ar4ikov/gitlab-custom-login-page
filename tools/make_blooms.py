"""Turn the generated backgrounds (*.raw.jpg) into blurred, grainy corner "blooms" (350x600 webp)."""
import glob, os, numpy as np
from PIL import Image, ImageFilter
SRC = {1: 'a-peach-nebula-s11', 2: 'b-aurora-ribbons-s22', 3: 'c-liquid-glass-s31', 4: 'd-grain-orb-s41',
       5: 'e-ink-smoke-s52', 6: 'f-voxel-drift-s61', 7: 'g-topo-lines-s71', 8: 'h-prism-shards-s81'}
W, H = 350, 600            # 2x of GitLab's 350x600 bloom-side slot (anchored top right)
out = os.environ.get('OUT', 'bloom'); os.makedirs(out, exist_ok=True)
rng = np.random.default_rng(7)
yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
dx, dy = (W - xx) / W, yy / H                      # distance from the top-right corner, 0..1
r = np.clip(1 - np.sqrt(dx ** 2 + dy ** 2) / 0.94, 0, 1)
mask = r * r * (3 - 2 * r)                         # smoothstep: exactly 0 before the left / bottom edges
SRC = {k: v for k, v in SRC.items() if k not in (3, 8)}   # glass and prism blur into grey mush
sheet = Image.new('RGB', (W * 6, H), (14, 13, 18))
for n, name in SRC.items():
    im = Image.open(os.path.join(os.environ.get('SRC', 'out'), f'{name}.raw.jpg')).convert('RGB')
    a = np.asarray(im).astype(np.float32)
    ys, xs = np.where(a.max(axis=2) > 60)          # crop to the colourful part
    im = im.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))
    s = max(W / im.width, H / im.height)
    im = im.resize((int(im.width * s) + 1, int(im.height * s) + 1), Image.LANCZOS)
    l, t = (im.width - W) // 2, (im.height - H) // 2
    im = im.crop((l, t, l + W, t + H)).filter(ImageFilter.GaussianBlur(36))
    a = np.asarray(im).astype(np.float32) / 255
    a = a / max(a.max(), 1e-3)                     # normalise brightness after the heavy blur
    flips = [a, a[:, ::-1], a[::-1], a[::-1, ::-1]] # put the brightest part under the top-right corner
    a = max(flips, key=lambda f: float((f.max(axis=2) * mask).sum()))
    lum = a.max(axis=2)
    alpha = mask * np.clip(0.3 + lum * 1.0, 0, 1) * 0.92
    rgb = np.clip(a + rng.normal(0, 0.05, (H, W, 1)).astype(np.float32), 0, 1)
    alpha = alpha * (1 + rng.normal(0, 0.10, (H, W)).astype(np.float32)) + (mask > 0) * rng.uniform(-0.5, 0.5, (H, W)).astype(np.float32) / 255
    alpha = np.clip(alpha, 0, 1)
    res = Image.fromarray((np.dstack([rgb, alpha]) * 255).astype(np.uint8), 'RGBA')
    res.save(f'{out}/side-{n}.webp', quality=70, alpha_quality=100, method=6)
    prev = Image.new('RGBA', (W, H), (14, 13, 18, 255)); prev.alpha_composite(res)
    sheet.paste(prev.convert('RGB'), (list(SRC).index(n) * W, 0))
sheet.save(os.path.join(out, 'sheet.jpg'), quality=85)   # contact sheet for a quick look
print({f: os.path.getsize(f) for f in sorted(glob.glob(out + '/*.webp'))})
