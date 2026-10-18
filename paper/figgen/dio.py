"""Draw a figure once, write it twice: an editable draw.io diagram (.drawio) and a PDF for LaTeX.

Coordinates are draw.io units with y pointing down; one unit is one PostScript point in the PDF, so a
figure drawn 241 units wide is exactly one ACM column wide. Every element becomes a native draw.io
shape (rectangle, ellipse, text, edge with waypoints), so the .drawio file can be edited freely and
exported again with File > Export as > PDF ("Crop" ticked) to replace the generated PDF.

Text may contain math in $...$ using a small TeX subset (Greek letters, _{} and ^{}, \\le, \\to, \\cap,
\\subseteq, \\Sigma, \\mathrm{}). Matplotlib renders it with mathtext; the draw.io copy gets the same
text as HTML (<i>, <sub>, <sup>, Unicode symbols).
"""
import html
import re

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Ellipse, FancyBboxPatch, Polygon, Rectangle  # noqa: E402

FONT = 'Nimbus Sans'            # metric clone of Helvetica, the draw.io default face
plt.rcParams.update({
    'pdf.fonttype': 42, 'font.family': 'sans-serif', 'font.sans-serif': [FONT, 'Liberation Sans', 'DejaVu Sans'],
    'mathtext.fontset': 'custom', 'mathtext.rm': FONT, 'mathtext.it': FONT + ':italic',
    'mathtext.bf': FONT + ':bold', 'mathtext.sf': FONT, 'axes.unicode_minus': False,
})

SYM = {r'\beta': 'β', r'\gamma': 'γ', r'\lambda': 'λ', r'\sigma': 'σ', r'\tau': 'τ', r'\rho': 'ρ',
       r'\Sigma': 'Σ', r'\sum': 'Σ', r'\le': '≤', r'\leq': '≤', r'\ge': '≥', r'\geq': '≥', r'\to': '→',
       r'\rightarrow': '→', r'\leftarrow': '←', r'\cap': '∩', r'\cup': '∪', r'\subseteq': '⊆', r'\times': '×',
       r'\cdot': '·', r'\in': '∈', r'\emptyset': '∅', r'\infty': '∞', r'\approx': '≈', r'\,': ' ',
       r'\;': ' ', r'\ ': ' ', r'\bot': '⊥', r'\ldots': '…', r'\{': '{', r'\}': '}', r'\%': '%'}


def _math_to_html(m):
    """TeX subset -> HTML, the counterpart of what mathtext draws."""
    out, i = [], 0

    def group(i):
        if i < len(m) and m[i] == '{':
            depth, j = 1, i + 1
            while depth:
                depth += {'{': 1, '}': -1}.get(m[j], 0)
                j += 1
            return m[i + 1:j - 1], j
        if m[i] == '\\':
            j = i + 1
            while j < len(m) and m[j].isalpha():
                j += 1
            return m[i:j], j
        return m[i], i + 1

    while i < len(m):
        c = m[i]
        if c in '_^':
            g, i = group(i + 1)
            tag = 'sub' if c == '_' else 'sup'
            out.append(f'<{tag}>{_math_to_html(g)}</{tag}>')
        elif c == '\\':
            j = i + 1
            while j < len(m) and m[j].isalpha():
                j += 1
            if j == i + 1:
                j += 1
            cmd = m[i:j]
            if cmd in (r'\mathrm', r'\text', r'\mathsf'):
                g, i = group(j)
                out.append(html.escape(g))
                continue
            if cmd == r'\mathbf':
                g, i = group(j)
                out.append(f'<b>{_math_to_html(g)}</b>')
                continue
            out.append(SYM.get(cmd, cmd.lstrip('\\')))
            i = j
        elif c in '{}':
            i += 1
        elif c.isalpha():
            j = i
            while j < len(m) and m[j].isalpha():
                j += 1
            out.append(f'<i>{m[i:j]}</i>')
            i = j
        else:
            out.append(html.escape(c))
            i += 1
    return ''.join(out)


def to_html(s):
    parts = re.split(r'(\$[^$]*\$)', s)
    h = ''.join(_math_to_html(p[1:-1]) if p.startswith('$') and len(p) > 1 else html.escape(p) for p in parts)
    return h.replace('\n', '<br>')


FS_SCALE = 1.2   # all figure text 25% larger than the original layout

class Fig:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.fig = plt.figure(figsize=(w / 72, h / 72), dpi=72)
        self.ax = self.fig.add_axes([0, 0, 1, 1])
        self.ax.set_xlim(0, w)
        self.ax.set_ylim(h, 0)
        self.ax.axis('off')
        self.cells = []
        self.z = 0
        self._texts = []

    def _id(self):
        self.z += 1
        return f'c{self.z}'

    def _zo(self):
        return 1 + self.z * 1e-3

    # ------------------------------------------------------------------ shapes
    def rect(self, x, y, w, h, fill='none', stroke='#000000', sw=0.8, r=0, dash=None, label=None, fs=8,
             color='#000000', bold=False, align='center', valign='middle', spacing=2):
        fs = fs * FS_SCALE
        z = self._zo()
        if r > 0:
            p = FancyBboxPatch((x, y), w, h, boxstyle=f'round,pad=0,rounding_size={r}', zorder=z)
        else:
            p = Rectangle((x, y), w, h, zorder=z)
        p.set_facecolor(fill if fill != 'none' else 'none')
        p.set_edgecolor(stroke if stroke != 'none' else 'none')
        p.set_linewidth(sw if stroke != 'none' else 0)
        if dash:
            p.set_linestyle((0, dash))
        self.ax.add_patch(p)
        style = (f'rounded={1 if r > 0 else 0};' + (f'absoluteArcSize=1;arcSize={2 * r};' if r > 0 else '') +
                 f'whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};strokeWidth={sw};'
                 f'fontFamily=Helvetica;fontSize={fs};fontColor={color};align={align};verticalAlign={valign};'
                 f'spacing={spacing};' + ('fontStyle=1;' if bold else '') +
                 (f'dashed=1;dashPattern={" ".join(str(v) for v in dash)};' if dash else ''))
        self.cells.append(('v', self._id(), to_html(label) if label else '', style, (x, y, w, h)))
        if label:
            tx = {'center': x + w / 2, 'left': x + spacing, 'right': x + w - spacing}[align]
            ty = {'middle': y + h / 2, 'top': y + spacing, 'bottom': y + h - spacing}[valign]
            self._mpl_text(tx, ty, label, fs, align, valign, color, bold, 0, z + 5e-4)

    def ellipse(self, cx, cy, rx, ry, fill='none', stroke='#000000', sw=0.8, label=None, fs=8, color='#000000',
                bold=False, dash=None):
        fs = fs * FS_SCALE
        z = self._zo()
        p = Ellipse((cx, cy), 2 * rx, 2 * ry, zorder=z, facecolor=fill if fill != 'none' else 'none',
                    edgecolor=stroke if stroke != 'none' else 'none', linewidth=sw if stroke != 'none' else 0)
        if dash:
            p.set_linestyle((0, dash))
        self.ax.add_patch(p)
        style = (f'ellipse;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};strokeWidth={sw};'
                 f'fontFamily=Helvetica;fontSize={fs};fontColor={color};spacing=0;' + ('fontStyle=1;' if bold else '') +
                 (f'dashed=1;dashPattern={" ".join(str(v) for v in dash)};' if dash else ''))
        self.cells.append(('v', self._id(), to_html(label) if label else '', style, (cx - rx, cy - ry, 2 * rx, 2 * ry)))
        if label:
            self._mpl_text(cx, cy, label, fs, 'center', 'middle', color, bold, 0, z + 5e-4)

    def marker(self, x, y, shape='o', size=4, fill='#000000', stroke='#ffffff', sw=0.5):
        """A data marker of diameter `size` centred on (x, y)."""
        z = self._zo()
        s = size / 2
        if shape == 'o':
            self.ax.add_patch(Ellipse((x, y), size, size, facecolor=fill, edgecolor=stroke, linewidth=sw, zorder=z))
            st = 'ellipse;'
        elif shape == 's':
            self.ax.add_patch(Rectangle((x - s, y - s), size, size, facecolor=fill, edgecolor=stroke, linewidth=sw, zorder=z))
            st = ''
        elif shape == '^':
            self.ax.add_patch(Polygon([(x - s, y + s), (x + s, y + s), (x, y - s)], facecolor=fill, edgecolor=stroke,
                                      linewidth=sw, zorder=z))
            st = 'triangle;direction=north;'
        elif shape == 'D':
            self.ax.add_patch(Polygon([(x - s, y), (x, y - s), (x + s, y), (x, y + s)], facecolor=fill, edgecolor=stroke,
                                      linewidth=sw, zorder=z))
            st = 'rhombus;'
        else:
            raise ValueError(shape)
        self.cells.append(('v', self._id(), '', st + f'html=1;fillColor={fill};strokeColor={stroke};strokeWidth={sw};',
                           (x - s, y - s, size, size)))

    def line(self, pts, color='#000000', sw=0.8, dash=None, arrow=None, head=5, cap='butt'):
        """Polyline through pts; arrow in {None, 'end', 'start', 'both'}; head = arrowhead length."""
        z = self._zo()
        pts = [(float(a), float(b)) for a, b in pts]
        xs, ys = zip(*pts)
        ln, = self.ax.plot(xs, ys, color=color, lw=sw, zorder=z, solid_capstyle=cap, dash_capstyle=cap,
                           solid_joinstyle='miter')
        if dash:
            ln.set_linestyle((0, dash))
        for end in (['end'] if arrow == 'end' else ['start'] if arrow == 'start' else ['start', 'end'] if arrow == 'both' else []):
            (x1, y1), (x0, y0) = (pts[-1], pts[-2]) if end == 'end' else (pts[0], pts[1])
            dx, dy = x1 - x0, y1 - y0
            L = max((dx * dx + dy * dy) ** 0.5, 1e-9)
            ux, uy = dx / L, dy / L
            bx, by = x1 - ux * head, y1 - uy * head
            hw = head * 0.4
            self.ax.add_patch(Polygon([(x1, y1), (bx - uy * hw, by + ux * hw), (bx + uy * hw, by - ux * hw)],
                                      facecolor=color, edgecolor=color, linewidth=0.3, zorder=z))
        ea = 'block' if arrow in ('end', 'both') else 'none'
        sa = 'block' if arrow in ('start', 'both') else 'none'
        style = (f'edgeStyle=none;html=1;rounded=0;endArrow={ea};endFill=1;endSize={head};startArrow={sa};'
                 f'startFill=1;startSize={head};strokeColor={color};strokeWidth={sw};' +
                 (f'dashed=1;dashPattern={" ".join(str(v) for v in dash)};' if dash else ''))
        self.cells.append(('e', self._id(), '', style, pts))

    def text(self, x, y, s, fs=8, ha='center', va='middle', color='#000000', bold=False, rot=0):
        """Text anchored at (x, y); ha in left/center/right, va in top/middle/bottom. rot = 90 reads upward."""
        fs = fs * FS_SCALE
        t = self._mpl_text(x, y, s, fs, ha, va, color, bold, rot, self._zo())
        cid = self._id()
        self.cells.append(('t', cid, to_html(s), None, (x, y, fs, ha, va, color, bold, rot, t)))

    def _mpl_text(self, x, y, s, fs, ha, va, color, bold, rot, z):
        vmap = {'middle': 'center', 'top': 'top', 'bottom': 'bottom', 'baseline': 'baseline'}
        return self.ax.text(x, y, s, fontsize=fs, ha=ha, va=vmap[va], color=color, rotation=rot,
                            fontweight='bold' if bold else 'normal', zorder=z, linespacing=1.15,
                            multialignment=ha if ha != 'center' else 'center', rotation_mode='anchor')

    # ------------------------------------------------------------------ output
    def save(self, base):
        self.fig.savefig(base + '.pdf', dpi=72)
        rend = self.fig.canvas.get_renderer()
        inv = self.ax.transData.inverted()
        out = ['<mxfile host="rptg-figgen" type="device">',
               f'<diagram name="{html.escape(base.rsplit("/", 1)[-1])}" id="d1">',
               f'<mxGraphModel grid="0" gridSize="5" guides="1" tooltips="1" connect="0" arrows="1" fold="1" page="1" '
               f'pageScale="1" pageWidth="{int(self.w) + 1}" pageHeight="{int(self.h) + 1}" math="0" shadow="0">',
               '<root><mxCell id="0"/><mxCell id="1" parent="0"/>',
               # an invisible frame of the figure's size keeps the exported PDF's crop box identical
               f'<mxCell id="frame" value="" style="rounded=0;html=1;fillColor=none;strokeColor=none;" vertex="1" '
               f'parent="1"><mxGeometry x="0" y="0" width="{self.w}" height="{self.h}" as="geometry"/></mxCell>']
        for kind, cid, val, style, geo in self.cells:
            v = html.escape(val, quote=True)
            if kind == 'v':
                x, y, w, h = geo
                out.append(f'<mxCell id="{cid}" value="{v}" style="{style}" vertex="1" parent="1">'
                           f'<mxGeometry x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" as="geometry"/></mxCell>')
            elif kind == 'e':
                pts = geo
                way = ''.join(f'<mxPoint x="{a:.2f}" y="{b:.2f}"/>' for a, b in pts[1:-1])
                out.append(f'<mxCell id="{cid}" value="" style="{style}" edge="1" parent="1">'
                           f'<mxGeometry relative="1" as="geometry">'
                           f'<mxPoint x="{pts[0][0]:.2f}" y="{pts[0][1]:.2f}" as="sourcePoint"/>'
                           f'<mxPoint x="{pts[-1][0]:.2f}" y="{pts[-1][1]:.2f}" as="targetPoint"/>'
                           + (f'<Array as="points">{way}</Array>' if way else '') + '</mxGeometry></mxCell>')
            else:
                x, y, fs, ha, va, color, bold, rot, t = geo
                bb = t.get_window_extent(rend)
                (x0, y1_), (x1_, y0) = inv.transform([(bb.x0, bb.y0), (bb.x1, bb.y1)])
                bw, bh = abs(x1_ - x0) + 2, abs(y1_ - y0) + 1
                if rot % 180:           # rotated: box of the unrotated text, centred on the drawn text
                    bw, bh = bh, bw
                    cx, cy = (x0 + x1_) / 2, (y0 + y1_) / 2
                    bx, by = cx - bw / 2, cy - bh / 2
                else:
                    bx = {'left': x - 1, 'center': x - bw / 2, 'right': x - bw + 1}[ha]
                    by = min(y0, y1_) - 0.5
                st = (f'text;html=1;whiteSpace=nowrap;strokeColor=none;fillColor=none;spacing=0;'
                      f'fontFamily=Helvetica;fontSize={fs};fontColor={color};align={ha};verticalAlign=middle;'
                      + ('fontStyle=1;' if bold else '') + (f'rotation={-rot};' if rot else ''))
                out.append(f'<mxCell id="{cid}" value="{v}" style="{st}" vertex="1" parent="1">'
                           f'<mxGeometry x="{bx:.2f}" y="{by:.2f}" width="{bw:.2f}" height="{bh:.2f}" as="geometry"/></mxCell>')
        out.append('</root></mxGraphModel></diagram></mxfile>')
        with open(base + '.drawio', 'w') as f:
            f.write('\n'.join(out) + '\n')
        plt.close(self.fig)


class Plot:
    """A data panel inside a Fig: maps data to figure units, draws axes, ticks, grid and legend."""

    def __init__(self, fig, x, y, w, h, xlim, ylim, xlog=False, ylog=False):
        self.f, self.x, self.y, self.w, self.h = fig, x, y, w, h
        self.xlim, self.ylim, self.xlog, self.ylog = xlim, ylim, xlog, ylog

    def _n(self, v, lim, log):
        import math
        a, b = lim
        if log:
            v, a, b = math.log10(max(v, 1e-300)), math.log10(a), math.log10(b)
        return (v - a) / (b - a)

    def X(self, v):
        return self.x + self._n(v, self.xlim, self.xlog) * self.w

    def Y(self, v):
        return self.y + self.h - self._n(v, self.ylim, self.ylog) * self.h

    def clampy(self, v):
        return min(max(v, self.ylim[0]), self.ylim[1])

    def frame(self, color='#000000', sw=0.6):
        f = self.f
        f.line([(self.x, self.y + self.h), (self.x + self.w, self.y + self.h)], color=color, sw=sw)
        f.line([(self.x, self.y), (self.x, self.y + self.h)], color=color, sw=sw)

    def xticks(self, vals, labels=None, fs=7, grid=True, tick=2):
        for i, v in enumerate(vals):
            X = self.X(v)
            if grid:
                self.f.line([(X, self.y), (X, self.y + self.h)], color='#e3e3e3', sw=0.4)
            self.f.line([(X, self.y + self.h), (X, self.y + self.h + tick)], color='#000000', sw=0.5)
            self.f.text(X, self.y + self.h + tick + 1, labels[i] if labels else f'{v:g}', fs=fs, va='top')

    def yticks(self, vals, labels=None, fs=7, grid=True, tick=2):
        for i, v in enumerate(vals):
            Y = self.Y(v)
            if grid:
                self.f.line([(self.x, Y), (self.x + self.w, Y)], color='#e3e3e3', sw=0.4)
            self.f.line([(self.x - tick, Y), (self.x, Y)], color='#000000', sw=0.5)
            self.f.text(self.x - tick - 1.5, Y, labels[i] if labels else f'{v:g}', fs=fs, ha='right')

    def xlabel(self, s, fs=7.5, dy=13):
        self.f.text(self.x + self.w / 2, self.y + self.h + dy, s, fs=fs, va='top')

    def ylabel(self, s, fs=7.5, dx=18):
        self.f.text(self.x - dx, self.y + self.h / 2, s, fs=fs, rot=90)

    def title(self, s, fs=7.5, dy=3, bold=True):
        self.f.text(self.x + self.w / 2, self.y - dy, s, fs=fs, va='bottom', bold=bold)

    def hline(self, v, color='#555555', sw=0.6, dash=(3, 2)):
        Y = self.Y(v)
        self.f.line([(self.x, Y), (self.x + self.w, Y)], color=color, sw=sw, dash=dash)

    def vline(self, v, color='#555555', sw=0.6, dash=(3, 2)):
        X = self.X(v)
        self.f.line([(X, self.y), (X, self.y + self.h)], color=color, sw=sw, dash=dash)

    def curve(self, xs, ys, color, sw=1.2, dash=None, clamp=True):
        pts = [(self.X(a), self.Y(self.clampy(b) if clamp else b)) for a, b in zip(xs, ys)]
        self.f.line(pts, color=color, sw=sw, dash=dash, cap='round')


def legend(fig, x, y, items, fs=7, row=10, sample=14, col_w=None, ncol=1):
    """items: (label, color, dash, marker) tuples; one row per item (or ncol columns)."""
    for i, (lab, color, dash, mk) in enumerate(items):
        c, r = (i % ncol, i // ncol)
        X = x + ((col_w[c] if isinstance(col_w, (list, tuple)) else c * col_w) if col_w else 0)
        Y = y + r * row
        if dash != 'bar':
            fig.line([(X, Y), (X + sample, Y)], color=color, sw=1.2, dash=dash)
            if mk:
                fig.marker(X + sample / 2, Y, mk, 3.6, fill=color)
        else:
            fig.rect(X + 2, Y - 3, sample - 4, 6, fill=color, stroke='none')
        fig.text(X + sample + 3, Y, lab, fs=fs, ha='left')
