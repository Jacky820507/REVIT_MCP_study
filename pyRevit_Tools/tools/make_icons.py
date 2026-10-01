# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Generate pyRevit ribbon icons for the MCP button extensions.

Pure standard library on purpose: this script lives in the repo and must still
run years from now without Pillow or a vector toolchain. Shapes are rasterized
at 4x and box-downsampled, which is enough anti-aliasing for a 96 px ribbon
icon.

Usage:
    python pyRevit_Tools/tools/make_icons.py            # write icon.png files
    python pyRevit_Tools/tools/make_icons.py --sheet X  # also write a contact sheet
    python pyRevit_Tools/tools/make_icons.py --panel Material

Adding a button: append an entry to BUTTONS with a glyph function and let the
panel decide the colour. Re-run; existing icons are overwritten.
"""

import os
import struct
import sys
import zlib

SIZE = 96
SS = 4                      # supersampling factor
CANVAS = SIZE * SS

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
EXTENSION = os.path.join(ROOT, 'MCP_Tools.extension')

# Panel identity. Buttons in the same panel share a hue so a full ribbon reads
# as groups rather than 27 unrelated pictures.
PANEL_COLORS = {
    'Takeoff': (31, 111, 235),      # blue   - 算量
    'Numbering': (22, 163, 74),     # green  - 編號
    'Check': (220, 38, 38),         # red    - 檢核
    'Visual': (124, 58, 237),       # purple - 視覺
    'Structure': (71, 85, 105),     # slate  - 結構
    'Revision': (217, 119, 6),      # amber  - 釋疑
    'Area': (13, 148, 136),         # teal   - 面積
    'BIMGovernance': (14, 116, 144), # cyan  - Agile BIM
    'Material': (37, 87, 131),      # deep blue - 材質管理
    'CAD': (190, 24, 93),           # rose   - CAD 匯入
}
INK = (55, 65, 81)
LIGHT = (148, 163, 184)
EXCEL = (16, 124, 65)
WHITE = (255, 255, 255)


class Canvas(object):
    def __init__(self):
        self.px = bytearray(CANVAS * CANVAS * 4)

    def _blend(self, x, y, color, alpha):
        if alpha <= 0 or x < 0 or y < 0 or x >= CANVAS or y >= CANVAS:
            return
        i = (y * CANVAS + x) * 4
        src_a = alpha
        dst_a = self.px[i + 3] / 255.0
        out_a = src_a + dst_a * (1 - src_a)
        if out_a <= 0:
            return
        for c in range(3):
            src = color[c] / 255.0
            dst = self.px[i + c] / 255.0
            self.px[i + c] = int(round(
                (src * src_a + dst * dst_a * (1 - src_a)) / out_a * 255))
        self.px[i + 3] = int(round(out_a * 255))

    def fill(self, bbox, inside, color, alpha=1.0):
        x0, y0, x1, y1 = bbox
        x0 = max(0, int(x0 * SS) - 2)
        y0 = max(0, int(y0 * SS) - 2)
        x1 = min(CANVAS - 1, int(x1 * SS) + 2)
        y1 = min(CANVAS - 1, int(y1 * SS) + 2)
        for py in range(y0, y1 + 1):
            uy = (py + 0.5) / SS
            for px in range(x0, x1 + 1):
                if inside((px + 0.5) / SS, uy):
                    self._blend(px, py, color, alpha)

    def downsample(self):
        out = bytearray(SIZE * SIZE * 4)
        area = SS * SS
        for y in range(SIZE):
            for x in range(SIZE):
                r = g = b = a = 0
                for dy in range(SS):
                    row = (y * SS + dy) * CANVAS
                    for dx in range(SS):
                        i = (row + x * SS + dx) * 4
                        pa = self.px[i + 3]
                        r += self.px[i] * pa
                        g += self.px[i + 1] * pa
                        b += self.px[i + 2] * pa
                        a += pa
                o = (y * SIZE + x) * 4
                if a:
                    out[o] = int(r / a)
                    out[o + 1] = int(g / a)
                    out[o + 2] = int(b / a)
                out[o + 3] = int(a / area)
        return out


# --- primitives (all coordinates in the 0..96 icon space) ------------------

def rect(canvas, x, y, w, h, color, radius=0, alpha=1.0):
    x1, y1 = x + w, y + h

    def inside(px, py):
        if px < x or px > x1 or py < y or py > y1:
            return False
        if radius <= 0:
            return True
        # Clamp to the corner-circle centre band, then one distance test.
        cx = x + radius if px < x + radius else (
            x1 - radius if px > x1 - radius else px)
        cy = y + radius if py < y + radius else (
            y1 - radius if py > y1 - radius else py)
        return (px - cx) ** 2 + (py - cy) ** 2 <= radius * radius

    canvas.fill((x, y, x1, y1), inside, color, alpha)


def outline(canvas, x, y, w, h, t, color):
    rect(canvas, x, y, w, t, color)
    rect(canvas, x, y + h - t, w, t, color)
    rect(canvas, x, y, t, h, color)
    rect(canvas, x + w - t, y, t, h, color)


def circle(canvas, cx, cy, r, color, alpha=1.0):
    canvas.fill((cx - r, cy - r, cx + r, cy + r),
                lambda px, py: (px - cx) ** 2 + (py - cy) ** 2 <= r * r,
                color, alpha)


def ring(canvas, cx, cy, r, t, color):
    inner = (r - t) ** 2
    outer = r * r
    canvas.fill(
        (cx - r, cy - r, cx + r, cy + r),
        lambda px, py: inner <= (px - cx) ** 2 + (py - cy) ** 2 <= outer,
        color)


def arc(canvas, cx, cy, r, t, color, start_deg, end_deg):
    """Partial ring. Avoids faking one by knocking out with an opaque box,
    which leaves a visible pale block on dark ribbon themes."""
    import math
    inner = (r - t) ** 2
    outer = r * r
    start = math.radians(start_deg) % (2 * math.pi)
    end = math.radians(end_deg) % (2 * math.pi)

    def inside(px, py):
        d2 = (px - cx) ** 2 + (py - cy) ** 2
        if not (inner <= d2 <= outer):
            return False
        angle = math.atan2(py - cy, px - cx) % (2 * math.pi)
        if start <= end:
            return start <= angle <= end
        return angle >= start or angle <= end

    canvas.fill((cx - r, cy - r, cx + r, cy + r), inside, color)


def line(canvas, x1, y1, x2, y2, t, color):
    dx, dy = x2 - x1, y2 - y1
    length2 = dx * dx + dy * dy
    half = t / 2.0

    def inside(px, py):
        if length2 == 0:
            return (px - x1) ** 2 + (py - y1) ** 2 <= half * half
        u = ((px - x1) * dx + (py - y1) * dy) / length2
        u = max(0.0, min(1.0, u))
        ox, oy = x1 + u * dx - px, y1 + u * dy - py
        return ox * ox + oy * oy <= half * half

    canvas.fill((min(x1, x2) - t, min(y1, y2) - t,
                 max(x1, x2) + t, max(y1, y2) + t), inside, color)


def polygon(canvas, points, color):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]

    def inside(px, py):
        hit = False
        n = len(points)
        for i in range(n):
            x1, y1 = points[i]
            x2, y2 = points[(i + 1) % n]
            if (y1 > py) != (y2 > py):
                xx = x1 + (py - y1) * (x2 - x1) / float(y2 - y1)
                if px < xx:
                    hit = not hit
        return hit

    canvas.fill((min(xs), min(ys), max(xs), max(ys)), inside, color)


def arrow(canvas, x1, y1, x2, y2, t, color, head=11):
    import math
    angle = math.atan2(y2 - y1, x2 - x1)
    bx = x2 - math.cos(angle) * head * 0.85
    by = y2 - math.sin(angle) * head * 0.85
    line(canvas, x1, y1, bx, by, t, color)
    left = (bx + math.cos(angle + 1.9) * head, by + math.sin(angle + 1.9) * head)
    right = (bx + math.cos(angle - 1.9) * head, by + math.sin(angle - 1.9) * head)
    polygon(canvas, [(x2, y2), left, right], color)


def dashes(canvas, x1, y, x2, t, color, dash=8, gap=6):
    x = x1
    while x < x2:
        line(canvas, x, y, min(x + dash, x2), y, t, color)
        x += dash + gap


def excel_badge(canvas):
    """Bottom-right spreadsheet badge marking buttons that emit .xlsx."""
    x, y, w, h = 54, 56, 38, 36
    rect(canvas, x, y, w, h, WHITE, 4)
    rect(canvas, x, y, w, h, EXCEL, 4, 0.16)
    outline(canvas, x, y, w, h, 3, EXCEL)
    rect(canvas, x + 3, y + 11, w - 6, 3, EXCEL)
    rect(canvas, x + 3, y + 22, w - 6, 3, EXCEL)
    rect(canvas, x + 15, y + 3, 3, h - 6, EXCEL)


# --- glyphs ----------------------------------------------------------------

def g_room(canvas, color, thick_edge=None):
    outline(canvas, 12, 14, 64, 56, 5, LIGHT if thick_edge else color)
    if thick_edge == 'bottom':
        rect(canvas, 8, 62, 72, 13, color, 2)
    elif thick_edge == 'top':
        rect(canvas, 8, 9, 72, 13, color, 2)
    elif thick_edge == 'fill':
        rect(canvas, 20, 22, 48, 40, color, 0, 0.35)


def g_partition(canvas, color):
    rect(canvas, 14, 22, 10, 56, color)
    rect(canvas, 40, 22, 10, 56, color)
    rect(canvas, 66, 22, 10, 56, color)
    rect(canvas, 14, 22, 62, 7, LIGHT)


def g_tall_wall(canvas, color):
    rect(canvas, 20, 12, 20, 72, color)
    rect(canvas, 48, 44, 18, 40, LIGHT)
    arrow(canvas, 78, 84, 78, 12, 5, color, 12)


def g_door_threshold(canvas, color):
    outline(canvas, 22, 12, 44, 60, 6, color)
    rect(canvas, 18, 70, 52, 9, EXCEL)
    circle(canvas, 56, 44, 4, color)


def g_relation_audit(canvas, color):
    """A Room boundary with a door/window relation and evidence marker."""
    outline(canvas, 10, 14, 52, 58, 5, color)
    rect(canvas, 30, 10, 14, 14, WHITE)
    line(canvas, 37, 24, 37, 46, 5, color)
    circle(canvas, 72, 34, 11, color)
    circle(canvas, 72, 65, 11, LIGHT)
    line(canvas, 56, 35, 64, 35, 4, color)
    line(canvas, 56, 63, 64, 63, 4, LIGHT)


def g_code_integrity(canvas, color):
    """A small input sheet with a verified row and a warning marker."""
    outline(canvas, 10, 8, 54, 76, 5, LIGHT)
    rect(canvas, 18, 20, 38, 5, color)
    rect(canvas, 18, 34, 28, 5, LIGHT)
    rect(canvas, 18, 48, 34, 5, LIGHT)
    rect(canvas, 18, 62, 24, 5, LIGHT)
    circle(canvas, 70, 36, 15, color)
    line(canvas, 62, 36, 68, 43, 5, WHITE)
    line(canvas, 68, 43, 80, 29, 5, WHITE)


def g_flame(canvas, color):
    polygon(canvas, [(48, 8), (68, 38), (62, 46), (72, 58),
                     (60, 84), (36, 84), (24, 58), (36, 40), (42, 48)], color)
    polygon(canvas, [(48, 40), (60, 60), (54, 78), (42, 78), (36, 60)],
            (255, 196, 84))


def g_clash(canvas, color):
    rect(canvas, 12, 20, 44, 44, LIGHT, 4)
    circle(canvas, 62, 60, 24, color, 0.85)
    line(canvas, 40, 38, 76, 74, 7, WHITE)
    line(canvas, 76, 38, 40, 74, 7, WHITE)


def g_parking(canvas, color):
    rect(canvas, 14, 14, 68, 68, color, 10)
    rect(canvas, 32, 28, 12, 42, WHITE)
    rect(canvas, 32, 28, 28, 12, WHITE)
    rect(canvas, 48, 28, 12, 24, WHITE)
    rect(canvas, 32, 40, 28, 12, WHITE)


def g_hash(canvas, color):
    rect(canvas, 30, 14, 8, 68, color)
    rect(canvas, 54, 14, 8, 68, color)
    rect(canvas, 14, 30, 68, 8, color)
    rect(canvas, 14, 56, 68, 8, color)


def g_sheet(canvas, color):
    rect(canvas, 18, 10, 58, 76, WHITE, 3)
    outline(canvas, 18, 10, 58, 76, 5, color)
    rect(canvas, 26, 62, 42, 16, color, 0, 0.35)
    rect(canvas, 26, 20, 42, 5, LIGHT)
    rect(canvas, 26, 32, 30, 5, LIGHT)


def g_bubble(canvas, color):
    ring(canvas, 40, 40, 26, 6, color)
    arrow(canvas, 58, 58, 84, 84, 6, color, 12)


def g_cloud(canvas, color):
    circle(canvas, 34, 50, 17, color)
    circle(canvas, 54, 44, 21, color)
    circle(canvas, 70, 54, 14, color)
    rect(canvas, 34, 50, 36, 16, color)


def g_cloud_clear(canvas, color):
    """A revision cloud crossed out: this button removes clouds."""
    g_cloud(canvas, color)
    line(canvas, 52, 28, 84, 60, 7, WHITE)
    line(canvas, 84, 28, 52, 60, 7, WHITE)


def g_cloud_tag(canvas, color):
    """A revision cloud with a small annotation tag attached."""
    g_cloud(canvas, color)
    rect(canvas, 55, 56, 34, 28, WHITE, 3)
    outline(canvas, 55, 56, 34, 28, 4, color)
    rect(canvas, 62, 64, 20, 4, color)
    rect(canvas, 62, 73, 14, 4, LIGHT)


def g_pdf_diff(canvas, color):
    """Two stacked sheets (old behind in grey, new in front) plus a cloud.

    The stack says 'two documents compared'; the cloud says what comes out.
    Drawn back-to-front so the front sheet's white fill occludes the back one,
    which is what makes them read as two sheets rather than one hatched box.
    """
    rect(canvas, 8, 6, 40, 54, WHITE, 3)
    outline(canvas, 8, 6, 40, 54, 4, LIGHT)
    rect(canvas, 16, 16, 24, 4, LIGHT)
    rect(canvas, 16, 26, 18, 4, LIGHT)

    rect(canvas, 30, 26, 44, 60, WHITE, 3)
    outline(canvas, 30, 26, 44, 60, 5, color)
    rect(canvas, 38, 36, 28, 4, LIGHT)
    rect(canvas, 38, 46, 20, 4, LIGHT)

    circle(canvas, 47, 68, 9, color)
    circle(canvas, 58, 64, 11, color)
    circle(canvas, 68, 69, 8, color)
    rect(canvas, 47, 68, 21, 9, color)


def g_magnifier(canvas, color):
    ring(canvas, 42, 40, 22, 6, color)
    line(canvas, 58, 56, 82, 80, 8, color)


def g_beam(canvas, color):
    rect(canvas, 10, 20, 76, 10, LIGHT)
    rect(canvas, 22, 58, 52, 16, color, 2)
    arrow(canvas, 70, 36, 70, 54, 5, color, 11)


def g_column(canvas, color):
    rect(canvas, 10, 18, 76, 10, LIGHT)
    rect(canvas, 26, 40, 26, 46, color)
    arrow(canvas, 70, 74, 70, 32, 5, color, 11)


def g_cube(canvas, color):
    polygon(canvas, [(48, 10), (82, 28), (48, 46), (14, 28)], color)
    polygon(canvas, [(14, 28), (48, 46), (48, 84), (14, 66)], color)
    polygon(canvas, [(82, 28), (82, 66), (48, 84), (48, 46)], LIGHT)


def g_scaffold(canvas, color, outer=True):
    if outer:
        outline(canvas, 8, 16, 80, 66, 5, LIGHT)
        x0, y0, w, h = 18, 26, 60, 46
    else:
        outline(canvas, 8, 16, 80, 66, 5, color)
        x0, y0, w, h = 22, 30, 52, 38
    outline(canvas, x0, y0, w, h, 5, color)
    rect(canvas, x0, y0 + h / 2 - 2, w, 5, color)
    rect(canvas, x0 + w / 2 - 2, y0, 5, h, color)


def g_table(canvas, color):
    rect(canvas, 12, 18, 72, 60, WHITE, 3)
    outline(canvas, 12, 18, 72, 60, 5, color)
    rect(canvas, 12, 34, 72, 5, color)
    rect(canvas, 36, 18, 5, 60, color)
    rect(canvas, 60, 18, 5, 60, color)
    rect(canvas, 12, 56, 72, 5, LIGHT)


def g_refresh(canvas, color):
    ring(canvas, 48, 48, 26, 7, color)
    rect(canvas, 58, 10, 34, 34, (0, 0, 0), 0, 0.0)
    polygon(canvas, [(64, 14), (88, 26), (64, 38)], color)


def g_paint(canvas, color):
    rect(canvas, 16, 20, 44, 22, color, 3)
    rect(canvas, 60, 26, 12, 10, LIGHT)
    rect(canvas, 44, 42, 8, 18, LIGHT)
    rect(canvas, 34, 58, 28, 28, color, 4)


def g_palette(canvas, color):
    circle(canvas, 46, 46, 32, color, 0.9)
    circle(canvas, 36, 34, 7, WHITE)
    circle(canvas, 58, 32, 7, WHITE)
    circle(canvas, 30, 56, 7, WHITE)
    line(canvas, 16, 80, 80, 16, 8, (220, 38, 38))


def g_material_lookup(canvas, color):
    """Material swatches under a search lens."""
    rect(canvas, 10, 14, 46, 18, color, 4)
    rect(canvas, 10, 39, 46, 18, LIGHT, 4)
    rect(canvas, 10, 64, 34, 18, (220, 119, 55), 4)
    ring(canvas, 63, 54, 18, 6, color)
    line(canvas, 76, 67, 89, 80, 8, color)


def g_material_batch(canvas, color):
    """A stack of material cards with an edit/check mark."""
    rect(canvas, 10, 15, 58, 18, LIGHT, 4)
    rect(canvas, 10, 40, 58, 18, color, 4)
    rect(canvas, 10, 65, 58, 18, (220, 119, 55), 4)
    circle(canvas, 73, 62, 19, WHITE)
    circle(canvas, 73, 62, 18, color, 0.95)
    line(canvas, 63, 62, 70, 70, 6, WHITE)
    line(canvas, 70, 70, 84, 53, 6, WHITE)


def g_room_material_detail(canvas, color):
    """Room envelope split into finish surfaces and a detail table."""
    outline(canvas, 8, 12, 54, 58, 5, color)
    rect(canvas, 13, 17, 44, 10, LIGHT)
    rect(canvas, 13, 57, 44, 8, (220, 119, 55))
    rect(canvas, 13, 27, 8, 30, color)
    rect(canvas, 64, 35, 26, 45, WHITE, 3)
    outline(canvas, 64, 35, 26, 45, 4, color)
    rect(canvas, 64, 48, 26, 4, color)
    rect(canvas, 64, 61, 26, 4, LIGHT)
    rect(canvas, 75, 35, 4, 45, color)


def g_stair(canvas, color):
    steps = [(16, 68), (30, 56), (44, 44), (58, 32), (72, 20)]
    for x, y in steps:
        rect(canvas, x, y, 16, 6, color)
        rect(canvas, x, y, 6, 18, color)
    dashes(canvas, 14, 82, 84, 5, LIGHT)


def g_param_transfer(canvas, color):
    """A parameter row leaving one property sheet for another.

    Rows rather than cards, because what moves is a definition in a list — and
    the trailing rows stay grey to say the source keeps its own.
    """
    outline(canvas, 4, 16, 34, 46, 4, LIGHT)
    for y in (24, 34, 44):
        rect(canvas, 9, y, 24, 4, LIGHT)
    outline(canvas, 58, 16, 34, 46, 5, color)
    rect(canvas, 63, 24, 24, 5, color)
    rect(canvas, 63, 34, 24, 4, LIGHT)
    rect(canvas, 63, 44, 24, 4, LIGHT)
    arrow(canvas, 41, 26, 55, 26, 5, color, head=9)


def g_template_transfer(canvas, color):
    """Two stacked view-template cards moving from one file to another.

    The left stack is greyed and the right one solid: what travels is a copy,
    and the source is left exactly as it was.
    """
    for offset in (0, 7, 14):
        outline(canvas, 6 + offset, 14 + offset, 30, 22, 4, LIGHT)
    outline(canvas, 60, 30, 30, 22, 5, color)
    rect(canvas, 60, 30, 30, 6, color)
    arrow(canvas, 44, 41, 56, 41, 5, color, head=9)


def g_dedup_areas(canvas, color):
    """Two offset area outlines collapsing into one.

    The back copy is drawn dashed and slightly offset — that offset is the
    whole defect, so it has to be visible at ribbon size.
    """
    for x, y in ((6, 12),):
        dashes(canvas, x, y + 6, x + 44, 4, LIGHT, dash=7, gap=5)
        dashes(canvas, x, y + 44, x + 44, 4, LIGHT, dash=7, gap=5)
    outline(canvas, 16, 26, 46, 46, 5, color)
    arrow(canvas, 68, 30, 84, 46, 5, color, head=9)
    outline(canvas, 66, 50, 26, 26, 5, LIGHT)


def g_area_parameters(canvas, color):
    """An area outline with a property list being added beside it.

    The plus is on the list, not the area: what this makes is the fields, and
    the area is only what they attach to.
    """
    outline(canvas, 6, 22, 36, 40, 4, LIGHT)
    for y in (32, 42, 52):
        rect(canvas, 52, y, 30, 5, color)
    line(canvas, 62, 12, 62, 26, 6, color)
    line(canvas, 55, 19, 69, 19, 6, color)


def g_area_ownership(canvas, color):
    """A plan split into a solid half and a hatched half.

    Solid is 專有, hatched is 共用 — the split is the classification, so the
    icon is the boundary between them rather than two separate rooms.
    """
    outline(canvas, 8, 18, 80, 60, 5, LIGHT)
    rect(canvas, 13, 23, 33, 50, color)
    for y in range(27, 74, 8):
        line(canvas, 50, y, 83, y, 3, color)
    rect(canvas, 46, 18, 5, 60, LIGHT)


def g_cad_grid_align(canvas, color):
    """Revit grids (solid, with bubbles) and an offset CAD grid (light)
    being pulled onto them — the whole button is 「把 CAD 交點貼到網格交點」.
    """
    line(canvas, 14, 30, 80, 30, 3, LIGHT)     # CAD grid, offset up-left
    line(canvas, 30, 14, 30, 80, 3, LIGHT)
    line(canvas, 22, 44, 88, 44, 5, color)     # Revit grid
    line(canvas, 44, 22, 44, 88, 5, color)
    ring(canvas, 44, 14, 7, 3, color)
    ring(canvas, 14, 44, 7, 3, color)
    arrow(canvas, 32, 32, 41, 41, 4, INK, head=8)
    circle(canvas, 44, 44, 5, INK)


def g_cad_to_boundary(canvas, color):
    """A messy CAD sketch on the left resolving into a clean boundary loop.

    The left half is deliberately ragged — overshooting lines, a stray stub —
    because that is what the button is for. Drawing two tidy rectangles would
    say 「複製」 rather than 「整理」.
    """
    line(canvas, 6, 20, 42, 20, 4, LIGHT)
    line(canvas, 6, 20, 6, 58, 4, LIGHT)
    line(canvas, 2, 58, 44, 58, 4, LIGHT)      # overshoots both ends
    line(canvas, 40, 14, 40, 52, 4, LIGHT)     # overshoots the corner
    line(canvas, 14, 40, 26, 40, 4, LIGHT)     # stray stub
    arrow(canvas, 48, 39, 62, 39, 5, color, head=9)
    outline(canvas, 66, 22, 26, 34, 5, color)


def g_swap_mark_types(canvas, color):
    """A section cut line with its head symbol, and a swap arrow.

    The head circle with a stub tail is the 剖刀 as it reads on a plan; the
    round-trip arrows underneath say the symbol itself is what changes, not
    where the section is.
    """
    dashes(canvas, 8, 26, 88, 6, LIGHT, dash=12, gap=8)
    circle(canvas, 20, 26, 13, color)
    circle(canvas, 20, 26, 6, WHITE)
    line(canvas, 33, 26, 46, 26, 7, color)
    circle(canvas, 76, 26, 13, LIGHT)
    circle(canvas, 76, 26, 6, WHITE)
    arrow(canvas, 26, 62, 70, 62, 6, color, head=10)
    arrow(canvas, 70, 80, 26, 80, 6, LIGHT, head=10)


def g_room_purge(canvas, color):
    """A room outline broken open on one side, with a bin-stroke through it.

    The gap in the boundary is the point: what gets cleared is the room whose
    walls are gone, not any old room. A closed box with an X would read as
    「刪掉房間」 generally, which is exactly the wrong promise.
    """
    # The gap is left wide open rather than dashed: at 96 px a dashed run
    # blurs back into a solid edge and the icon reverts to 「刪掉房間」.
    for x1, y1, x2, y2 in ((10, 14, 86, 14), (10, 14, 10, 78),
                           (10, 78, 44, 78), (86, 14, 86, 40)):
        line(canvas, x1, y1, x2, y2, 7, LIGHT)
    line(canvas, 22, 68, 76, 24, 9, color)


def g_replace_titleblock(canvas, color):
    """Two framed sheets: left carries the old title strip, right the new one.

    Same sheet outline on both sides — only the titleblock strip differs, which
    is exactly what the button changes.
    """
    outline(canvas, 4, 16, 34, 46, 4, LIGHT)
    rect(canvas, 4, 52, 34, 10, LIGHT)
    outline(canvas, 58, 16, 34, 46, 5, color)
    rect(canvas, 58, 46, 34, 16, color)
    arrow(canvas, 40, 39, 55, 39, 5, color, head=9)


def g_placeholder_sheet(canvas, color):
    """A dashed empty sheet becoming a solid framed one.

    The left sheet is dashed and blank — that is what a placeholder is, a
    number with no titleblock. The right one has a real border and a title
    strip. The arrow between them is the whole button.
    """
    outline(canvas, 4, 16, 34, 46, 4, LIGHT)
    dashes(canvas, 6, 20, 36, 4, LIGHT, dash=6, gap=5)
    dashes(canvas, 6, 56, 36, 4, LIGHT, dash=6, gap=5)
    outline(canvas, 58, 16, 34, 46, 5, color)
    rect(canvas, 58, 52, 34, 10, color)
    arrow(canvas, 40, 39, 55, 39, 5, color, head=9)


def g_egress_distance(canvas, color):
    """The walked route beside the straight line it is not.

    §93 measures 「隔間後之可行距離非直線距離」, so the icon has to show the
    difference or it shows nothing: a pale dashed straight shot from the room
    to the stair, and the real route in the accent colour detouring round the
    end of the partition. The stair is the ink-coloured block it arrives at,
    kept a different tone from the route so the two do not read as one shape.
    """
    circle(canvas, 16, 22, 7, color)                      # 居室的起點
    rect(canvas, 46, 6, 7, 46, LIGHT)                     # 隔間牆（下端留缺口）
    dashes(canvas, 25, 22, 66, 3, LIGHT, dash=7, gap=6)   # 直線：錯的量法
    line(canvas, 16, 30, 16, 76, 6, color)                # 實際路徑：先往下
    line(canvas, 13, 76, 74, 76, 6, color)                # 繞過牆端
    line(canvas, 74, 76, 74, 48, 6, color)                # 再折上樓梯
    for index in range(3):                                # 樓梯：終點
        rect(canvas, 62 + index * 8, 40 - index * 10, 8, 10 + index * 10, INK)


def g_wall_slab_attach(canvas, color):
    """A slab with a wall short of it, and the gap called out in red.

    Two walls under one slab: the left one reaches, the right one stops short
    with the gap drawn as a dashed void. The whole point of the button is that
    gap, so it is the only thing in the accent colour.
    """
    rect(canvas, 6, 14, 84, 14, LIGHT)          # slab
    rect(canvas, 18, 28, 14, 58, color)         # wall that reaches
    rect(canvas, 58, 44, 14, 42, color)         # wall that stops short
    dashes(canvas, 54, 36, 78, 5, (220, 38, 38), dash=7, gap=5)
    line(canvas, 65, 30, 65, 42, 4, (220, 38, 38))


def g_accessible_stair(canvas, color):
    """Stair steps behind a wheelchair mark — 「哪一座樓梯算數」.

    The steps are drawn in LIGHT and the mark in the panel colour, because the
    question this button answers is not 「有沒有樓梯」 but which of them counts
    as 無障礙. At ribbon size the mark is what has to survive the downsample,
    so it gets the contrast and the steps stay background.
    """
    for x, y in ((6, 76), (18, 64), (30, 52), (42, 40)):
        rect(canvas, x, y, 14, 5, LIGHT)
        rect(canvas, x, y, 5, 17, LIGHT)
    ring(canvas, 64, 62, 21, 7, color)
    circle(canvas, 57, 20, 8, color)
    line(canvas, 57, 29, 57, 53, 8, color)
    line(canvas, 57, 53, 82, 53, 8, color)
    line(canvas, 82, 53, 87, 72, 7, color)


def g_door_window(canvas, color):
    """A door leaf beside a four-pane window — the 門窗表 pairing."""
    outline(canvas, 8, 10, 34, 66, 5, color)
    circle(canvas, 35, 44, 4, color)
    outline(canvas, 50, 18, 38, 38, 5, color)
    rect(canvas, 50, 35, 38, 5, color)
    rect(canvas, 66, 18, 5, 38, color)


def g_door_window_legend(canvas, color):
    """Two openings on a shared baseline, with text lines under them.

    The button's whole point is the arrangement, so the icon shows it: a tall
    window and a short door standing on the *same* bottom line (not centred,
    not top-aligned), each with its parameter text below.
    """
    baseline = 62
    rect(canvas, 10, baseline - 44, 32, 44, LIGHT)        # 高的窗
    line(canvas, 26, baseline - 44, 26, baseline, 3, color)
    line(canvas, 10, baseline - 22, 42, baseline - 22, 3, color)
    rect(canvas, 52, baseline - 30, 30, 30, LIGHT)        # 矮的門
    line(canvas, 52, baseline - 30, 52, baseline, 3, color)
    line(canvas, 6, baseline, 88, baseline, 4, color)     # 共同底線
    for index in range(3):                                # 參數文字
        y = baseline + 8 + index * 8
        dashes(canvas, 10, y, 42, 3, INK, dash=8, gap=4)
        dashes(canvas, 52, y, 82, 3, INK, dash=8, gap=4)


def g_duplicate_marks(canvas, color):
    """A window pane plus two stacked number tags — one 編號 on two things.

    The tags overlap and the front one is knocked out in white, which is what
    makes the pair read as a duplicate rather than as two unrelated labels.
    """
    outline(canvas, 8, 6, 36, 36, 5, LIGHT)
    rect(canvas, 8, 22, 36, 4, LIGHT)
    rect(canvas, 24, 6, 4, 36, LIGHT)
    for x, y in ((44, 42), (56, 56)):
        rect(canvas, x, y, 38, 24, WHITE, 4)
        outline(canvas, x, y, 38, 24, 5, color)
    rect(canvas, 64, 66, 9, 5, color)
    rect(canvas, 77, 66, 9, 5, color)


def g_area(canvas, color):
    """A dashed area boundary with the enclosed face filled and a small tag.

    The boundary is dashed because that is what distinguishes an area boundary
    line from a wall on screen, and the fill is what says the region actually
    closed — the two things this button spends all its effort getting right.
    """
    rect(canvas, 12, 14, 62, 54, color, 0, 0.22)
    for y in (14, 68):
        dashes(canvas, 12, y, 74, 5, color, 9, 6)
    for x in (12, 74):
        for y in range(14, 68, 15):
            rect(canvas, x, y, 5, 9, color)
    rect(canvas, 50, 62, 34, 22, WHITE, 3)
    outline(canvas, 50, 62, 34, 22, 4, color)
    rect(canvas, 57, 71, 20, 4, color)


def g_merge_dimensions(canvas, color):
    """Two short dimension strings above, one continuous string below.

    The witness ticks are what make it read as dimensions rather than plain
    rules, and the middle tick disappearing on the lower line is the merge.
    """
    for x in (10, 44, 50, 86):
        rect(canvas, x, 14, 4, 20, LIGHT)
    rect(canvas, 12, 22, 32, 4, color)
    rect(canvas, 52, 22, 32, 4, color)
    arrow(canvas, 48, 44, 48, 60, 6, color, 11)
    for x in (10, 86):
        rect(canvas, x, 66, 4, 20, LIGHT)
    rect(canvas, 12, 74, 74, 4, color)


def g_group_height(canvas, color):
    """Two stacked group boxes on their level lines, the upper one lifted.

    The gap under the top box is the defect this button looks for: identical
    groups that should sit the same way on every floor, one of them floating.
    """
    rect(canvas, 10, 78, 76, 5, LIGHT)
    rect(canvas, 10, 40, 76, 5, LIGHT)
    outline(canvas, 20, 52, 44, 26, 5, color)
    rect(canvas, 30, 60, 24, 4, color)
    outline(canvas, 20, 8, 44, 26, 5, color)
    rect(canvas, 30, 16, 24, 4, color)
    arrow(canvas, 74, 40, 74, 14, 5, color, 10)


def g_area_formula(canvas, color):
    """An area split into two labelled pieces with an equals bar underneath.

    The divided outline plus the ``=`` is the idea in one glance: the region is
    read as simple shapes and written out as an expression.
    """
    rect(canvas, 8, 8, 76, 40, color, 0, 0.20)
    for y in (8, 48):
        dashes(canvas, 8, y, 84, 4, color, 8, 5)
    for x in (8, 84):
        for y in range(8, 48, 13):
            rect(canvas, x, y, 4, 8, color)
    rect(canvas, 44, 8, 4, 40, color)
    rect(canvas, 12, 62, 68, 6, color)
    rect(canvas, 12, 76, 68, 6, color)


def g_area_list(canvas, color):
    """A dashed area outline with list rows inside — the areas as a table.

    Kept to the top-left so the shared Excel badge has its corner; the dashed
    edge is what ties it to the rest of the 面積 family.
    """
    rect(canvas, 8, 8, 44, 44, color, 0, 0.18)
    for y in (8, 52):
        dashes(canvas, 8, y, 52, 4, color, 8, 5)
    for x in (8, 52):
        for y in range(8, 52, 12):
            rect(canvas, x, y, 4, 7, color)
    for y in (20, 30, 40):
        rect(canvas, 16, y, 30, 4, color)


def g_area_purge(canvas, color):
    """A dashed area outline being struck through — the only tool that deletes.

    The stroke reads as removal at ribbon size, where a small bin icon would
    turn to mush.
    """
    rect(canvas, 10, 12, 64, 54, color, 0, 0.16)
    for y in (12, 66):
        dashes(canvas, 10, y, 74, 4, color, 8, 6)
    for x in (10, 74):
        for y in range(12, 66, 14):
            rect(canvas, x, y, 4, 8, color)
    line(canvas, 14, 70, 82, 8, 7, color)
    line(canvas, 14, 8, 82, 70, 7, color)


def g_area_boundary(canvas, color):
    """Room walls in grey with the dashed area boundary redrawn over them.

    The two layers are the whole point of this button: solid architecture
    underneath, generated boundary on top following it.
    """
    outline(canvas, 8, 8, 80, 62, 5, LIGHT)
    rect(canvas, 46, 8, 5, 62, LIGHT)
    rect(canvas, 8, 40, 43, 5, LIGHT)
    for y in (12, 66):
        dashes(canvas, 12, y, 84, 4, color, 8, 6)
    for x in (12, 84):
        for y in range(12, 66, 13):
            rect(canvas, x, y, 4, 7, color)
    rect(canvas, 48, 12, 4, 58, color)


def g_area_copy(canvas, color):
    """Two dashed area outlines with an arrow between them — one copied to two.

    The source keeps the filled interior and the target is left empty, so the
    direction of the copy reads without needing the arrow alone to carry it.
    """
    rect(canvas, 6, 8, 34, 34, color, 0, 0.22)
    for y in (8, 42):
        dashes(canvas, 6, y, 40, 4, color, 7, 5)
    for x in (6, 40):
        for y in range(8, 42, 11):
            rect(canvas, x, y, 4, 6, color)
    arrow(canvas, 46, 48, 62, 62, 6, color, 11)
    for y in (54, 88):
        dashes(canvas, 54, y, 88, 4, color, 7, 5)
    for x in (54, 88):
        for y in range(54, 88, 11):
            rect(canvas, x, y, 4, 6, color)


def g_area_renumber(canvas, color):
    """The dashed area boundary plus the numbering hash used by 編號 buttons.

    Shares the dashed-boundary idiom with the sibling 面積 icon so the two read
    as one family, and borrows the hash so it reads as numbering at a glance.
    """
    rect(canvas, 8, 8, 40, 40, color, 0, 0.22)
    for y in (8, 48):
        dashes(canvas, 8, y, 48, 4, color, 8, 5)
    for x in (8, 48):
        for y in range(8, 48, 12):
            rect(canvas, x, y, 4, 7, color)
    g_hash_small(canvas, color)


def g_dependent_crop(canvas, color):
    """A parent view frame, its dashed crop region, and the dependent copy."""
    outline(canvas, 8, 8, 58, 46, 5, LIGHT)
    dashes(canvas, 18, 20, 56, 4, color, 8, 6)
    dashes(canvas, 18, 42, 56, 4, color, 8, 6)
    rect(canvas, 18, 20, 4, 26, color)
    rect(canvas, 52, 20, 4, 26, color)
    rect(canvas, 40, 58, 46, 32, WHITE, 4)
    outline(canvas, 40, 58, 46, 32, 5, color)


def g_group_projection(canvas, color):
    """Warm upper plane and cool lower plane sharing a vertical centre."""
    polygon(canvas, [(12, 26), (48, 8), (84, 26), (48, 44)], (220, 80, 45))
    polygon(canvas, [(12, 66), (48, 48), (84, 66), (48, 84)], (45, 115, 215))
    line(canvas, 48, 25, 48, 66, 5, color)
    ring(canvas, 48, 26, 8, 3, WHITE)
    ring(canvas, 48, 66, 8, 3, WHITE)


def g_view_scale(canvas, color):
    """A sheet with a scale bar under it — the ratio printed on every drawing.

    Alternating filled and empty divisions read as a scale bar rather than as
    a plain dashed rule.
    """
    outline(canvas, 12, 8, 60, 50, 5, LIGHT)
    rect(canvas, 12, 20, 60, 4, LIGHT)
    outline(canvas, 12, 70, 72, 16, 4, color)
    rect(canvas, 12, 70, 18, 16, color)
    rect(canvas, 48, 70, 18, 16, color)


def g_parking_overlap(canvas, color):
    """Two bays pushed into each other, with the shared strip filled solid.

    The filled intersection is the whole point of the check, so it carries the
    accent while the bays themselves stay as outlines.
    """
    outline(canvas, 8, 12, 50, 70, 5, LIGHT)
    rect(canvas, 38, 26, 20, 56, color, 0, 0.30)
    outline(canvas, 38, 26, 50, 56, 5, color)


def g_fill_blank_mark(canvas, color):
    """A window pane and an empty number tag being filled from above.

    The tag's dashed interior is what says 「空白」 — a solid one would read as
    an ordinary label rather than a blank waiting for a value.
    """
    outline(canvas, 8, 6, 36, 36, 5, LIGHT)
    rect(canvas, 8, 22, 36, 4, LIGHT)
    rect(canvas, 24, 6, 4, 36, LIGHT)
    arrow(canvas, 68, 18, 68, 54, 7, color, 12)
    rect(canvas, 46, 62, 44, 28, WHITE, 4)
    outline(canvas, 46, 62, 44, 28, 5, color)
    dashes(canvas, 54, 74, 82, 4, color, 7, 5)


def g_matchline(canvas, color):
    """Two crop regions split by a dashed boundary, labelled on both sides."""
    outline(canvas, 8, 14, 38, 68, 5, LIGHT)
    outline(canvas, 50, 14, 38, 68, 5, LIGHT)
    # The matchline itself sits on the shared edge, drawn vertically.
    x = 48
    y = 10
    while y < 86:
        rect(canvas, x - 3, y, 7, 9, color)
        y += 15
    # Sheet-number tags either side.
    rect(canvas, 14, 40, 26, 7, color, 2)
    rect(canvas, 56, 40, 26, 7, color, 2)
    rect(canvas, 14, 52, 18, 6, LIGHT, 2)
    rect(canvas, 56, 52, 18, 6, LIGHT, 2)


def g_rc_volume(canvas, color):
    """A wall drawn with depth — the takeoff is m3, not m2 — with an opening."""
    polygon(canvas, [(10, 30), (24, 16), (72, 16), (58, 30)], LIGHT)
    polygon(canvas, [(58, 30), (72, 16), (72, 62), (58, 76)], LIGHT)
    polygon(canvas, [(10, 30), (58, 30), (58, 76), (10, 76)], color)
    rect(canvas, 20, 44, 16, 32, WHITE)


def g_floor(canvas, color):
    polygon(canvas, [(10, 52), (48, 30), (86, 52), (48, 74)], color)
    polygon(canvas, [(10, 52), (48, 74), (48, 84), (10, 62)], LIGHT)
    polygon(canvas, [(86, 52), (86, 62), (48, 84), (48, 74)], LIGHT)


# --- button map ------------------------------------------------------------

def excel(fn):
    """Mark a glyph as producing a spreadsheet."""
    def wrapped(canvas, color):
        fn(canvas, color)
        excel_badge(canvas)
    return wrapped


BUTTONS = [
    ('MCP_Macros.tab/CAD.panel/CadGridAlign.pushbutton', g_cad_grid_align),
    ('MCP_Macros.tab/Area.panel/AutoPlaceAreas.pushbutton', g_area),
    ('MCP_Macros.tab/Area.panel/AreaFormula.pushbutton', g_area_formula),
    ('MCP_Macros.tab/Area.panel/CadToBoundary.pushbutton',
     g_cad_to_boundary),
    ('MCP_Macros.tab/Area.panel/AreaOwnership.pushbutton',
     g_area_ownership),
    ('MCP_Macros.tab/Area.panel/AreaParameters.pushbutton',
     g_area_parameters),
    ('MCP_Macros.tab/Area.panel/DedupAreas.pushbutton',
     g_dedup_areas),
    ('MCP_Macros.tab/Area.panel/CopyAreasToScheme.pushbutton', g_area_copy),
    ('MCP_Macros.tab/Area.panel/ExportAreasExcel.pushbutton',
     excel(g_area_list)),
    ('MCP_Macros.tab/Area.panel/PurgeAreas.pushbutton', g_area_purge),
    ('MCP_Macros.tab/Area.panel/RegenAreaBoundaries.pushbutton',
     g_area_boundary),
    ('MCP_Macros.tab/Area.panel/RenumberAreas.pushbutton', g_area_renumber),
    ('MCP_Macros.tab/Check.panel/AccessibleStairCount.pushbutton',
     g_accessible_stair),
    ('MCP_Macros.tab/Check.panel/DetectClashes.pushbutton', g_clash),
    ('MCP_Macros.tab/Check.panel/EgressDistance.pushbutton',
     g_egress_distance),
    ('MCP_Macros.tab/Check.panel/DuplicateMarks.pushbutton',
     g_duplicate_marks),
    ('MCP_Macros.tab/Check.panel/FireRatingColor.pushbutton', g_flame),
    ('MCP_Macros.tab/Check.panel/GroupHeightCheck.pushbutton',
     g_group_height),
    ('MCP_Macros.tab/Check.panel/ParkingOverlap.pushbutton',
     g_parking_overlap),
    ('MCP_Macros.tab/Check.panel/RoomPurge.pushbutton', g_room_purge),
    ('MCP_Macros.tab/Check.panel/WallSlabAttach.pushbutton',
     g_wall_slab_attach),
    ('MCP_Macros.tab/Numbering.panel/FillBlankMarks.pushbutton',
     g_fill_blank_mark),
    ('MCP_Macros.tab/Numbering.panel/ParkingNumbering.pushbutton', g_parking),
    ('MCP_Macros.tab/Numbering.panel/PlaceholderSheets.pushbutton',
     g_placeholder_sheet),
    ('MCP_Macros.tab/Numbering.panel/ReplaceTitleblocks.pushbutton',
     g_replace_titleblock),
    ('MCP_Macros.tab/Numbering.panel/TemplateTransfer.pushbutton',
     g_template_transfer),
    ('MCP_Macros.tab/Numbering.panel/ProjectParameterTransfer.pushbutton',
     g_param_transfer),
    ('MCP_Macros.tab/Numbering.panel/RenumberRooms.pushbutton',
     lambda c, col: (g_room(c, col), g_hash_small(c, col))),
    ('MCP_Macros.tab/Numbering.panel/RenumberSheets.pushbutton',
     lambda c, col: (g_sheet(c, col), g_hash_small(c, col))),
    ('MCP_Macros.tab/Numbering.panel/SyncDetailNumbers.pushbutton', g_bubble),
    ('MCP_Macros.tab/Revision.panel/CloudViewsToSheets.pushbutton',
     lambda c, col: (g_sheet(c, col), g_cloud_small(c, col))),
    ('MCP_Macros.tab/Revision.panel/ExportExcel.pushbutton',
     excel(lambda c, col: g_cloud(c, col))),
    ('MCP_Macros.tab/Revision.panel/ScanClouds.pushbutton',
     lambda c, col: (g_cloud(c, LIGHT), g_magnifier(c, col))),
    ('MCP_Macros.tab/Revision.panel/PdfDiffClouds.pushbutton', g_pdf_diff),
    ('MCP_Macros.tab/Revision.panel/ClearRevisionClouds.pushbutton',
     g_cloud_clear),
    ('MCP_Macros.tab/Revision.panel/PlaceRevisionCloudTags.pushbutton',
     g_cloud_tag),
    ('MCP_Macros.tab/BIMGovernance.panel/RoomWallDoorAudit.pushbutton',
     g_relation_audit),
    ('MCP_Macros.tab/BIMGovernance.panel/TaiwanBuildingCodeIntegrity.pushbutton',
     g_code_integrity),
    ('MCP_Macros.tab/BIMGovernance.panel/RoomParameterDictionary.pushbutton',
     g_room),
    ('MCP_Macros.tab/BIMGovernance.panel/RoomClassification.pushbutton',
     g_relation_audit),
    ('MCP_Macros.tab/BIMGovernance.panel/DoorSpecifications.pushbutton',
     g_door_window),
    ('MCP_Macros.tab/BIMGovernance.panel/DoorWindowNumbering.pushbutton',
     g_duplicate_marks),
    ('MCP_Macros.tab/BIMGovernance.panel/WallPerformanceClassification.pushbutton',
     g_tall_wall),
    ('MCP_Macros.tab/Material.panel/MaterialReverseLookup.pushbutton',
     g_material_lookup),
    ('MCP_Macros.tab/Material.panel/MaterialBatchEditor.pushbutton',
     g_material_batch),
    ('MCP_Macros.tab/Material.panel/RoomMaterialDetail.pushbutton',
     excel(g_room_material_detail)),
    ('MCP_Macros.tab/Structure.panel/AlignBeams.pushbutton', g_beam),
    ('MCP_Macros.tab/Structure.panel/AlignColumns.pushbutton', g_column),
    ('MCP_Macros.tab/Structure.panel/IfcSync.pushbutton', g_cube),
    ('MCP_Macros.tab/Takeoff.panel/Baseboard.pushbutton',
     excel(lambda c, col: g_room(c, col, 'bottom'))),
    ('MCP_Macros.tab/Takeoff.panel/CeilingTakeoff.pushbutton',
     excel(lambda c, col: g_room(c, col, 'top'))),
    ('MCP_Macros.tab/Takeoff.panel/FloorTakeoff.pushbutton', excel(g_floor)),
    ('MCP_Macros.tab/Takeoff.panel/InteriorWallPaint.pushbutton',
     excel(g_paint)),
    ('MCP_Macros.tab/Takeoff.panel/DoorWindowExcel.pushbutton',
     excel(g_door_window)),
    ('MCP_Macros.tab/Takeoff.panel/MachineRoomThresholdExcel.pushbutton',
     g_door_threshold),
    ('MCP_Macros.tab/Takeoff.panel/ParkingExcel.pushbutton', excel(g_parking)),
    ('MCP_Macros.tab/Takeoff.panel/PartitionTakeoff.pushbutton',
     excel(g_partition)),
    ('MCP_Macros.tab/Takeoff.panel/RcVolumeExcel.pushbutton',
     excel(g_rc_volume)),
    ('MCP_Macros.tab/Takeoff.panel/ScaffoldExterior.pushbutton',
     excel(lambda c, col: g_scaffold(c, col, True))),
    ('MCP_Macros.tab/Takeoff.panel/ScaffoldRooms.pushbutton',
     excel(lambda c, col: g_scaffold(c, col, False))),
    ('MCP_Macros.tab/Takeoff.panel/SpaceTableUpdate.pushbutton',
     excel(lambda c, col: (g_table(c, col), g_update_mark(c, col)))),
    ('MCP_Macros.tab/Takeoff.panel/TallPartitionExcel.pushbutton',
     excel(g_tall_wall)),
    ('MCP_Macros.tab/Visual.panel/DoorWindowLegend.pushbutton',
     g_door_window_legend),
    ('MCP_Macros.tab/Visual.panel/ClearOverrides.pushbutton', g_palette),
    ('MCP_Macros.tab/Visual.panel/DependentViewCropScope.pushbutton',
     g_dependent_crop),
    ('MCP_Macros.tab/Visual.panel/Matchlines.pushbutton', g_matchline),
    ('MCP_Macros.tab/Visual.panel/MergeDimensions.pushbutton',
     g_merge_dimensions),
    ('MCP_Macros.tab/Visual.panel/StairHiddenLine.pushbutton', g_stair),
    ('MCP_Macros.tab/Visual.panel/SwapViewMarkTypes.pushbutton',
     g_swap_mark_types),
    ('MCP_Macros.tab/Visual.panel/ViewScale.pushbutton', g_view_scale),
    ('MCP_Macros.tab/Visual.panel/GroupProjection.pushbutton', g_group_projection),
]


def g_hash_small(canvas, color):
    rect(canvas, 56, 52, 6, 38, color)
    rect(canvas, 74, 52, 6, 38, color)
    rect(canvas, 48, 62, 40, 6, color)
    rect(canvas, 48, 76, 40, 6, color)


def g_update_mark(canvas, color):
    """Clockwise arc + head: 'this rewrites an existing table'."""
    arc(canvas, 28, 28, 17, 6, color, 95, 20)
    polygon(canvas, [(40, 4), (56, 15), (38, 24)], color)


def g_cloud_small(canvas, color):
    circle(canvas, 62, 68, 12, color)
    circle(canvas, 76, 63, 14, color)
    rect(canvas, 62, 68, 22, 11, color)


def write_png(path, pixels):
    raw = bytearray()
    for y in range(SIZE):
        raw.append(0)
        raw.extend(pixels[y * SIZE * 4:(y + 1) * SIZE * 4])

    def chunk(tag, data):
        out = struct.pack('>I', len(data)) + tag + data
        return out + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)

    png = (b'\x89PNG\r\n\x1a\n'
           + chunk(b'IHDR', struct.pack('>IIBBBBB', SIZE, SIZE, 8, 6, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(bytes(raw), 9))
           + chunk(b'IEND', b''))
    with open(path, 'wb') as handle:
        handle.write(png)


def panel_of(rel_path):
    for part in rel_path.split('/'):
        if part.endswith('.panel'):
            return part[:-len('.panel')]
    return 'Takeoff'


def build(rel_path, glyph):
    canvas = Canvas()
    color = PANEL_COLORS.get(panel_of(rel_path), INK)
    glyph(canvas, color)
    return canvas.downsample()


def main():
    written = []
    only_panel = None
    if '--panel' in sys.argv:
        only_panel = sys.argv[sys.argv.index('--panel') + 1]
    for rel_path, glyph in BUTTONS:
        if '--button' in sys.argv and not rel_path.endswith('/' + sys.argv[sys.argv.index('--button') + 1] + '.pushbutton'):
            continue
        if only_panel and panel_of(rel_path) != only_panel:
            continue
        folder = os.path.join(EXTENSION, *rel_path.split('/'))
        if not os.path.isdir(folder):
            print('skip (missing): {}'.format(rel_path))
            continue
        pixels = build(rel_path, glyph)
        target = os.path.join(folder, 'icon.png')
        write_png(target, pixels)
        written.append((rel_path, pixels))
        print('wrote {}'.format(os.path.relpath(target, ROOT)))

    if '--sheet' in sys.argv:
        sheet_path = sys.argv[sys.argv.index('--sheet') + 1]
        write_contact_sheet(sheet_path, written)
        print('contact sheet: {}'.format(sheet_path))
    print('{} icons'.format(len(written)))


def write_contact_sheet(path, written):
    cols = 7
    rows = (len(written) + cols - 1) // cols
    pad = 8
    cell = SIZE + pad
    width, height = cols * cell + pad, rows * cell + pad
    buf = bytearray([250, 250, 250, 255] * (width * height))
    for index, (_rel, pixels) in enumerate(written):
        ox = pad + (index % cols) * cell
        oy = pad + (index // cols) * cell
        for y in range(SIZE):
            for x in range(SIZE):
                i = (y * SIZE + x) * 4
                a = pixels[i + 3] / 255.0
                o = ((oy + y) * width + ox + x) * 4
                for c in range(3):
                    buf[o + c] = int(round(
                        pixels[i + c] * a + buf[o + c] * (1 - a)))
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw.extend(buf[y * width * 4:(y + 1) * width * 4])

    def chunk(tag, data):
        out = struct.pack('>I', len(data)) + tag + data
        return out + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)

    png = (b'\x89PNG\r\n\x1a\n'
           + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(bytes(raw), 9))
           + chunk(b'IEND', b''))
    with open(path, 'wb') as handle:
        handle.write(png)


if __name__ == '__main__':
    main()
