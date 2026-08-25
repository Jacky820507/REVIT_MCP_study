# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Pure rules for 牆是否貼附樓板 (JAC 06.05).

Revit records *that* a wall end is attached (``WALL_TOP_IS_ATTACHED``) but
never *what* it is attached to — the API exposes no target. So the flag on its
own cannot answer 「這面牆有沒有貼到樓板」, and neither can geometry on its
own. This module reads both and reports where they disagree, because the
disagreements are the findings:

* **未貼附但剛好齊平** works today and breaks the moment the slab moves. It is
  invisible in every view and in every schedule, and it is the most common way
  a model quietly rots.
* **已貼附但和最近的樓板對不上** usually means the wall is attached to
  something else — a roof, a ceiling, a slab two levels up. Worth a look
  precisely because the flag says everything is fine.

A wall is sampled along its centreline rather than tested as one box: a wall
running past the edge of a slab is covered at one end and open at the other,
and a single verdict would have to lie about half of it.

Geometry is the bounding box of what is actually in the model, so a sloped or
profile-edited wall is judged at its highest point. That is stated rather than
detected — a wrong 「非平頂」 flag would be worse than none.

Lengths are millimetres.
"""


DEFAULT_FLUSH_TOL_MM = 5.0
# Beyond this the wall was probably never meant to reach the slab — a 矮牆, a
# 欄杆牆, a 女兒牆. Reporting those as defects buries the real ones.
DEFAULT_IGNORE_GAP_MM = 1500.0
# How far a slab underside may sit below the wall top and still be the slab
# this wall meets. Past this the wall is under a different storey entirely.
DEFAULT_PENETRATION_MM = 600.0
DEFAULT_CELL_MM = 5000.0

END_TOP = 'top'
END_BASE = 'base'
END_LABELS = {END_TOP: u'牆頂', END_BASE: u'牆底'}

STATE_OK = u'已貼附且齊平'
STATE_ATTACHED_OFF = u'已貼附但與最近樓板不齊平'
STATE_GAP = u'未貼附且有縫隙'
STATE_EMBEDDED = u'未貼附且穿入樓板'
STATE_FLUSH_ONLY = u'未貼附但齊平'
STATE_NO_SLAB = u'該側無樓板'
STATE_UNKNOWN = u'讀不到貼附狀態'

# Ordered by how likely you need to do something about it, not by any
# regulatory ranking.
STATE_ORDER = (
    STATE_GAP,
    STATE_EMBEDDED,
    STATE_ATTACHED_OFF,
    STATE_FLUSH_ONLY,
    STATE_UNKNOWN,
    STATE_NO_SLAB,
    STATE_OK,
)
PROBLEM_STATES = (STATE_GAP, STATE_EMBEDDED, STATE_ATTACHED_OFF,
                  STATE_FLUSH_ONLY)

FLAG_PARTIAL = u'部分範圍無樓板'

SKIP_CURTAIN = u'帷幕牆，貼附不適用'
SKIP_STACKED_MEMBER = u'堆疊牆的子牆，由母牆代表'
SKIP_NO_GEOMETRY = u'讀不到幾何範圍'


def _number(value, fallback=None):
    try:
        if value is None:
            return fallback
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value).strip()
    except Exception:
        return str(value).strip()


def _cell(value, cell_mm):
    return int(_number(value, 0.0) // cell_mm)


DEFAULT_SAMPLE_SPACING_MM = 1000.0
MIN_SAMPLES = 3
MAX_SAMPLES = 25
# Ends are sampled just inside the wall so that a wall finishing exactly on a
# slab edge does not flip on floating-point noise.
END_INSET = 0.02


def sample_params(length_mm, spacing_mm=DEFAULT_SAMPLE_SPACING_MM,
                  max_points=MAX_SAMPLES):
    """Normalised positions along a wall to test, ends first.

    Spacing is by length rather than a fixed count: five points on a 40 m wall
    leaves 10 m between tests, which is wide enough to step over a whole
    stairwell opening and report the wall as covered.
    """
    length = _number(length_mm, 0.0) or 0.0
    spacing = _number(spacing_mm, DEFAULT_SAMPLE_SPACING_MM) or \
        DEFAULT_SAMPLE_SPACING_MM
    count = int(abs(length) // spacing) + 1
    count = max(MIN_SAMPLES, min(int(max_points), count))
    span = 1.0 - 2.0 * END_INSET
    return [END_INSET + span * index / float(count - 1)
            for index in range(count)]


def build_slab_index(slabs, cell_mm=DEFAULT_CELL_MM):
    """Grid-hash slabs by plan cell.

    Without this the search is walls x samples x slabs, which on a real model
    is tens of millions of comparisons in IronPython. Each slab is filed under
    every cell its plan box touches, so a sample point only ever looks at the
    handful of slabs actually near it.
    """
    index = {}
    for slab in slabs or []:
        min_x = _number(slab.get('min_x'))
        min_y = _number(slab.get('min_y'))
        max_x = _number(slab.get('max_x'))
        max_y = _number(slab.get('max_y'))
        if None in (min_x, min_y, max_x, max_y):
            continue
        for cx in range(_cell(min_x, cell_mm), _cell(max_x, cell_mm) + 1):
            for cy in range(_cell(min_y, cell_mm), _cell(max_y, cell_mm) + 1):
                index.setdefault((cx, cy), []).append(slab)
    return index


def slabs_at(index, x, y, cell_mm=DEFAULT_CELL_MM):
    """Slabs whose plan box actually contains the point, not just its cell."""
    found = []
    for slab in index.get((_cell(x, cell_mm), _cell(y, cell_mm)), []):
        if (_number(slab.get('min_x'), 0.0) <= x
                <= _number(slab.get('max_x'), 0.0)
                and _number(slab.get('min_y'), 0.0) <= y
                <= _number(slab.get('max_y'), 0.0)):
            found.append(slab)
    return found


def gap_above(index, x, y, z, cell_mm=DEFAULT_CELL_MM,
              penetration_mm=DEFAULT_PENETRATION_MM):
    """``(gap_mm, slab)`` for the slab this wall top meets, or ``(None, None)``.

    Positive gap means a hole between the wall top and the slab underside;
    negative means the wall pokes up into the slab.
    """
    best = None
    best_z = None
    for slab in slabs_at(index, x, y, cell_mm):
        under = _number(slab.get('bottom_z'))
        if under is None or under < z - penetration_mm:
            continue
        if best_z is None or under < best_z:
            best_z = under
            best = slab
    if best is None:
        return None, None
    return best_z - z, best


def gap_below(index, x, y, z, cell_mm=DEFAULT_CELL_MM,
              penetration_mm=DEFAULT_PENETRATION_MM):
    """``(gap_mm, slab)`` for the slab this wall base sits on.

    Positive gap means the wall floats above the slab top; negative means it
    sinks into it.
    """
    best = None
    best_z = None
    for slab in slabs_at(index, x, y, cell_mm):
        over = _number(slab.get('top_z'))
        if over is None or over > z + penetration_mm:
            continue
        if best_z is None or over > best_z:
            best_z = over
            best = slab
    if best is None:
        return None, None
    return z - best_z, best


def skip_reason(wall):
    if wall.get('is_curtain'):
        return SKIP_CURTAIN
    if wall.get('is_stacked_member'):
        return SKIP_STACKED_MEMBER
    if (_number(wall.get('top_z')) is None
            or _number(wall.get('bottom_z')) is None):
        return SKIP_NO_GEOMETRY
    return u''


def classify(attached, worst_gap_mm, flush_tol_mm=DEFAULT_FLUSH_TOL_MM):
    """State for one wall end, given the flag and the worst gap found.

    ``attached`` of ``None`` means the parameter could not be read. Folding
    that into False would invent a 「未貼附」 finding out of a failed read, so
    it gets its own state and is never counted as a defect.
    """
    if attached is None:
        return STATE_UNKNOWN
    if worst_gap_mm is None:
        return STATE_NO_SLAB
    flush = abs(worst_gap_mm) <= flush_tol_mm
    if attached:
        return STATE_OK if flush else STATE_ATTACHED_OFF
    if flush:
        return STATE_FLUSH_ONLY
    return STATE_GAP if worst_gap_mm > 0 else STATE_EMBEDDED


def _worst(gaps):
    """The gap furthest from flush — a wall is only as good as its worst point."""
    values = [value for value in gaps if value is not None]
    if not values:
        return None
    return max(values, key=lambda value: abs(value))


def examine_end(wall, index, end, options):
    """Measure and classify one end of one wall."""
    cell_mm = options.get('cell_mm', DEFAULT_CELL_MM)
    penetration_mm = options.get('penetration_mm', DEFAULT_PENETRATION_MM)
    flush_tol_mm = options.get('flush_tol_mm', DEFAULT_FLUSH_TOL_MM)
    ignore_gap_mm = options.get('ignore_gap_mm', DEFAULT_IGNORE_GAP_MM)

    if end == END_TOP:
        z = _number(wall.get('top_z'))
        attached = wall.get('top_attached')
        finder = gap_above
    else:
        z = _number(wall.get('bottom_z'))
        attached = wall.get('bottom_attached')
        finder = gap_below
    if attached is not None:
        attached = bool(attached)

    gaps = []
    slab_names = []
    for point in wall.get('samples') or []:
        x = _number(point[0])
        y = _number(point[1])
        if x is None or y is None or z is None:
            gaps.append(None)
            continue
        gap, slab = finder(index, x, y, z, cell_mm, penetration_mm)
        # A gap this large means the wall was never meant to reach: a 矮牆 or
        # a 欄杆牆. Treated as 「該側無樓板」 so it does not bury real defects.
        if gap is not None and gap > ignore_gap_mm:
            gap, slab = None, None
        gaps.append(gap)
        if slab is not None:
            name = _text(slab.get('category'))
            if name and name not in slab_names:
                slab_names.append(name)

    covered = len([value for value in gaps if value is not None])
    total = len(gaps)
    worst = _worst(gaps)
    state = classify(attached, worst, flush_tol_mm)

    flags = []
    if 0 < covered < total:
        flags.append(FLAG_PARTIAL)

    return {
        'end': end,
        'end_label': END_LABELS.get(end, end),
        'attached': attached,
        'gaps': gaps,
        'covered': covered,
        'sample_count': total,
        'worst_gap_mm': worst,
        'state': state,
        'flags': flags,
        'slab_categories': slab_names,
    }


def headline_state(item):
    """The one state worth showing when a wall has two ends checked."""
    present = item.get('states') or []
    for state in STATE_ORDER:
        if state in present:
            return state
    return STATE_OK


def analyze(walls, slabs, options=None):
    """Full 貼附 check over a set of walls against a set of slabs."""
    options = dict(options or {})
    options.setdefault('cell_mm', DEFAULT_CELL_MM)
    options.setdefault('penetration_mm', DEFAULT_PENETRATION_MM)
    options.setdefault('flush_tol_mm', DEFAULT_FLUSH_TOL_MM)
    options.setdefault('ignore_gap_mm', DEFAULT_IGNORE_GAP_MM)
    options.setdefault('check_top', True)
    options.setdefault('check_base', False)

    index = build_slab_index(slabs, options['cell_mm'])

    rows = []
    skipped = []
    for wall in walls or []:
        reason = skip_reason(wall)
        if reason:
            skipped.append({'record': wall, 'reason': reason})
            continue
        ends = []
        if options['check_top']:
            ends.append(examine_end(wall, index, END_TOP, options))
        if options['check_base']:
            ends.append(examine_end(wall, index, END_BASE, options))
        item = dict(wall)
        item['ends'] = ends
        item['states'] = [entry['state'] for entry in ends]
        item['problem'] = any(entry['state'] in PROBLEM_STATES
                              for entry in ends)
        rows.append(item)

    rows.sort(key=lambda item: (STATE_ORDER.index(headline_state(item)),
                                _text(item.get('level')),
                                _text(item.get('type_name')),
                                int(_number(item.get('id'), 0))))

    counts = {}
    for item in rows:
        for entry in item['ends']:
            counts[entry['state']] = counts.get(entry['state'], 0) + 1

    return {
        'options': options,
        'rows': rows,
        'skipped': skipped,
        'counts': counts,
        'total': len(rows),
        'slab_count': len(list(slabs or [])),
        'flagged_ids': [item['id'] for item in rows if item['problem']],
    }


def has_problem(result):
    return bool(result.get('flagged_ids'))


def report_lines(result):
    options = result['options']
    ends = []
    if options.get('check_top', True):
        ends.append(END_LABELS[END_TOP])
    if options.get('check_base', False):
        ends.append(END_LABELS[END_BASE])

    lines = [
        u'檢查 {} 面牆對 {} 片樓板／屋頂／天花，檢查端：{}'.format(
            result['total'], result['slab_count'], u'、'.join(ends)),
        u'齊平容差 {:.0f} mm；縫隙大於 {:.0f} mm 視為本來就不到頂的矮牆'.format(
            options['flush_tol_mm'], options['ignore_gap_mm']),
        u'',
    ]

    for state in STATE_ORDER:
        count = result['counts'].get(state)
        if count:
            lines.append(u'　{}：{} 處'.format(state, count))
    lines.append(u'')

    if not result['flagged_ids']:
        lines.append(u'✓ 沒有發現貼附問題。')
    else:
        lines.append(u'✗ {} 面牆需要處理。'.format(len(result['flagged_ids'])))
        shown = 0
        for item in result['rows']:
            if not item['problem'] or shown >= 10:
                continue
            shown += 1
            for entry in item['ends']:
                if entry['state'] not in PROBLEM_STATES:
                    continue
                gap = entry['worst_gap_mm']
                measure = u'{:+.0f} mm'.format(gap) if gap is not None \
                    else u'—'
                lines.append(u'　{}　{}　{}　{}　{}'.format(
                    _text(item.get('level')) or u'(無樓層)',
                    _text(item.get('type_name')),
                    entry['end_label'], entry['state'], measure).rstrip())
        if len(result['flagged_ids']) > shown:
            lines.append(u'　…（其餘 {} 面見輸出視窗）'.format(
                len(result['flagged_ids']) - shown))

    if result['skipped']:
        lines.append(u'')
        lines.append(u'略過 {} 面（帷幕牆／堆疊子牆／無幾何）。'.format(
            len(result['skipped'])))

    lines.append(u'')
    lines.append(u'牆以其外框上下緣代表，所以斜頂或編輯過輪廓的牆是以最高點判斷。')
    lines.append(u'Revit 只記錄「有沒有貼附」，不記錄「貼到什麼」，'
                 u'因此「已貼附但不齊平」多半是貼到屋頂或更上層的板。')
    return u'\n'.join(lines).rstrip()
