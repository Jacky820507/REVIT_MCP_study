# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Pure rules for CAD 轉區域線（依圖層）— JAC 04.01.

A DWG arrives as one lump of geometry whose only structure is the layer each
curve sits on. Turning a floor plan's 牆心線 layer into area boundary lines is
therefore mostly a filtering problem, and the filtering is where it goes wrong:

**A CAD drawing is not clean.** The same wall gets drawn twice by two people,
polylines close with a zero-length segment on the last vertex, and a "line"
that is 0.4mm long is a leftover from a trim. Feeding those straight into
``NewAreaBoundaryLine`` produces either an exception or an area plan carrying
hundreds of invisible duplicate lines that make every subsequent 面積 unusable
and are miserable to find again.

So three filters run before anything is drawn, and each one reports its count
rather than silently dropping work:

* **too short** — below a threshold the user sets, because what counts as
  noise depends on the drawing's units and sloppiness.
* **duplicate** — same geometry already in this batch, compared without regard
  to direction, since the same wall drawn left-to-right and right-to-left is
  still one wall.
* **unsupported** — splines and ellipses. They are reported, not tessellated
  by default: turning one spline into 200 short boundary lines is a decision
  with consequences, not a detail.

Lengths are millimetres. Nothing here touches Revit.
"""


KIND_LINE = 'Line'
KIND_ARC = 'Arc'
KIND_OTHER = 'Other'

SUPPORTED_KINDS = (KIND_LINE, KIND_ARC)

DEFAULT_MIN_LENGTH_MM = 10.0
# Two endpoints closer than this are the same point as far as dedup cares.
DEFAULT_TOLERANCE_MM = 1.0

BLOCK_TOO_SHORT = u'長度低於下限'
BLOCK_DUPLICATE = u'與同批其他曲線重複'
BLOCK_UNSUPPORTED = u'曲線型別不支援（雲線／橢圓等）'

BLOCK_ORDER = (BLOCK_UNSUPPORTED, BLOCK_TOO_SHORT, BLOCK_DUPLICATE)


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value).strip()
    except Exception:
        return str(value).strip()


def _number(value, fallback=0.0):
    try:
        if value is None:
            return fallback
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _snap(point, tolerance_mm):
    """Quantise a point so float noise does not defeat the dedup.

    Grid snapping, not a distance test: deduping thousands of CAD curves by
    comparing every pair is quadratic, and a drawing that needs this tool has
    thousands. The trade is that the tolerance is a hint rather than a
    guarantee — two points closer than the tolerance still land in different
    buckets when they straddle a grid line (0 and 3 do, at a tolerance of 5).
    Exact duplicates, which is what CAD drawings actually contain, always
    match. Anything the grid misses simply gets drawn, which is the safe way
    to be wrong.
    """
    if not point:
        return (0, 0)
    step = tolerance_mm if tolerance_mm > 0 else DEFAULT_TOLERANCE_MM
    return (int(round(_number(point[0]) / step)),
            int(round(_number(point[1]) / step)))


def curve_key(record, tolerance_mm=DEFAULT_TOLERANCE_MM):
    """Direction-agnostic identity for one curve.

    The two ends are sorted so a wall drawn left-to-right matches the same wall
    drawn right-to-left, but the midpoint is kept separate — otherwise an arc
    and the chord across it would compare equal and one of them would vanish.
    """
    ends = sorted([_snap(record.get('start'), tolerance_mm),
                   _snap(record.get('end'), tolerance_mm)])
    return (_text(record.get('kind')), ends[0], ends[1],
            _snap(record.get('mid'), tolerance_mm))


def layer_summary(records):
    """``[{'layer', 'count', 'total_length_mm'}]`` sorted by layer name.

    Shown before anything is picked: on a real drawing the layer names alone
    rarely say which one holds the walls, but the curve counts do.
    """
    buckets = {}
    for record in records or []:
        layer = _text(record.get('layer')) or u'(無圖層)'
        entry = buckets.setdefault(layer, {'layer': layer, 'count': 0,
                                           'total_length_mm': 0.0})
        entry['count'] += 1
        entry['total_length_mm'] += _number(record.get('length_mm'))
    return sorted(buckets.values(), key=lambda item: item['layer'])


def block_reason(record, min_length_mm):
    if _text(record.get('kind')) not in SUPPORTED_KINDS:
        return BLOCK_UNSUPPORTED
    if _number(record.get('length_mm')) < min_length_mm:
        return BLOCK_TOO_SHORT
    return u''


def build_plan(records, layers=None, min_length_mm=DEFAULT_MIN_LENGTH_MM,
               tolerance_mm=DEFAULT_TOLERANCE_MM):
    """Split the CAD curves into what gets drawn and what does not.

    ``layers`` of ``None`` means every layer.
    """
    wanted = set(layers) if layers else None
    draw = []
    blocked = []
    seen = {}

    for record in records or []:
        layer = _text(record.get('layer')) or u'(無圖層)'
        if wanted is not None and layer not in wanted:
            continue
        reason = block_reason(record, min_length_mm)
        if reason:
            blocked.append({'record': record, 'reason': reason})
            continue
        key = curve_key(record, tolerance_mm)
        if key in seen:
            blocked.append({'record': record, 'reason': BLOCK_DUPLICATE,
                            'duplicate_of': seen[key]})
            continue
        seen[key] = record.get('index')
        draw.append(record)

    counts = {}
    for entry in blocked:
        counts[entry['reason']] = counts.get(entry['reason'], 0) + 1

    return {
        'draw': draw,
        'blocked': blocked,
        'block_counts': counts,
        'layers': layer_summary(draw),
        'count': len(draw),
        'min_length_mm': _number(min_length_mm, DEFAULT_MIN_LENGTH_MM),
        'tolerance_mm': _number(tolerance_mm, DEFAULT_TOLERANCE_MM),
        'considered': len(draw) + len(blocked),
    }


def has_work(plan):
    return bool(plan.get('draw'))


def plan_lines(plan, delete_count=0):
    lines = []
    if not has_work(plan):
        lines.append(u'選取的圖層沒有可用的曲線，模型不會變更。')
    else:
        lines.append(u'將建立 {} 條區域線（來源共 {} 條曲線）：'.format(
            plan['count'], plan['considered']))
        for entry in plan['layers']:
            lines.append(u'　{}：{} 條，總長 {:.1f} m'.format(
                entry['layer'], entry['count'],
                entry['total_length_mm'] / 1000.0))

    if plan['blocked']:
        lines.append(u'')
        lines.append(u'略過 {} 條：'.format(len(plan['blocked'])))
        for reason in BLOCK_ORDER:
            count = plan['block_counts'].get(reason)
            if count:
                lines.append(u'　{}：{} 條'.format(reason, count))

    if delete_count:
        lines.append(u'')
        lines.append(u'另會先刪除該視圖既有的 {} 條區域線。'.format(delete_count))

    lines.append(u'')
    lines.append(u'長度下限 {:.1f} mm，重複比對容差 {:.1f} mm。'.format(
        plan['min_length_mm'], plan['tolerance_mm']))
    return u'\n'.join(lines)
