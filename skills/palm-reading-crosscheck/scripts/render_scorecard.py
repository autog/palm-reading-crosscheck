"""Render a life-area scorecard image from rated palm features.
Usage: python3 render_scorecard.py SCORECARD.json OUT.jpg

SCORECARD.json:
{
  "title": "Palm scorecard", "person": "Right hand (dominant)", "date": "25 Nov 2026",
  "tradition": "General conventions",
  "categories": [
    {"name": "Career & Success",
     "features": [{"feature": "Fate line", "rating": "Good", "why": "Rises from the wrist, even depth"}, ...]},
    ...
  ],
  "summary": "One or two sentences in plain words."
}
Ratings: Excellent=4, Good=3, Average=2, Bad=1. A rating of "" or "Needs photo" is listed but not scored.
Each category's score is the mean of its scored features, so the image always matches the sheet.
"""
import sys, json, math, textwrap
from PIL import Image, ImageDraw, ImageFont

DISCLAIMER = ("Disclaimer: This reading is for experimentation only. It is a preliminary reading and should "
              "not be taken seriously. It is not professional, medical, financial or life advice, so please "
              "don't make decisions based on it.")
PTS = {'Excellent': 4, 'Good': 3, 'Average': 2, 'Bad': 1}
COL = {'Excellent': (26, 152, 80), 'Good': (145, 207, 96), 'Average': (253, 184, 60), 'Bad': (215, 48, 39),
       None: (120, 124, 135)}
BG, CARD, INK, MUTED, LINE = (18, 20, 28), (30, 33, 45), (240, 240, 245), (165, 170, 185), (55, 60, 78)
FD = '/usr/share/fonts/truetype/dejavu/'
def F(size, bold=False): return ImageFont.truetype(FD + ('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'), size)

def band(s):
    if s is None: return None
    return 'Excellent' if s >= 3.5 else 'Good' if s >= 2.75 else 'Average' if s >= 1.75 else 'Bad'

def wrap(d, text, font, width):
    words, lines, cur = text.split(), [], ''
    for w in words:
        t = (cur + ' ' + w).strip()
        if d.textlength(t, font=font) <= width: cur = t
        else: lines.append(cur); cur = w
    if cur: lines.append(cur)
    return lines

spec = json.load(open(sys.argv[1])); out = sys.argv[2]
cats = spec['categories']
for c in cats:
    sc = [PTS[f['rating']] for f in c['features'] if f.get('rating') in PTS]
    c['score'] = round(sum(sc) / len(sc), 2) if sc else None
    c['n_scored'], c['n_total'] = len(sc), len(c['features'])
scored = [c['score'] for c in cats if c['score'] is not None]
overall = round(sum(scored) / len(scored), 2) if scored else None

W, PAD, GAP = 2400, 70, 36
COLS = 2; CW = (W - 2 * PAD - GAP * (COLS - 1)) // COLS
tmp = ImageDraw.Draw(Image.new('RGB', (10, 10)))
fT, fH, fB, fS, fX = F(64, True), F(40, True), F(30), F(26), F(24)

# measure card heights
def card_h(c):
    h = 40 + 56 + 30 + 40          # name, score row, bar, gap
    for f in c['features']:
        h += 38 * len(wrap(tmp, f"{f['feature']} — {f.get('rating') or 'Not rated'}: {f['why']}", fB, CW - 160)) + 14
    return h + 30
rows = [cats[i:i + COLS] for i in range(0, len(cats), COLS)]
row_h = [max(card_h(c) for c in r) for r in rows]
HEAD = 760
sum_lines = wrap(tmp, spec.get('summary', ''), fB, W - 2 * PAD - 60)
dis_lines = wrap(tmp, DISCLAIMER, F(30, True), W - 2 * PAD - 80)
H = HEAD + sum(row_h) + GAP * len(rows) + (60 + 40 * len(sum_lines) if sum_lines else 0) + 110 + 44 * len(dis_lines) + 120
im = Image.new('RGB', (W, H), BG); d = ImageDraw.Draw(im)

# header
d.text((PAD, PAD), spec.get('title', 'Palm scorecard'), font=fT, fill=INK)
d.text((PAD, PAD + 84), f"{spec.get('person', '')}  ·  {spec.get('date', '')}  ·  read by: {spec.get('tradition', '')}",
       font=fS, fill=MUTED)
# overall gauge
cx, cy, R = PAD + 230, PAD + 360, 170
d.arc([cx - R, cy - R, cx + R, cy + R], 135, 405, fill=LINE, width=34)
if overall:
    d.arc([cx - R, cy - R, cx + R, cy + R], 135, 135 + 270 * (overall - 1) / 3, fill=COL[band(overall)], width=34)
    t = f"{overall:.1f}"; d.text((cx - d.textlength(t, font=F(96, True)) / 2, cy - 70), t, font=F(96, True), fill=INK)
    t = f"out of 4 · {band(overall)}"; d.text((cx - d.textlength(t, font=fS) / 2, cy + 40), t, font=fS, fill=COL[band(overall)])
t = 'Overall'; d.text((cx - d.textlength(t, font=fH) / 2, cy + R + 10), t, font=fH, fill=INK)
# radar of categories
rx, ry, rr = W - PAD - 560, PAD + 370, 230
n = len(cats)
ang = [-math.pi / 2 + 2 * math.pi * k / n for k in range(n)]
for lvl in (1, 2, 3, 4):
    pts = [(rx + rr * lvl / 4 * math.cos(a), ry + rr * lvl / 4 * math.sin(a)) for a in ang]
    d.polygon(pts, outline=LINE)
for k, a in enumerate(ang):
    d.line([(rx, ry), (rx + rr * math.cos(a), ry + rr * math.sin(a))], fill=LINE)
    lab = cats[k]['name']; lx, ly = rx + (rr + 40) * math.cos(a), ry + (rr + 40) * math.sin(a)
    tw = d.textlength(lab, font=fX)
    lx = lx - tw / 2 if abs(math.cos(a)) < 0.3 else (lx if math.cos(a) > 0 else lx - tw)
    d.text((lx, ly - 14), lab, font=fX, fill=MUTED)
poly = [(rx + rr * (c['score'] or 0) / 4 * math.cos(a), ry + rr * (c['score'] or 0) / 4 * math.sin(a)) for c, a in zip(cats, ang)]
ov = Image.new('RGBA', im.size, (0, 0, 0, 0)); od = ImageDraw.Draw(ov)
od.polygon(poly, fill=(120, 170, 255, 70), outline=(140, 185, 255, 255))
im.paste(Image.alpha_composite(im.convert('RGBA'), ov).convert('RGB')); d = ImageDraw.Draw(im)
for (px, py), c in zip(poly, cats):
    d.ellipse([px - 9, py - 9, px + 9, py + 9], fill=COL[band(c['score'])])
# colour key under the title
kx, ky = PAD + 520, PAD + 200
for k, (name, p) in enumerate(PTS.items()):
    y = ky + k * 52
    d.rounded_rectangle([kx, y, kx + 34, y + 34], 8, fill=COL[name])
    d.text((kx + 50, y), f"{name} ({p})", font=fB, fill=INK)
d.text((kx, ky + 4 * 52 + 10), "Grey = needs a better photo,", font=fX, fill=MUTED)
d.text((kx, ky + 4 * 52 + 40), "touch or transcript (not scored)", font=fX, fill=MUTED)

# category cards
y = HEAD
for r, h in zip(rows, row_h):
    for j, c in enumerate(r):
        x = PAD + j * (CW + GAP); b = band(c['score'])
        d.rounded_rectangle([x, y, x + CW, y + h], 28, fill=CARD)
        d.rounded_rectangle([x, y, x + 14, y + h], 7, fill=COL[b])
        d.text((x + 50, y + 34), c['name'], font=fH, fill=INK)
        st = f"{c['score']:.1f} / 4" if c['score'] is not None else "—"
        d.text((x + CW - 50 - d.textlength(st, font=fH), y + 34), st, font=fH, fill=COL[b])
        chip = b or 'Not scored'; cw_ = d.textlength(chip, font=fS) + 36
        d.rounded_rectangle([x + 50, y + 96, x + 50 + cw_, y + 136], 20, fill=COL[b])
        d.text((x + 68, y + 101), chip, font=fS, fill=(20, 20, 20))
        cnt = f"{c['n_scored']} of {c['n_total']} features scored"
        d.text((x + CW - 50 - d.textlength(cnt, font=fX), y + 104), cnt, font=fX, fill=MUTED)
        bx0, bx1, by = x + 50, x + CW - 50, y + 160
        d.rounded_rectangle([bx0, by, bx1, by + 18], 9, fill=LINE)
        if c['score']: d.rounded_rectangle([bx0, by, bx0 + (bx1 - bx0) * c['score'] / 4, by + 18], 9, fill=COL[b])
        fy = by + 50
        for f in c['features']:
            rt = f.get('rating') if f.get('rating') in PTS else None
            d.ellipse([x + 52, fy + 8, x + 74, fy + 30], fill=COL[rt])
            lines = wrap(d, f"{f['feature']} — {rt or 'Not rated'}: {f['why']}", fB, CW - 160)
            head = f"{f['feature']} — {rt or 'Not rated'}:"
            for k, ln in enumerate(lines):
                if k == 0 and ln.startswith(head):
                    d.text((x + 92, fy), head, font=F(30, True), fill=INK)
                    d.text((x + 92 + d.textlength(head + ' ', font=F(30, True)), fy), ln[len(head):].strip(), font=fB, fill=MUTED)
                else:
                    d.text((x + 92, fy), ln, font=fB, fill=MUTED)
                fy += 38
            fy += 14
    y += h + GAP

# summary
if sum_lines:
    d.text((PAD, y + 10), 'In short', font=fH, fill=INK); y += 64
    for ln in sum_lines: d.text((PAD, y), ln, font=fB, fill=MUTED); y += 40
    y += 20
# disclaimer box
dh = 44 * len(dis_lines) + 50
d.rounded_rectangle([PAD, y + 20, W - PAD, y + 20 + dh], 20, outline=(253, 184, 60), width=4, fill=(45, 38, 20))
for k, ln in enumerate(dis_lines): d.text((PAD + 40, y + 45 + 44 * k), ln, font=F(30, True), fill=(253, 214, 140))
y += dh + 50
d.text((PAD, y), "Category score = average of its rated features (Excellent 4 · Good 3 · Average 2 · Bad 1). "
       "Palmistry is a tradition, not evidence.", font=fX, fill=MUTED)
im.save(out, quality=90)
print(json.dumps({c['name']: c['score'] for c in cats} | {'overall': overall}, indent=1))
