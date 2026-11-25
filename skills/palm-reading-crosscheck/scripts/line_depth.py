"""Measure how deep (dark + wide) each palm line is along its length.
Usage: python3 line_depth.py IMAGE LINES.json OUTDIR
LINES.json: {"life": {"pts": [[x,y],...], "ages": [10, 80]}, ...}  (pts in image pixels,
 ordered from the line's start; "ages" = age at first and last point on the tradition's age scale, optional)
"""
import sys, json, math, os, csv, collections
import numpy as np
from PIL import Image, ImageOps, ImageDraw, ImageFont
from scipy.ndimage import gaussian_filter, map_coordinates, median_filter
from scipy.spatial import cKDTree

img_path, lines_path, out = sys.argv[1:4]
os.makedirs(out, exist_ok=True)
im = ImageOps.exif_transpose(Image.open(img_path)).convert('RGB')
g = np.asarray(ImageOps.grayscale(im)).astype(float)
bg = gaussian_filter(g, 15)                       # local skin brightness
dark = np.clip((bg - gaussian_filter(g, 1.0)) / np.maximum(bg, 1), 0, None)  # relative darkness
dark_s = gaussian_filter(dark, 1.5)
L = json.load(open(lines_path))
H = 18                                            # half-width of the cross-section, px
STEP = 1                                          # px between samples along the line
K = 3                                             # smoothing scale, in samples per 3 px

def resample(pts):
    pts = np.array(pts, float); seg = np.hypot(*np.diff(pts, axis=0).T)
    s = np.concatenate([[0], np.cumsum(seg)]); n = max(int(s[-1] / STEP), 2)
    t = np.linspace(0, s[-1], n)
    return np.c_[np.interp(t, s, pts[:, 0]), np.interp(t, s, pts[:, 1])], t / s[-1]

def normals(P):
    d = np.gradient(P, axis=0); d /= np.linalg.norm(d, axis=1, keepdims=True) + 1e-9
    return np.c_[-d[:, 1], d[:, 0]]

def snap(P, R=10, iters=2):
    # move each sample onto the darkest crease within +-R px across the line, then smooth the shift
    for _ in range(iters):
        nrm = normals(P); off = np.arange(-R, R + 1)
        X = P[:, 0, None] + nrm[:, 0, None] * off; Y = P[:, 1, None] + nrm[:, 1, None] * off
        best = off[map_coordinates(dark_s, [Y, X], order=1).argmax(1)].astype(float)
        raw_best = best.copy(); best = median_filter(best, size=15 * K, mode='nearest'); best = gaussian_filter(best, 6 * K)
        P = P + nrm * best[:, None]
    return P, best, raw_best

rows, strips, warn, paths = [], {}, {}, {}
for name, spec in L.items():
    P, frac = resample(spec['pts'])
    P, last, raw = snap(P)
    # confidence: how often the darkest point across the line agrees with the smoothed path
    agree = float((np.abs(raw - last) <= 3).mean())
    if agree < 0.6: warn[name] = (f'only {agree:.0%} of cross-sections have their darkest point on the path: '
                                  'no single clear crease here (faint line, or the trace is off). Check zoom tiles and re-trace.')
    nrm = normals(P); paths[name] = P
    off = np.arange(-H, H + 1)
    X = P[:, 0, None] + nrm[:, 0, None] * off; Y = P[:, 1, None] + nrm[:, 1, None] * off
    prof = map_coordinates(dark, [Y, X], order=1)          # (n, 2H+1) cross-sections
    strips[name] = map_coordinates(g, [Y, X], order=1)
    # depth = peak darkness near the trace (allows +-8 px trace error); width = FWHM in px
    core = prof[:, H - 8:H + 9]; k = core.argmax(1) + H - 8
    depth = prof[np.arange(len(k)), k]
    width = np.array([(p >= dp / 2).sum() if dp > 0 else 0 for p, dp in zip(prof, depth)])
    # island hint: two separate dark strands across the section
    def two_strands(p, dp):
        c = p[H - 10:H + 11]; pk = [i for i in range(1, len(c) - 1) if c[i] >= c[i-1] and c[i] > c[i+1] and c[i] > 0.5 * dp]
        for a in pk:
            for b in pk:
                if b - a >= 5 and c[a:b+1].min() < 0.5 * min(c[a], c[b]): return True
        return False
    isl = np.array([two_strands(p, dp) for p, dp in zip(prof, depth)])
    # keep only runs that persist along the line (a real island does)
    island = np.zeros_like(isl); run = 0
    for i, v in enumerate(isl):
        run = run + 1 if v else 0
        if run >= 4 * K: island[i - run + 1:i + 1] = True
    a0, a1 = spec.get('ages', [None, None])
    for i in range(len(P)):
        age = None if a0 is None else round(a0 + (a1 - a0) * frac[i], 1)
        rows.append(dict(line=name, i=i, x=round(P[i, 0]), y=round(P[i, 1]), frac=round(frac[i], 3),
                         age=age, depth=float(depth[i]), width=int(width[i]), island=bool(island[i])))

# mask samples that sit on a crossing with another traced line (crossings look falsely deep)
# and the first/last 4% of each line (thumb-web and wrist folds look falsely deep)
trees = {n: cKDTree(p) for n, p in paths.items()}
for r in rows:
    others = [t.query([r['x'], r['y']])[0] for n, t in trees.items() if n != r['line']]
    r['crossing'] = bool(others and min(others) < 9)
    r['masked'] = r['crossing'] or r['frac'] < 0.04 or r['frac'] > 0.96

# normalise depth against the palm's own major lines so 'deep' and 'faint' are relative
by = collections.defaultdict(list)
for r in rows: by[r['line']].append(r)
MAJOR = ('life', 'heart', 'mind', 'head', 'fate')
ref = np.median([r['depth'] for r in rows if r['line'] in MAJOR and not r['masked']] or [r['depth'] for r in rows])
summary = {}
for name, rs in by.items():
    raw = np.array([r['depth'] for r in rs], float); m = np.array([r['masked'] for r in rs])
    if (~m).sum() > 2: raw[m] = np.interp(np.flatnonzero(m), np.flatnonzero(~m), raw[~m])  # fill masked from neighbours
    dep = gaussian_filter(raw, 2 * K) / ref
    wid = gaussian_filter(np.array([r['width'] for r in rs], float), 2 * K)
    cls = np.where(dep < 0.3, 'gap?', np.where(dep < 0.65, 'faint', np.where(dep > 1.5, 'deep', 'normal')))
    for r, dv, c in zip(rs, dep, cls): r['rel_depth'] = round(float(dv), 2); r['class'] = str(c)
    # collapse into segments of the same class; very short ones merge into the previous segment
    segs, cur = [], None
    for r in rs:
        if cur and cur['class'] == r['class']: cur['end'] = r
        else: cur = {'class': r['class'], 'start': r, 'end': r}; segs.append(cur)
    merged = []
    for s in segs:
        n = s['end']['i'] - s['start']['i'] + 1
        if merged and n < 4 * K: merged[-1]['end'] = s['end']
        else: merged.append(s)
    thirds = np.array_split(dep, 3)
    summary[name] = dict(
        mean_rel_depth=round(float(dep.mean()), 2), median_width_px=float(np.median(wid)),
        thirds_rel_depth=[round(float(t.mean()), 2) for t in thirds],   # start / middle / end
        trend=('thinning' if thirds[2].mean() < 0.7 * thirds[0].mean() else
               'thickening' if thirds[2].mean() > 1.4 * thirds[0].mean() else 'even'),
        crossings_at=[(r['age'] if r['age'] is not None else r['frac']) for k, r in enumerate(rs) if r['crossing'] and (k == 0 or not rs[k-1]['crossing'])],
        island_runs=[(r['age'] if r['age'] is not None else r['frac']) for k, r in enumerate(rs) if r['island'] and (k == 0 or not rs[k-1]['island'])],
        warning=warn.get(name),
        segments=[dict(cls=s['class'], from_age=s['start']['age'], to_age=s['end']['age'],
                       from_frac=s['start']['frac'], to_frac=s['end']['frac']) for s in merged])
json.dump(summary, open(f'{out}/summary.json', 'w'), indent=1)
with open(f'{out}/samples.csv', 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
print(json.dumps(summary, indent=1))

# each line straightened into a zoomed strip, with its depth graph and ages underneath
F = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 18)
COL = {'deep': (215, 48, 39), 'normal': (26, 152, 80), 'faint': (253, 184, 60), 'gap?': (120, 120, 120)}
panels = []
for name, rs in by.items():
    s = strips[name].T; s = (s - s.min()) / (np.ptp(s) + 1e-9) * 255
    Z = 2; st = Image.fromarray(s.astype(np.uint8)).resize((s.shape[1] * Z, s.shape[0] * Z)).convert('RGB')
    W = st.width; gh = 120; p = Image.new('RGB', (W, st.height + gh + 40), 'white'); p.paste(st, (0, 30))
    d = ImageDraw.Draw(p); d.text((5, 5), f"{name}  (start -> end; ages under the graph)", font=F, fill='black')
    cy = 30 + H * Z; d.line([(0, cy), (8, cy)], fill='red', width=2); d.line([(W - 8, cy), (W, cy)], fill='red', width=2)
    base = st.height + 30 + gh
    for j, r in enumerate(rs):
        x = j * Z; h = min(r['rel_depth'], 2.5) / 2.5 * (gh - 10)
        d.rectangle([x, base - h, x + Z - 1, base], fill=COL[r['class']])
    d.line([(0, base - 1.0 / 2.5 * (gh - 10)), (W, base - 1.0 / 2.5 * (gh - 10))], fill='black')  # 1.0 = palm reference
    for j, r in enumerate(rs):
        if r['age'] is not None and (j % max(1, len(rs) // 8) == 0):
            d.text((j * Z, base + 2), str(int(r['age'])), font=F, fill='black')
    panels.append(p)
Wm = max(p.width for p in panels); Ht = sum(p.height + 20 for p in panels)
sheet = Image.new('RGB', (Wm, Ht), 'white'); y = 0
for p in panels: sheet.paste(p, (0, y)); y += p.height + 20
sheet.save(f'{out}/line_strips.png')

# 3x colour close-ups tiled along each line: trace drawn just below the crease, coloured by class,
# labelled with age (or fraction), class and pixel position for re-tracing
Fz = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 20)
ZC, R = 3, 60
for name, rs in by.items():
    tiles = []
    for j in range(0, len(rs), 110):
        c = rs[j]; box = (c['x'] - R, c['y'] - R, c['x'] + R, c['y'] + R)
        t = im.crop(box).resize((2 * R * ZC, 2 * R * ZC), Image.LANCZOS); dt = ImageDraw.Draw(t)
        for a, b in zip(rs, rs[1:]):
            if box[0] <= a['x'] < box[2] and box[1] <= a['y'] < box[3]:
                dt.line([((a['x'] - box[0]) * ZC, (a['y'] - box[1]) * ZC + 14), ((b['x'] - box[0]) * ZC, (b['y'] - box[1]) * ZC + 14)],
                        fill=COL[a['class']], width=3)
        lab = f"{name} @ {c['age'] if c['age'] is not None else c['frac']}  {c['class']}  ({c['x']},{c['y']})"
        dt.rectangle([0, 0, dt.textlength(lab, font=Fz) + 10, 28], fill='black'); dt.text((5, 3), lab, font=Fz, fill='white')
        tiles.append(t)
    cols = 4; tw = 2 * R * ZC; rows_n = math.ceil(len(tiles) / cols)
    sheet = Image.new('RGB', (cols * tw + (cols - 1) * 6, rows_n * tw + (rows_n - 1) * 6), 'white')
    for k, t in enumerate(tiles): sheet.paste(t, ((k % cols) * (tw + 6), (k // cols) * (tw + 6)))
    sheet.save(f'{out}/zoom_{name}.png')
