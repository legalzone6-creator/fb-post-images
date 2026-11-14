"""Weekly 11-second brand Reel engine (720x1280, H.264 + AAC). Pure Python: PIL + numpy + ffmpeg.
Usage:  python engine.py spec.json THEME_INDEX out.mp4      (THEME_INDEX 0-7)
spec.json: {"brand":"lz|ieic|tc|medi","hook":"...","points":["...","...","..."],"cta":"..."}
Bangla and Latin text can be mixed freely; commas, digits etc. are drawn with the Latin font automatically.
"""
import os, sys, math, json, tarfile, io, subprocess, shutil, wave
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops

W, H, FPS, DUR = 720, 1280, 30, 11.0
FONT_DIR = os.environ.get('REEL_FONT_DIR', '/tmp/reel_fonts')
RQ = ImageFont.Layout.RAQM

BRANDS = {
    'lz':   dict(name='LEGAL ZONE', title='Legal Zone', base=(7, 18, 44), accent=(212, 175, 90), accent2=(240, 214, 140), phone='01611-150180', web='legalzonebd.org'),
    'ieic': dict(name='IEIC', title='IEIC', base=(6, 30, 56), accent=(0, 176, 190), accent2=(120, 224, 232), phone='01886-533105', web='ieicbd.com'),
    'tc':   dict(name='TRAVEL COUNSELLOR', title='Travel Counsellor Ltd', base=(8, 36, 52), accent=(255, 140, 56), accent2=(255, 198, 128), phone='01886-533101', web='travelcsbd.com'),
    'medi': dict(name='MEDI COUNSELLOR', title='Medi Counsellor', base=(6, 40, 46), accent=(52, 200, 150), accent2=(150, 236, 204), phone='01886-533102', web='facebook.com/medicounsellor'),
}
CREAM = (246, 242, 233)
WHITE = (247, 245, 240)

THEMES = [
    dict(name='spotlight', bg='bokeh',   light=False, latin='pf', card='glass', motion='rise'),
    dict(name='aurora',    bg='aurora',  light=False, latin='ms', card='glass', motion='slide'),
    dict(name='geometric', bg='bands',   light=False, latin='ms', card='solid', motion='slide'),
    dict(name='paper',     bg='paper',   light=True,  latin='pf', card='line',  motion='rise'),
    dict(name='grid',      bg='grid',    light=False, latin='ms', card='bar',   motion='zoom'),
    dict(name='blocks',    bg='blocks',  light=False, latin='ms', card='bar',   motion='slide'),
    dict(name='rings',     bg='rings',   light=False, latin='pf', card='glass', motion='zoom'),
    dict(name='halftone',  bg='dots',    light=True,  latin='ms', card='darksolid', motion='rise'),
]

# ---------------- fonts ----------------
NPM = {
    'bn': ('@fontsource/noto-sans-bengali', {400: 'noto-sans-bengali-bengali-400-normal.woff', 700: 'noto-sans-bengali-bengali-700-normal.woff'}),
    'pf': ('@fontsource/playfair-display', {700: 'playfair-display-latin-700-normal.woff'}),
    'ms': ('@fontsource/montserrat', {500: 'montserrat-latin-500-normal.woff', 600: 'montserrat-latin-600-normal.woff'}),
}

def ensure_fonts():
    import requests
    os.makedirs(FONT_DIR, exist_ok=True)
    for key, (pkg, files) in NPM.items():
        if all(os.path.exists(os.path.join(FONT_DIR, f)) for f in files.values()):
            continue
        meta = requests.get('https://registry.npmjs.org/%s/latest' % pkg, timeout=60).json()
        tb = requests.get(meta['dist']['tarball'], timeout=120).content
        with tarfile.open(fileobj=io.BytesIO(tb), mode='r:gz') as tf:
            for m in tf.getmembers():
                base = os.path.basename(m.name)
                if base in files.values():
                    open(os.path.join(FONT_DIR, base), 'wb').write(tf.extractfile(m).read())

_fc = {}
def fnt(kind, size, weight):
    k = (kind, size, weight)
    if k not in _fc:
        if kind == 'bn':
            p = NPM['bn'][1][700 if weight >= 600 else 400]
        elif kind == 'pf':
            p = NPM['pf'][1][700]
        else:
            p = NPM['ms'][1][600 if weight >= 600 else 500]
        _fc[k] = ImageFont.truetype(os.path.join(FONT_DIR, p), size, layout_engine=RQ)
    return _fc[k]

def is_bn(ch):
    return 'ঀ' <= ch <= '৿' or ch in '‌‍'

def runs_of(text, size, weight, latin):
    """split into (string, font) runs: Bengali script -> bn font; everything else -> latin font. Spaces follow the current run."""
    out = []
    cur, cur_k = '', None
    for ch in text:
        if ch == ' ':
            k = cur_k or 'lat'
        else:
            k = 'bn' if is_bn(ch) else 'lat'
        if cur_k is None:
            cur_k = k
        if k != cur_k:
            out.append((cur, cur_k)); cur, cur_k = '', k
        cur += ch
    if cur:
        out.append((cur, cur_k or 'lat'))
    res = []
    for s, k in out:
        f = fnt('bn', size, weight) if k == 'bn' else fnt(latin, size, weight)
        res.append((s, f))
    return res

def mixed_w(text, size, weight, latin):
    return sum(f.getlength(s) for s, f in runs_of(text, size, weight, latin))

def wrap(text, size, weight, latin, maxw):
    words, lines, cur = text.split(' '), [], ''
    for w in words:
        t = (cur + ' ' + w).strip()
        if cur and mixed_w(t, size, weight, latin) > maxw:
            lines.append(cur); cur = w
        else:
            cur = t
    if cur: lines.append(cur)
    return lines

def draw_mixed(d, text, size, weight, fill, cx, cy, latin='ms', tracking=0, anchor_x='c'):
    runs = runs_of(text, size, weight, latin)
    if tracking:
        total = sum(f.getlength(s) for s, f in runs) + tracking * (len(text) - 1)
    else:
        total = sum(f.getlength(s) for s, f in runs)
    x = cx - total / 2 if anchor_x == 'c' else cx
    base = cy + size * 0.34
    for s, f in runs:
        if tracking:
            for ch in s:
                d.text((x, base), ch, font=f, fill=fill, anchor='ls')
                x += f.getlength(ch) + tracking
        else:
            d.text((x, base), s, font=f, fill=fill, anchor='ls')
            x += f.getlength(s)

def clamp(x, a=0.0, b=1.0): return max(a, min(b, x))
def ss(x):
    x = clamp(x); return x * x * (3 - 2 * x)
def eo(x):
    x = clamp(x); return 1 - (1 - x) ** 3
def lerp(a, b, p): return a + (b - a) * p
def fin(t, t0, d=0.5): return ss((t - t0) / d)
def fout(t, t1, d=0.4): return 1 - ss((t - t1) / d)

def layer(): return Image.new('RGBA', (W, H), (0, 0, 0, 0))

# ---------------- backgrounds ----------------
def grad(top, bot):
    y = np.linspace(0, 1, H)[:, None, None]
    a = np.array(top, float)[None, None, :]; b = np.array(bot, float)[None, None, :]
    g = np.broadcast_to(a * (1 - y) + b * y, (H, W, 3))
    return g.copy()

def lighten(c, k): return tuple(int(min(255, v + (255 - v) * k)) for v in c)
def darken(c, k): return tuple(int(v * (1 - k)) for v in c)

_bgc = {}
def base_bg(b, th):
    key = (b['name'], th['bg'])
    if key in _bgc: return _bgc[key]
    if th['light']:
        arr = grad(CREAM, lighten(CREAM, 0.0) if th['bg'] == 'paper' else (236, 232, 222))
    else:
        arr = grad(darken(b['base'], 0.35), lighten(b['base'], 0.12))
        x = np.linspace(-1, 1, W)[None, :]; y = np.linspace(-1, 1, H)[:, None]
        arr *= (1 - 0.35 * (x ** 2 * 0.5 + y ** 2 * 0.45))[..., None]
    _bgc[key] = arr
    return arr

def to_img(arr): return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

_rs = np.random.default_rng(3)
BOK = [(_rs.random(), _rs.random(), _rs.uniform(6, 22), _rs.uniform(0.02, 0.06), _rs.uniform(0, 6.28), _rs.uniform(0.3, 0.9)) for _ in range(26)]

def bg_frame(b, th, t):
    kind = th['bg']
    base = to_img(base_bg(b, th))
    acc, acc2, bs = b['accent'], b['accent2'], b['base']
    if kind == 'bokeh':
        lw, lh = 180, 320
        im = Image.new('RGB', (lw, lh), (0, 0, 0)); d = ImageDraw.Draw(im)
        for (x, y, r, sp, ph, br) in BOK:
            yy = (y - sp * t) % 1.0; xx = x + 0.02 * math.sin(t * 0.6 + ph)
            a = br * (0.55 + 0.45 * math.sin(t * 1.1 + ph))
            col = tuple(int(c * a * 0.5) for c in acc)
            d.ellipse((xx * lw - r / 4, yy * lh - r / 4, xx * lw + r / 4, yy * lh + r / 4), fill=col)
        im = im.resize((W, H), Image.BICUBIC).filter(ImageFilter.GaussianBlur(4))
        return ImageChops.add(base, im)
    if kind == 'aurora':
        lw, lh = 108, 192
        im = Image.new('RGB', (lw, lh), (0, 0, 0)); d = ImageDraw.Draw(im)
        blobs = [(acc, 0.3, 0.3, 0.9, 0.7, 60), (acc2, 0.7, 0.6, 0.7, 1.1, 50), (lighten(bs, 0.35), 0.5, 0.85, 1.3, 0.5, 70)]
        for (c, x, y, sp, ph, r) in blobs:
            cx = (x + 0.22 * math.sin(t * 0.55 * sp + ph)) * lw
            cy = (y + 0.18 * math.cos(t * 0.45 * sp + ph * 2)) * lh
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=tuple(int(v * 0.42) for v in c))
        im = im.filter(ImageFilter.GaussianBlur(14)).resize((W, H), Image.BICUBIC)
        return ImageChops.add(base, im)
    if kind == 'bands':
        im = base.copy().convert('RGBA'); lay = layer(); d = ImageDraw.Draw(lay)
        off = (t * 60) % 360
        for i in range(-2, 8):
            x0 = i * 360 - off + 200
            col = (*lighten(bs, 0.10 + 0.04 * (i % 2)), 90)
            d.polygon([(x0, 0), (x0 + 170, 0), (x0 + 170 - 700, H), (x0 - 700, H)], fill=col)
        d.rectangle((0, H - 18, W, H), fill=(*acc, 255))
        d.polygon([(W - 220, 0), (W, 0), (W, 220)], fill=(*acc, 255))
        im.alpha_composite(lay)
        return im.convert('RGB')
    if kind == 'paper':
        im = base.convert('RGBA'); lay = layer(); d = ImageDraw.Draw(lay)
        for gx in range(0, W, 72): d.line([(gx, 0), (gx, H)], fill=(*bs, 14), width=1)
        for gy in range(0, H, 72): d.line([(0, gy), (W, gy)], fill=(*bs, 14), width=1)
        r = 260 + 20 * math.sin(t * 0.8)
        d.ellipse((W - r * 0.9, -r * 0.4, W + r * 0.9, r * 1.4), fill=(*acc, 70))
        d.ellipse((-160, H - 360, 260, H + 60), fill=(*acc2, 80))
        d.rectangle((0, 0, 14, H), fill=(*bs, 255))
        im.alpha_composite(lay)
        return im.convert('RGB')
    if kind == 'grid':
        im = base.convert('RGBA'); lay = layer(); d = ImageDraw.Draw(lay)
        hz = int(H * 0.46)
        ph = (t * 0.55) % 1.0
        for k in range(14):
            p = (k + ph) / 14.0
            y = hz + (H - hz) * (p ** 2.2)
            d.line([(0, y), (W, y)], fill=(*acc, int(40 + 150 * p)), width=2)
        for k in range(-9, 10):
            d.line([(W / 2 + k * 28, hz), (W / 2 + k * 190, H)], fill=(*acc, 70), width=2)
        d.ellipse((W / 2 - 240, hz - 240, W / 2 + 240, hz + 240), fill=(*acc, 34))
        im.alpha_composite(lay.filter(ImageFilter.GaussianBlur(1.2)))
        return im.convert('RGB')
    if kind == 'blocks':
        im = base.convert('RGBA'); lay = layer(); d = ImageDraw.Draw(lay)
        p = eo(t / 1.4)
        d.rectangle((0, H - int(300 * p), W, H), fill=(*acc, 255))
        d.rectangle((0, 0, int(26 * p), H), fill=(*acc2, 255))
        d.rectangle((W - int(110 * p), 0, W, int(560 * p)), fill=(*lighten(bs, 0.12), 255))
        im.alpha_composite(lay)
        return im.convert('RGB')
    if kind == 'rings':
        im = base.convert('RGBA'); lay = layer(); d = ImageDraw.Draw(lay)
        for k in range(6):
            p = ((t * 0.28) + k / 6.0) % 1.0
            r = 60 + p * 760
            d.ellipse((W / 2 - r, H * 0.5 - r, W / 2 + r, H * 0.5 + r), outline=(*acc, int(150 * (1 - p))), width=3)
        d.ellipse((W / 2 - 18, H * 0.5 - 18, W / 2 + 18, H * 0.5 + 18), fill=(*acc2, 60))
        im.alpha_composite(lay)
        return im.convert('RGB')
    if kind == 'dots':
        im = base.convert('RGBA'); lay = layer(); d = ImageDraw.Draw(lay)
        step = 44
        for gy in range(0, H + step, step):
            for gx in range(0, W + step, step):
                w = 0.5 + 0.5 * math.sin(gx * 0.012 + gy * 0.009 - t * 1.4)
                r = 2 + 9 * w * (gy / H)
                d.ellipse((gx - r, gy - r, gx + r, gy + r), fill=(*acc, int(120 + 100 * w)))
        im.alpha_composite(lay)
        return im.convert('RGB')
    return base

# ---------------- scene ----------------
def motion_off(th, t, t0, d=0.6):
    p = eo((t - t0) / d)
    m = th['motion']
    if m == 'rise': return 0, 34 * (1 - p), 1.0
    if m == 'slide': return -90 * (1 - p), 0, 1.0
    return 0, 0, 0.88 + 0.12 * p

def card_point(base, th, b, idx, text, cy, t, t0, t1):
    a = fin(t, t0, 0.45) * fout(t, t1, 0.35)
    if a <= 0.01: return
    dx, dy, sc = motion_off(th, t, t0)
    light = th['light']
    txtcol = b['base'] if light else WHITE
    size = 36
    lines = wrap(text, size, 700, th['latin'], 470)[:2]
    h = 40 + 46 * len(lines)
    x0, x1 = 60, W - 60
    top, bot = cy - h / 2 + dy, cy + h / 2 + dy
    L = layer(); d = ImageDraw.Draw(L)
    A = int(255 * a)
    kind = th['card']
    if kind == 'glass':
        d.rounded_rectangle((x0 + dx, top, x1 + dx, bot), 22, fill=(255, 255, 255, int(34 * a)), outline=(*b['accent'], int(210 * a)), width=2)
    elif kind == 'solid':
        d.rounded_rectangle((x0 + dx, top, x1 + dx, bot), 18, fill=(*b['accent'], int(245 * a)))
        txtcol = b['base']
    elif kind == 'darksolid':
        d.rounded_rectangle((x0 + dx, top, x1 + dx, bot), 20, fill=(*b['base'], int(240 * a)))
        txtcol = WHITE
    elif kind == 'bar':
        d.rectangle((x0 + dx, top, x0 + 10 + dx, bot), fill=(*b['accent'], A))
        d.rectangle((x0 + 10 + dx, top, x1 + dx, bot), fill=(255, 255, 255, int(20 * a)) if not light else (0, 0, 0, int(10 * a)))
    elif kind == 'line':
        d.rectangle((x0 + dx, bot + 2, x0 + dx + (x1 - x0) * eo((t - t0) / 0.7), bot + 5), fill=(*b['accent'], A))
    bx = x0 + 44 + dx
    bad = b['base'] if kind in ('solid',) else b['accent']
    d.ellipse((bx - 24, cy + dy - 24, bx + 24, cy + dy + 24), fill=(*bad, A) if kind != 'solid' else (*b['base'], A))
    numcol = b['base'] if kind != 'solid' else b['accent']
    if light and kind in ('line',): numcol = WHITE
    draw_mixed(d, str(idx + 1), 28, 600, (*numcol, A), bx, cy + dy, 'ms')
    ty = cy + dy - (len(lines) - 1) * 23
    for i, ln in enumerate(lines):
        draw_mixed(d, ln, size, 700, (*txtcol, A), x0 + 100 + (x1 - x0 - 120) / 2 + dx, ty + i * 46, th['latin'], anchor_x='c')
    base.alpha_composite(L)

def sweep(rgb, t, t0, dur, c):
    p = (t - t0) / dur
    if p < 0 or p > 1: return rgb
    x0 = -200 + p * (W + 400)
    ov = Image.new('L', (W, H), 0); d = ImageDraw.Draw(ov)
    d.polygon([(x0, 0), (x0 + 90, 0), (x0 + 90 - 330, H), (x0 - 330, H)], fill=60)
    ov = ov.filter(ImageFilter.GaussianBlur(26))
    return Image.composite(Image.new('RGB', (W, H), c), rgb, ov)

def make_frame(spec, th, fi):
    t = fi / FPS
    b = BRANDS[spec['brand']]
    light = th['light']
    txt = b['base'] if light else WHITE
    img = bg_frame(b, th, t).convert('RGBA')
    L = layer(); d = ImageDraw.Draw(L)
    chip_a = fin(t, 0.15, 0.5)
    draw_mixed(d, b['name'], 22, 600, (*(b['base'] if light else b['accent2']), int(255 * chip_a)), W / 2, 74, 'ms', tracking=5)
    d.line([(W / 2 - 40, 104), (W / 2 + 40, 104)], fill=(*b['accent'], int(255 * chip_a)), width=3)
    img.alpha_composite(L)
    ph = ss((t - 2.5) / 0.9)
    hsize = int(lerp(58, 38, ph)); hy = lerp(560, 210, ph)
    ha = fin(t, 0.45, 0.7)
    hout = fout(t, 8.0, 0.5)
    lines = wrap(spec['hook'], hsize, 700, th['latin'], 610)[:3]
    L = layer(); d = ImageDraw.Draw(L)
    dx, dy, sc = motion_off(th, t, 0.45, 0.8)
    for i, ln in enumerate(lines):
        yy = hy + (i - (len(lines) - 1) / 2) * (hsize * 1.32) + dy
        draw_mixed(d, ln, hsize, 700, (*txt, int(255 * ha * hout)), W / 2 + dx, yy, th['latin'])
    ulw = 220 * eo((t - 1.4) / 0.7)
    uly = hy + (len(lines) / 2) * (hsize * 1.32) + 14 + dy
    d.rounded_rectangle((W / 2 - ulw / 2, uly, W / 2 + ulw / 2, uly + 5), 3, fill=(*b['accent'], int(255 * ha * hout)))
    img.alpha_composite(L)
    pts = spec['points'][:3]
    for i, p in enumerate(pts):
        t0 = 2.9 + i * 1.7
        card_point(img, th, b, i, p, 470 + i * 190, t, t0, 8.0)
    if t >= 8.0:
        a = fin(t, 8.0, 0.5)
        pa = eo((t - 8.0) / 0.8)
        L = layer(); d = ImageDraw.Draw(L)
        scale = 0.9 + 0.1 * pa
        draw_mixed(d, b['title'], int(58 * scale), 700, (*(b['base'] if light else b['accent2']), int(255 * a)), W / 2, 420, 'pf')
        ulw = 360 * eo((t - 8.3) / 0.7)
        d.rounded_rectangle((W / 2 - ulw / 2, 478, W / 2 + ulw / 2, 483), 3, fill=(*b['accent'], int(255 * a)))
        cl = wrap(spec['cta'], 38, 700, th['latin'], 560)[:2]
        for i, ln in enumerate(cl):
            draw_mixed(d, ln, 38, 700, (*txt, int(255 * fin(t, 8.4, 0.5))), W / 2, 560 + i * 52 + 26 * (1 - eo((t - 8.4) / 0.6)), th['latin'])
        py = 760 + 30 * (1 - eo((t - 8.9) / 0.6))
        pill = fin(t, 8.9, 0.5)
        d.rounded_rectangle((90, py - 70, W - 90, py + 70), 70, fill=(*b['accent'], int(255 * pill)))
        pc = b['base']
        draw_mixed(d, 'কল করুন', 28, 700, (*pc, int(255 * pill)), W / 2, py - 28, 'ms')
        draw_mixed(d, b['phone'], 46, 600, (*pc, int(255 * pill)), W / 2, py + 22, 'ms')
        draw_mixed(d, b['web'], 32, 500, (*txt, int(255 * fin(t, 9.4, 0.5))), W / 2, 930, 'ms')
        if spec.get('note'):
            draw_mixed(d, spec['note'], 22, 500, (*txt, int(190 * fin(t, 9.8, 0.5))), W / 2, 1200, 'ms')
        img.alpha_composite(L)
    rgb = img.convert('RGB')
    if t >= 8.0:
        rgb = sweep(rgb, t, 8.0, 1.3, b['accent2'])
    if t < 0.4:
        k = ss(t / 0.4)
        rgb = Image.eval(rgb, lambda v: int(v * k))
    if t > DUR - 0.35:
        k = 1 - ss((t - (DUR - 0.35)) / 0.35)
        rgb = Image.eval(rgb, lambda v: int(v * k))
    return rgb

# ---------------- audio ----------------
SR = 44100
def hz(m): return 440.0 * 2 ** ((m - 69) / 12)

MOODS = [
    dict(bpm=96, ch=[([59, 62, 66], 47), ([55, 59, 62], 43), ([62, 66, 69], 50), ([57, 61, 64], 45)]),
    dict(bpm=100, ch=[([57, 60, 64], 45), ([53, 57, 60], 41), ([60, 64, 67], 48), ([55, 59, 62], 43)]),
    dict(bpm=92, ch=[([61, 64, 68], 49), ([57, 61, 64], 45), ([64, 68, 71], 52), ([59, 63, 66], 47)]),
    dict(bpm=104, ch=[([62, 65, 69], 50), ([58, 62, 65], 46), ([65, 69, 72], 53), ([60, 64, 67], 48)]),
]

def make_audio(theme_idx, path):
    N = int(SR * DUR); rng = np.random.default_rng(100 + theme_idx)
    mood = MOODS[theme_idx % 4]
    beat = 60.0 / mood['bpm']; bar = beat * 4
    dry = np.zeros(N); wet = np.zeros(N)
    def put(buf, sig, t0, g=1.0):
        i = int(t0 * SR)
        if i >= N: return
        e = min(N, i + len(sig)); buf[i:e] += sig[:e - i] * g
    def piano(m, ln, v):
        n = int(ln * SR); t = np.arange(n) / SR; f = hz(m); s = np.zeros(n)
        for k, a in enumerate([1.0, 0.5, 0.33, 0.2, 0.12, 0.07], 1):
            s += a * np.sin(2 * np.pi * f * k * t) * np.exp(-t * (1.3 + 0.9 * k))
        s *= v; ra = int(0.004 * SR); s[:ra] *= np.linspace(0, 1, ra); return s
    def pad(ms, ln, v):
        n = int(ln * SR); t = np.arange(n) / SR; s = np.zeros(n)
        for m in ms:
            f = hz(m)
            for det in (-0.004, 0.0, 0.004):
                s += np.sin(2 * np.pi * f * (1 + det) * t) * 0.18
                s += np.sin(2 * np.pi * f * 2 * (1 + det) * t) * 0.06
        e = np.minimum(1, t / 0.7) * np.minimum(1, (ln - t) / 0.5)
        return s / len(ms) * e * v
    def kick(v):
        n = int(0.4 * SR); t = np.arange(n) / SR
        f = 110 * np.exp(-t * 14) + 40
        return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 8) * v
    def hat(v):
        n = int(0.06 * SR); t = np.arange(n) / SR
        x = rng.standard_normal(n); x = np.diff(x, prepend=0)
        return x * np.exp(-t * 60) * v
    def boom(v, ln=2.6):
        n = int(ln * SR); t = np.arange(n) / SR
        f = 70 * np.exp(-t * 2.5) + 32
        s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 1.7)
        x = rng.standard_normal(n); x = np.convolve(x, np.ones(24) / 24, mode='same')
        return (s + x * np.exp(-t * 3.5) * 0.3) * v
    nb = int(np.ceil(DUR / bar))
    for bi in range(nb):
        t0 = bi * bar; tri, bass = mood['ch'][bi % 4]
        pat = [tri[0] - 12, tri[1] - 12, tri[2] - 12, tri[0], tri[2] - 12, tri[1], tri[2], tri[1]]
        for i, m in enumerate(pat):
            tt = t0 + i * beat / 2
            if tt < 8.0:
                put(wet, piano(m, 1.8, 0.5 if i % 4 == 0 else 0.38), tt, 0.55)
        if t0 + bar > 2.5 and t0 < 8.2:
            put(wet, pad(tri, bar + 0.3, 0.6), max(t0, 2.5), 0.6)
    for k in range(int(2.6 / beat), int(8.2 / beat)):
        tt = k * beat
        if 2.6 <= tt < 8.2:
            put(dry, kick(0.55 if k % 2 == 0 else 0.3), tt, 0.7)
            if tt > 5.2: put(dry, hat(0.1), tt + beat / 2, 0.5)
    put(dry, boom(1.0), 8.0, 0.8)
    tri, bass = mood['ch'][2]
    final = [tri[0] - 12, tri[0], tri[1], tri[2], tri[0] + 12]
    for m in final: put(wet, piano(m, 2.8, 0.55), 8.05, 0.55)
    put(wet, pad(tri + [tri[0] + 12], 2.9, 0.9), 8.0, 0.8)
    rl = int(1.4 * SR); tt = np.arange(rl) / SR
    ir = rng.standard_normal(rl) * np.exp(-tt * 3.2); ir[0] = 0
    nfft = 1 << int(np.ceil(np.log2(N + rl)))
    rev = np.fft.irfft(np.fft.rfft(wet, nfft) * np.fft.rfft(ir, nfft), nfft)[:N] * 0.05
    mix = dry + wet * 0.8 + rev
    fi_ = int(0.04 * SR); mix[:fi_] *= np.linspace(0, 1, fi_)
    fo = int(0.9 * SR); mix[-fo:] *= np.linspace(1, 0, fo) ** 1.4
    mix = np.tanh(mix / (np.max(np.abs(mix)) + 1e-9) * 1.3) / np.tanh(1.3) * 0.85
    st = np.stack([mix, np.roll(mix, 12)], axis=1)
    with wave.open(path, 'wb') as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((st * 32767).astype(np.int16).tobytes())

# ---------------- render ----------------
def ffmpeg_exe():
    p = shutil.which('ffmpeg')
    if p: return p
    try:
        import imageio_ffmpeg
    except ImportError:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-q', '--break-system-packages', 'imageio-ffmpeg'])
        import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()

def render(spec, theme_idx, out, workdir='/tmp'):
    ensure_fonts()
    th = THEMES[theme_idx % len(THEMES)]
    wav = os.path.join(workdir, 'bed_%d.wav' % theme_idx)
    make_audio(theme_idx, wav)
    cmd = [ffmpeg_exe(), '-y', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (W, H), '-r', str(FPS), '-i', '-',
           '-i', wav, '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k',
           '-shortest', '-movflags', '+faststart', out]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for fi in range(int(DUR * FPS)):
        p.stdin.write(make_frame(spec, th, fi).tobytes())
    p.stdin.close(); p.wait()
    return out

def stills(spec, theme_idx, times, out_png):
    ensure_fonts()
    th = THEMES[theme_idx % len(THEMES)]
    ims = [make_frame(spec, th, int(t * FPS)).resize((W // 2, H // 2)) for t in times]
    sheet = Image.new('RGB', (W // 2 * len(ims), H // 2))
    for i, im in enumerate(ims): sheet.paste(im, (i * (W // 2), 0))
    sheet.save(out_png)

if __name__ == '__main__':
    spec = json.load(open(sys.argv[1]))
    render(spec, int(sys.argv[2]), sys.argv[3])
    print('done', sys.argv[3])
