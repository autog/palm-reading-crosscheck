"""Match a palmistry teacher's on-screen drawings to their transcript.
Usage: python3 video_sync.py VIDEO TRANSCRIPT.txt REGIONS.json OUTDIR [--every 2]
  TRANSCRIPT: lines "HH:MM:SS" followed by that block's text (the course's export format)
  REGIONS.json: {"Jupiter": [x0,y0,x1,y1], ...} boxes in video pixels, marked once per video
                from OUTDIR/final_grid.png (run once with an empty {} to get that file).
Outputs in OUTDIR: episodes.csv, sync.json, review.jpg, final_grid.png, regions_check.png
"""
import sys, os, re, json, csv, glob, subprocess, textwrap
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import binary_opening, binary_dilation, label

video, tpath, rpath, out = sys.argv[1:5]
EVERY = float(sys.argv[sys.argv.index('--every') + 1]) if '--every' in sys.argv else 2.0
LAG_BEFORE, LAG_AFTER = 40, 10        # speech may come up to 40 s before a stroke, 10 s after
os.makedirs(f'{out}/frames', exist_ok=True)
FB = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 18)
FR = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 16)
mmss = lambda x: f'{int(x)//60:02d}:{int(x)%60:02d}'

# 1. frames every EVERY seconds + final frame
if not glob.glob(f'{out}/frames/f_*.png'):
    subprocess.run(['ffmpeg', '-v', 'error', '-i', video, '-vf', f'fps=1/{EVERY}', f'{out}/frames/f_%04d.png'], check=True)
subprocess.run(['ffmpeg', '-v', 'error', '-y', '-sseof', '-1', '-i', video, '-update', '1', '-frames:v', '1', f'{out}/final.png'], check=True)
fs = sorted(glob.glob(f'{out}/frames/f_*.png'))
dur = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', video],
                           capture_output=True, text=True).stdout)

# gridded final frame for marking regions by hand
fin = Image.open(f'{out}/final.png').convert('RGB'); W0, H0 = fin.size
g = fin.resize((W0 * 2, H0 * 2)); d = ImageDraw.Draw(g)
for X in range(0, W0, 25):
    d.line([(X*2, 0), (X*2, H0*2)], fill=(0, 120, 255) if X % 50 == 0 else (0, 60, 120))
    if X % 50 == 0: d.text((X*2+2, 2), str(X), fill='yellow', font=FR)
for Y in range(0, H0, 25):
    d.line([(0, Y*2), (W0*2, Y*2)], fill=(0, 120, 255) if Y % 50 == 0 else (0, 60, 120))
    if Y % 50 == 0: d.text((2, Y*2+2), str(Y), fill='yellow', font=FR)
g.save(f'{out}/final_grid.png')
R = json.load(open(rpath))
if not R:
    print(f'Mark mount boxes on {out}/final_grid.png into {rpath}, then run again.'); sys.exit()
rc = fin.copy(); d = ImageDraw.Draw(rc)
for k, b in R.items(): d.rectangle(b, outline='cyan', width=2); d.text((b[0]+2, b[1]+2), k, fill='cyan', font=FR)
rc.save(f'{out}/regions_check.png')

# 2. transcript -> sentences with estimated times (linear by characters inside each stamped block)
t = open(tpath).read()
parts = re.split(r'^(\d\d:\d\d:\d\d)\s*$', t, flags=re.M)
blocks = []
for i in range(1, len(parts), 2):
    h, m, s = map(int, parts[i].split(':')); blocks.append([h*3600 + m*60 + s, ' '.join(parts[i+1].split())])
sents = []
for i, (st, txt) in enumerate(blocks):
    en = blocks[i+1][0] if i + 1 < len(blocks) else dur
    pieces = [p.strip() for p in re.split(r'(?<=[.?!])\s*', txt) if p.strip()]
    tot = sum(len(p) for p in pieces) or 1; c = 0
    for p in pieces:
        sents.append(dict(t=round(st + (en - st) * c / tot, 1), text=p, block=st)); c += len(p)

# 3. chalk strokes: near-white, low-saturation pixels; track additions AND erasures
def chalk(p):
    a = np.asarray(Image.open(p).convert('RGB')).astype(int)
    return binary_opening((a.min(2) > 200) & ((a.max(2) - a.min(2)) < 35), np.ones((2, 2)))
def region_of(x, y):
    hits = [k for k, (x0, y0, x1, y1) in R.items() if x0 <= x <= x1 and y0 <= y <= y1]
    return min(hits, key=lambda k: (R[k][2]-R[k][0]) * (R[k][3]-R[k][1])) if hits else 'unmapped'
stable = chalk(fs[0]); events = []
for i in range(1, len(fs)):
    cur = chalk(fs[i]); tt = i * EVERY
    added = cur & ~stable; erased = stable & ~cur & ~binary_dilation(cur, iterations=2)
    lab, n = label(binary_dilation(added, iterations=3))
    for j in range(1, n + 1):
        ys, xs = np.nonzero((lab == j) & added)
        if len(xs) < 40: continue           # mouse cursor and compression specks are smaller
        events.append(dict(t=tt, kind='drawn', px=len(xs), cx=int(xs.mean()), cy=int(ys.mean()),
                           box=[int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())], frame=i + 1))
    el, en = label(binary_dilation(erased, iterations=3))
    big = np.zeros_like(erased)
    for j in range(1, en + 1):
        comp = (el == j) & erased
        if comp.sum() >= 80: big |= comp     # a moving cursor leaves only small 'erasures'
    erased = big
    if erased.sum() > 0:
        ys, xs = np.nonzero(erased)
        events.append(dict(t=tt, kind='erased', px=int(erased.sum()), cx=int(xs.mean()), cy=int(ys.mean()),
                           box=[int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())], frame=i + 1))
        stable &= ~erased
    stable |= added
for e in events: e['region'] = region_of(e['cx'], e['cy'])

# 4. merge strokes into drawing episodes (same region, gaps <= 12 s)
eps = []
for e in sorted(events, key=lambda e: e['t']):
    last = next((p for p in reversed(eps) if p['region'] == e['region'] and p['kind'] == e['kind']), None)
    if last and e['t'] - last['t1'] <= 12:
        last['t1'] = e['t']; last['px'] += e['px']; last['frame1'] = e['frame']
        last['box'] = [min(last['box'][0], e['box'][0]), min(last['box'][1], e['box'][1]), max(last['box'][2], e['box'][2]), max(last['box'][3], e['box'][3])]
    else:
        eps.append(dict(kind=e['kind'], region=e['region'], t0=e['t'], t1=e['t'], px=e['px'], box=e['box'], frame0=e['frame'], frame1=e['frame']))
eps = [p for p in eps if p['px'] >= 80]

# 5. keyword match inside the lag window -> confidence
KW = {'Jupiter': ['jupiter'], 'Saturn': ['saturn', 'fate line'], 'Sun': ['sun mount', 'sun month', ' sun '],
      'Mercury': ['mercury', 'business line'], 'Outer Mars': ['mars', 'mass mount', 'mass month'],
      'Inner Mars': ['mars', 'mass mount', 'mass month'], 'Moon': ['moon'], 'Venus': ['venus'],
      'Rahu': ['rahu'], 'Ketu': ['ketu'], 'Legend': ['trident', 'flag', 'star', 'triangle', 'mole', 'island', 'mesh', 'fishnet', ' x ', 'fish', 'ring']}
def said(region, a, b):
    kws = KW.get(region, [region.lower()])
    return [s for s in sents if a <= s['t'] <= b and any(k in f" {s['text'].lower()} " for k in kws)]
for p in eps:
    win = [s for s in sents if p['t0'] - LAG_BEFORE <= s['t'] <= p['t1'] + LAG_AFTER]
    hit = said(p['region'], p['t0'] - LAG_BEFORE, p['t1'] + LAG_AFTER)
    p['speech'] = ' '.join(s['text'] for s in win)[:600]
    p['keyword_sentences'] = [s['text'] for s in hit]
    p['confidence'] = ('drawn + said' if hit else 'drawn only (check by eye)') if p['region'] != 'unmapped' else 'unmapped stroke (check)'
# mounts talked about with no drawing anywhere near (the two Mars mounts share keywords, so they are checked as one group)
said_only = []
for k in KW:
    if k in ('Legend', 'Inner Mars'): continue
    grp = ('Outer Mars', 'Inner Mars') if 'Mars' in k else (k,)
    for s in sents:
        if any(w in f" {s['text'].lower()} " for w in KW[k]) and not any(p['region'] in grp and p['t0'] - LAG_AFTER <= s['t'] + LAG_BEFORE and s['t'] - LAG_BEFORE <= p['t1'] + LAG_AFTER for p in eps):
            said_only.append(dict(t=s['t'], region='Mars (either)' if 'Mars' in k else k, text=s['text'], confidence='said only'))

json.dump(dict(episodes=eps, said_only=said_only, sentences=sents), open(f'{out}/sync.json', 'w'), indent=1)
with open(f'{out}/episodes.csv', 'w', newline='') as f:
    w = csv.writer(f); w.writerow(['start', 'end', 'kind', 'region', 'confidence', 'keyword sentences', 'speech in window', 'frames'])
    for p in eps: w.writerow([mmss(p['t0']), mmss(p['t1']), p['kind'], p['region'], p['confidence'], ' | '.join(p['keyword_sentences']), p['speech'], f"{p['frame0']}-{p['frame1']}"])
    for s in said_only: w.writerow([mmss(s['t']), '', 'speech', s['region'], 'said only', s['text'], '', ''])

# 6. review sheet: each episode's new strokes in red (erasures in blue) on its last frame, with the matched speech
rows = []
for p in eps:
    a = np.asarray(Image.open(fs[p['frame1'] - 1]).convert('RGB')).copy()
    m = np.zeros(a.shape[:2], bool); x0, y0, x1, y1 = p['box']
    before = chalk(fs[max(p['frame0'] - 2, 0)]); after = chalk(fs[p['frame1'] - 1])
    m[y0:y1+1, x0:x1+1] = (after & ~before)[y0:y1+1, x0:x1+1] if p['kind'] == 'drawn' else (before & ~after)[y0:y1+1, x0:x1+1]
    a[binary_dilation(m, iterations=1)] = [230, 40, 40] if p['kind'] == 'drawn' else [40, 120, 230]
    tile = Image.fromarray(a).resize((440, int(440 * a.shape[0] / a.shape[1])))
    row = Image.new('RGB', (1100, max(tile.height, 230) + 10), 'white'); row.paste(tile, (5, 5)); d = ImageDraw.Draw(row)
    col = {'drawn + said': '#1A9850', 'drawn only (check by eye)': '#d98c00'}.get(p['confidence'], '#D73027')
    d.text((460, 8), f"{mmss(p['t0'])}–{mmss(p['t1'])}  {p['kind']}  ·  {p['region']}", font=FB, fill='black')
    d.text((460, 34), p['confidence'], font=FB, fill=col)
    y = 64
    for line in textwrap.wrap(' | '.join(p['keyword_sentences'])[:400] or p['speech'][:400], 70)[:9]:
        d.text((460, y), line, font=FR, fill='black'); y += 19
    rows.append(row)
if rows:
    sheet = Image.new('RGB', (1100, sum(r.height for r in rows)), 'white'); y = 0
    for r in rows: sheet.paste(r, (0, y)); y += r.height
    sheet.save(f'{out}/review.jpg', quality=85)
print(f'{len(eps)} episodes ({sum(p["confidence"]=="drawn + said" for p in eps)} drawn+said, '
      f'{sum(p["confidence"].startswith("drawn only") for p in eps)} drawn only, '
      f'{sum(p["region"]=="unmapped" for p in eps)} unmapped, {sum(p["kind"]=="erased" for p in eps)} erasures); '
      f'{len(said_only)} said-only sentences')
