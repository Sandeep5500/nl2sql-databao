"""Generate a technical diagram for the Context Engine pipeline (no emoji)."""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch

OUT = "/data/user_data/sandeep3/personal/capstone/dce_pipeline.png"

fig, ax = plt.subplots(figsize=(18, 8))
ax.set_xlim(0, 18)
ax.set_ylim(0, 8)
ax.axis('off')
fig.patch.set_facecolor('#F7F9FC')

# ── Palette ───────────────────────────────────────────────────────────────────
BLUE   = '#2D6DB5'   # databases / files
GREEN  = '#2E8B5B'   # data artifacts
ORANGE = '#C96A1A'   # ML models
PURPLE = '#6A3FA6'   # vector store
GRAY   = '#555555'   # process steps

# ── Lane backgrounds ──────────────────────────────────────────────────────────
lanes = [
    (0.2,  0.9, 2.6,  6.8, '#EDF4FB', 'Input'),
    (3.0,  0.9, 3.8,  6.8, '#EDF7F1', 'Schema Extraction'),
    (7.0,  0.9, 4.0,  6.8, '#FEF5EE', 'LLM Enrichment'),
    (11.2, 0.9, 6.4,  6.8, '#F2EEF9', 'Chunking & Embedding'),
]
for lx, ly, lw, lh, lc, ll in lanes:
    p = FancyBboxPatch((lx, ly), lw, lh, boxstyle='round,pad=0.15',
                       fc=lc, ec='#CCCCCC', lw=1.0, zorder=0)
    ax.add_patch(p)
    ax.text(lx + lw/2, ly + lh - 0.28, ll,
            ha='center', va='top', fontsize=9.5, color='#777',
            fontstyle='italic', fontweight='bold', zorder=1)

# ── Helpers ───────────────────────────────────────────────────────────────────
def rbox(ax, cx, cy, w, h, fc, lines, zorder=4):
    """Rounded rectangle with 1-3 text lines."""
    p = FancyBboxPatch((cx - w/2, cy - h/2), w, h,
                       boxstyle='round,pad=0.12',
                       fc=fc, ec='white', lw=2.5, zorder=zorder, alpha=0.93)
    ax.add_patch(p)
    offsets = {1: [0], 2: [0.22, -0.22], 3: [0.38, 0, -0.38]}[len(lines)]
    styles  = ['bold', 'normal', 'normal']
    sizes   = [10.5, 8.5, 8]
    for line, off, sty, sz in zip(lines, offsets, styles, sizes):
        ax.text(cx, cy + off, line, ha='center', va='center',
                fontsize=sz, fontweight=sty, color='white',
                alpha=1.0 if sty == 'bold' else 0.88, zorder=zorder+1)

def cyl(ax, cx, cy, w, h, fc, lines, zorder=4):
    """Cylinder shape."""
    body = FancyBboxPatch((cx - w/2, cy - h/2), w, h,
                          boxstyle='round,pad=0.05',
                          fc=fc, ec='white', lw=2.5, zorder=zorder, alpha=0.93)
    cap = mpatches.Ellipse((cx, cy + h/2), w, 0.38,
                           fc=fc, ec='white', lw=2.5, zorder=zorder+1, alpha=1.0)
    shine = mpatches.Ellipse((cx, cy + h/2), w, 0.38,
                             fc='white', ec='none', lw=0,
                             zorder=zorder+2, alpha=0.18)
    ax.add_patch(body); ax.add_patch(cap); ax.add_patch(shine)
    offsets = {1: [0], 2: [0.2, -0.2]}[len(lines)]
    styles  = ['bold', 'normal']
    sizes   = [10.5, 8.5]
    for line, off, sty, sz in zip(lines, offsets, styles, sizes):
        ax.text(cx, cy + off, line, ha='center', va='center',
                fontsize=sz, fontweight=sty, color='white',
                alpha=1.0 if sty == 'bold' else 0.88, zorder=zorder+3)

def diam(ax, cx, cy, w, h, fc, lines, zorder=4):
    """Diamond shape for ML models."""
    dx, dy = w/2, h/2
    poly = plt.Polygon([[cx, cy+dy],[cx+dx, cy],[cx, cy-dy],[cx-dx, cy]],
                       closed=True, fc=fc, ec='white', lw=2.5,
                       zorder=zorder, alpha=0.93)
    ax.add_patch(poly)
    offsets = {1: [0], 2: [0.25, -0.22], 3: [0.42, 0.0, -0.38]}[len(lines)]
    styles  = ['bold', 'normal', 'normal']
    sizes   = [10, 8.5, 8]
    for line, off, sty, sz in zip(lines, offsets, styles, sizes):
        ax.text(cx, cy + off, line, ha='center', va='center',
                fontsize=sz, fontweight=sty, color='white',
                alpha=1.0 if sty == 'bold' else 0.88, zorder=zorder+1)

def arr(ax, x1, y1, x2, y2, label='', rad=0.0, color='#555'):
    ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle='->', color=color, lw=1.8,
                                connectionstyle=f'arc3,rad={rad}'))
    if label:
        mx, my = (x1+x2)/2, (y1+y2)/2
        ax.text(mx, my+0.22, label, ha='center', fontsize=7.5,
                color='#444', fontstyle='italic',
                bbox=dict(fc='white', ec='none', alpha=0.75, pad=1))

# ── NODES ─────────────────────────────────────────────────────────────────────

# 1. SQLite DB stack (input)
for i, off in enumerate([0.14, 0.07, 0.0]):
    zz = 4 + i
    b = FancyBboxPatch((0.65 + off, 3.55 - off), 1.7, 2.1,
                       boxstyle='round,pad=0.1',
                       fc=BLUE, ec='white', lw=1.8,
                       zorder=zz, alpha=0.68 + i * 0.12)
    ax.add_patch(b)
ax.text(1.5, 5.05, 'SQLite DBs',  ha='center', va='center',
        fontsize=10.5, fontweight='bold', color='white', zorder=8)
ax.text(1.5, 4.65, '29 databases', ha='center', va='center',
        fontsize=8.5, color='white', alpha=0.88, zorder=8)
ax.text(1.5, 4.27, 'raw schema only', ha='center', va='center',
        fontsize=8, color='white', alpha=0.78, zorder=8)
# small DB icon lines
for yy in [3.9, 3.72, 3.55]:
    ax.plot([0.85, 2.15], [yy, yy], color='white', lw=0.8, alpha=0.35, zorder=8)

# 2. Schema Extractor (process)
rbox(ax, 4.9, 5.3, 2.4, 1.0, GRAY,
     ['Schema Extractor', 'DuckDB catalog read'])

# 3. Raw YAML (data artifact)
rbox(ax, 4.9, 3.2, 2.4, 1.1, GREEN,
     ['Raw YAML', 'columns · types · PKs', '+ sample rows'])

# 4. LLM model (diamond)
diam(ax, 9.0, 5.35, 2.8, 1.6, ORANGE,
     ['Qwen3-32B-AWQ', 'LLM Enrichment', 'offline, one-time'])

# 5. Enriched YAML (data artifact)
rbox(ax, 9.0, 3.2, 2.4, 1.1, GREEN,
     ['Enriched YAML', 'schema + NL descriptions'])

# 6. Chunker (process)
rbox(ax, 12.35, 6.1, 2.2, 0.9, GRAY,
     ['Chunker', 'table + column units'])

# 7. Chunks stack
for i, off in enumerate([0.09, 0.045, 0.0]):
    b = FancyBboxPatch((11.3 + off, 4.0 - off), 2.1, 0.95,
                       boxstyle='round,pad=0.08',
                       fc=GREEN, ec='white', lw=1.5,
                       zorder=4+i, alpha=0.72 + i*0.1)
    ax.add_patch(b)
ax.text(12.35, 4.62, 'Chunks', ha='center', va='center',
        fontsize=10.5, fontweight='bold', color='white', zorder=8)
ax.text(12.35, 4.24, 'NL embeddable text + YAML', ha='center', va='center',
        fontsize=8, color='white', alpha=0.88, zorder=8)

# 8. Embedding model (diamond)
diam(ax, 15.3, 4.7, 2.6, 1.45, ORANGE,
     ['nomic-embed-text', '768-dim vectors'])

# 9. DuckDB vector index (cylinder)
cyl(ax, 15.3, 2.35, 2.2, 1.15, PURPLE,
    ['DuckDB Vector Index', 'cosine similarity search'])

# ── ARROWS ────────────────────────────────────────────────────────────────────
arr(ax, 2.35, 4.65, 3.65, 5.2,  'connects to')
arr(ax, 4.9,  4.78, 4.9,  3.77, 'serialise')
arr(ax, 6.1,  5.35, 7.57, 5.38, 'raw YAML')
arr(ax, 9.0,  4.54, 9.0,  3.77, 'append descriptions')
arr(ax, 10.2, 5.35, 11.2, 6.1,  '')
arr(ax, 10.2, 3.2,  11.22,5.8,  'enriched YAML', rad=-0.2)
arr(ax, 13.45,6.1,  13.45,4.97, '')
arr(ax, 13.45,4.0,  14.0, 4.55, 'embed')
arr(ax, 15.3, 3.96, 15.3, 2.98, 'store vectors')

# ── Legend ────────────────────────────────────────────────────────────────────
legend_items = [
    (BLUE,   'Database / Storage'),
    (GREEN,  'Data Artifact'),
    (ORANGE, 'ML Model'),
    (PURPLE, 'Vector Index'),
    (GRAY,   'Process Step'),
]
for i, (c, lbl) in enumerate(legend_items):
    bx = 0.5 + i * 3.5
    ax.add_patch(FancyBboxPatch((bx, 0.18), 0.5, 0.42,
                                boxstyle='round,pad=0.05',
                                fc=c, ec='white', lw=1.5, zorder=5))
    ax.text(bx + 0.65, 0.39, lbl, va='center', fontsize=8.5,
            color='#333', zorder=5)

plt.tight_layout(pad=0.3)
plt.savefig(OUT, dpi=160, bbox_inches='tight', facecolor=fig.get_facecolor())
print(f"Saved to {OUT}")
