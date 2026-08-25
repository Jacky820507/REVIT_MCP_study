# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Pure rules for 自動放置面積 (JAC 01.02).

Every length here is millimetres and every point is a plain ``(x, y)`` tuple,
never a Revit ``XYZ``. The collection layer converts once on the way in, which
is what lets the whole of this module be unit-tested with no Revit at all.

Two things this module deliberately does *not* try to decide:

- **whether a boundary actually closes.** Only Revit knows, because it depends
  on the area scheme's own rules about which walls count. The button answers it
  by placing the areas inside a Transaction that is guaranteed to roll back and
  reading the result; :func:`apply_trial_result` folds that answer back in.
- **whether an area is "redundant".** The Revit API has no ``IsRedundant``, so
  the honest signal is the warning text Revit itself produced, surfaced
  verbatim for the operator to judge. Inventing a redundancy rule here would
  produce a confident answer nobody could check.
"""

import room_takeoff_sources_logic as sort_logic


MM_PER_FOOT = 304.8
SQ_FT_TO_SQ_M = 0.09290304

# Seed sources. Only the first is implemented — an option that cannot run is
# worse than a missing one, so the button does not offer the others yet.
SEED_FROM_ROOM = 'room'
SEED_FROM_BOUNDARY = 'boundary'
SEED_FROM_PICK = 'pick'

NUMBER_FROM_ROOM = 'room_number'
NUMBER_SEQUENCE = 'sequence'
NUMBER_NONE = 'none'

NAME_FROM_ROOM = 'room_name'
NAME_CONSTANT = 'constant'
NAME_NONE = 'none'

NUMBER_SOURCES = (NUMBER_FROM_ROOM, NUMBER_SEQUENCE, NUMBER_NONE)
NAME_SOURCES = (NAME_FROM_ROOM, NAME_CONSTANT, NAME_NONE)

# Warning kinds. Revit gives each of these its own FailureDefinitionId, so the
# collection layer can classify by GUID instead of by message text — which
# matters because the text is localised and this office runs a Chinese UI.
KIND_NOT_PLACED = 'not_placed'
KIND_NOT_ENCLOSED = 'not_enclosed'
KIND_REDUNDANT = 'redundant'
KIND_BOUNDARY_OVERLAP = 'boundary_overlap'
KIND_OTHER = 'other'

KIND_LABELS = {
    KIND_NOT_PLACED: u'未放置',
    KIND_NOT_ENCLOSED: u'未封閉',
    KIND_REDUNDANT: u'多餘面積（同一區域有多個）',
    KIND_BOUNDARY_OVERLAP: u'面積邊界線重疊',
    KIND_OTHER: u'其他警告',
}

# Area states the audit reports.
AREA_OK = u'正常'
AREA_NOT_PLACED = u'未放置'
AREA_NOT_ENCLOSED = u'未封閉'
AREA_REDUNDANT = u'多餘面積'
AREA_WARNING = u'其他警告'

AREA_STATES = (AREA_OK, AREA_NOT_PLACED, AREA_NOT_ENCLOSED, AREA_REDUNDANT,
               AREA_WARNING)

BLOCK_ROOM_NOT_PLACED = u'房間本身未放置'
BLOCK_NO_SEED_POINT = u'取不到可用的種子點'
BLOCK_ALREADY_COVERED = u'該封閉區域已有面積'
BLOCK_SELF_COVERED = u'與本次先前的面積落在同一封閉區域'
BLOCK_NUMBER_COLLISION = u'編號與既有面積重複'
BLOCK_SELF_COLLISION = u'本次產生的編號互相重複'
BLOCK_NOT_ENCLOSED = u'試放後未圍出面積（邊界未封閉）'


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value).strip()
    except Exception:
        return str(value).strip()


def _number(value, fallback=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


# --- geometry --------------------------------------------------------------

def _edges(loops):
    """Every edge of every loop, as ``((x1, y1), (x2, y2))``.

    Outer loop and holes are walked the same way on purpose: the even-odd rule
    below then treats a hole's interior as outside without needing to know
    which loop is which, and Revit does not promise an order.
    """
    for loop in loops or []:
        points = [item for item in loop or []]
        if len(points) < 3:
            continue
        for index in range(len(points)):
            yield points[index], points[(index + 1) % len(points)]


def polygon_area(loop):
    """Signed shoelace area. Negative means the loop winds clockwise."""
    points = [item for item in loop or []]
    if len(points) < 3:
        return 0.0
    total = 0.0
    for index in range(len(points)):
        x1, y1 = points[index]
        x2, y2 = points[(index + 1) % len(points)]
        total += float(x1) * float(y2) - float(x2) * float(y1)
    return total / 2.0


def point_in_loops(point, loops):
    """Even-odd crossing test against all loops at once.

    Counting crossings to the right of the point and flipping a parity bit
    means a hole flips it back — a point in the middle of a donut reports
    False, which is the answer that matters when deciding whether a seed will
    land in a real enclosed region.

    The ``(y1 > y) != (y2 > y)`` guard is the half-open rule: an edge counts
    only if the ray passes its lower endpoint, so a ray through a shared vertex
    is counted once rather than twice or zero times.
    """
    if point is None or not loops:
        return False
    x = _number(point[0])
    y = _number(point[1])
    inside = False
    for (x1, y1), (x2, y2) in _edges(loops):
        y1 = _number(y1)
        y2 = _number(y2)
        if (y1 > y) != (y2 > y):
            crossing = _number(x1) + (y - y1) / (y2 - y1) * (
                _number(x2) - _number(x1))
            if crossing > x:
                inside = not inside
    return inside


def _scan_spans(loops, y):
    """Interior x-intervals where a horizontal line at ``y`` cuts the region."""
    crossings = []
    for (x1, y1), (x2, y2) in _edges(loops):
        y1 = _number(y1)
        y2 = _number(y2)
        if y1 == y2:
            continue
        low, high = (y1, y2) if y1 < y2 else (y2, y1)
        if y <= low or y >= high:
            continue
        crossings.append(
            _number(x1) + (y - y1) / (y2 - y1) * (_number(x2) - _number(x1)))
    crossings.sort()
    spans = []
    index = 0
    while index + 1 < len(crossings):
        spans.append((crossings[index], crossings[index + 1]))
        index += 2
    return spans


def interior_point(loops):
    """A point guaranteed to sit inside the region, or ``None``.

    A centroid is not good enough: for an L-shaped room or a ring it can land
    outside the region entirely, and a seed placed there produces an area that
    either fails or belongs to the wrong space.

    Instead the region is cut by horizontal lines chosen *between* consecutive
    distinct vertex heights — so no scan line ever passes through a vertex, the
    degenerate case that makes crossing counts unreliable — and the midpoint of
    the widest resulting interior span is returned. Widest is preferred because
    it is the furthest from any boundary, which keeps the seed away from
    rounding trouble at the edges.
    """
    heights = sorted(set(_number(point[1])
                         for loop in loops or [] for point in loop or []))
    if len(heights) < 2:
        return None
    best = None
    for index in range(len(heights) - 1):
        y = (heights[index] + heights[index + 1]) / 2.0
        for left, right in _scan_spans(loops, y):
            width = right - left
            if width <= 0:
                continue
            if best is None or width > best[0]:
                best = (width, ((left + right) / 2.0, y))
    return best[1] if best else None


def seed_from_room(room):
    """``(point, note)`` for one room, or ``(None, reason)``.

    The room's own location point is preferred because it is where the tag
    already sits, but it is verified first: after a boundary edit Revit leaves
    the point where it was, and a point outside its own room would seed an area
    in the neighbouring space.
    """
    if not room.get('placed'):
        return None, BLOCK_ROOM_NOT_PLACED
    loops = room.get('loops')
    point = room.get('point_xy')
    if point is not None and loops and point_in_loops(point, loops):
        return (_number(point[0]), _number(point[1])), u''
    fallback = interior_point(loops) if loops else None
    if fallback is not None:
        return fallback, u'LocationPoint 不在房間內，改用邊界內部點'
    if point is not None:
        return (_number(point[0]), _number(point[1])), u'沒有邊界資料，直接用 LocationPoint'
    return None, BLOCK_NO_SEED_POINT


# --- audit -----------------------------------------------------------------

def warning_kinds(warnings):
    """Kinds present in a warning list, tolerating plain strings.

    The collection layer hands back dicts carrying a GUID-derived ``kind``;
    tests and any older caller may pass bare text, which counts as a generic
    warning rather than being silently dropped.
    """
    kinds = set()
    for entry in warnings or []:
        if isinstance(entry, dict):
            kinds.add(entry.get('kind') or KIND_OTHER)
        else:
            kinds.add(KIND_OTHER)
    return kinds


def area_status(area, warnings=None):
    """One state per area, in a fixed priority.

    Unplaced is checked first because an unplaced area has no geometry to
    measure, then enclosure, then redundancy. Revit reports each of these with
    its own failure definition, but the model's own numbers are checked too —
    a zero area is not enclosed whether or not a warning survived.
    """
    kinds = warning_kinds(warnings)
    if not area.get('placed') or KIND_NOT_PLACED in kinds:
        return AREA_NOT_PLACED
    if _number(area.get('area_sqft')) <= 0.0 or KIND_NOT_ENCLOSED in kinds:
        return AREA_NOT_ENCLOSED
    if KIND_REDUNDANT in kinds:
        return AREA_REDUNDANT
    if kinds:
        return AREA_WARNING
    return AREA_OK


def audit_lines(report):
    lines = [u'共 {} 個面積'.format(report['total']), u'']
    counts = report['counts']
    for status in AREA_STATES:
        lines.append(u'　{}：{} 個'.format(status, counts.get(status, 0)))
    problems = (report['total'] - counts.get(AREA_OK, 0))
    lines.append(u'')
    if not problems:
        lines.append(u'✓ 沒有異常。')
    else:
        lines.append(u'✗ 有 {} 個面積需要處理，明細見輸出視窗。'.format(problems))
    return u'\n'.join(lines)


def build_audit(areas, warnings=None):
    """Classify every collected area; ``warnings`` maps area id -> [text]."""
    warnings = warnings or {}
    counts = {}
    rows = []
    for area in areas or []:
        texts = warnings.get(area.get('id')) or []
        status = area_status(area, texts)
        counts[status] = counts.get(status, 0) + 1
        row = dict(area)
        row['status'] = status
        row['warnings'] = list(texts)
        rows.append(row)
    rows.sort(key=sort_key)
    return {
        'total': len(areas or []),
        'counts': counts,
        'rows': rows,
        'flagged_ids': [row['id'] for row in rows if row['status'] != AREA_OK],
    }


# --- ordering --------------------------------------------------------------

def natural_key(value):
    """``A2`` before ``A10``. Reuses the room-number key so 編號 sort once."""
    return sort_logic.room_number_sort_key(value)


def sort_key(record):
    """Deterministic run order, so a generated sequence is reproducible.

    View position is deliberately not used. Sorting by where things sit on
    screen makes the numbering depend on which view happened to be open, and
    the same button press would then produce different numbers.
    """
    return (_number(record.get('level_elevation')),
            natural_key(record.get('number') or record.get('room_number')),
            int(_number(record.get('id'))))


# --- planning --------------------------------------------------------------

def _sequence_value(options, index):
    start = int(_number(options.get('start'), 1.0))
    pad = int(_number(options.get('pad'), 0.0))
    number = u'{}'.format(start + index)
    if pad > 0:
        number = number.zfill(pad)
    return u'{}{}'.format(_text(options.get('prefix')), number)


def assign_values(seeds, number_source, name_source, options=None):
    """Attach the 編號 and 名稱 each seed would receive."""
    if number_source not in NUMBER_SOURCES:
        raise ValueError('unknown number_source: {}'.format(number_source))
    if name_source not in NAME_SOURCES:
        raise ValueError('unknown name_source: {}'.format(name_source))
    options = options or {}
    rows = []
    for index, seed in enumerate(seeds or []):
        row = dict(seed)
        if number_source == NUMBER_FROM_ROOM:
            row['number'] = _text(seed.get('room_number'))
        elif number_source == NUMBER_SEQUENCE:
            row['number'] = _sequence_value(options, index)
        else:
            row['number'] = u''
        if name_source == NAME_FROM_ROOM:
            row['name'] = _text(seed.get('room_name'))
        elif name_source == NAME_CONSTANT:
            row['name'] = _text(options.get('constant'))
        else:
            row['name'] = u''
        rows.append(row)
    return rows


def build_plan(rooms, existing_areas, number_source=NUMBER_FROM_ROOM,
               name_source=NAME_FROM_ROOM, options=None):
    """Work out which rooms would seed a new area, and which must not.

    Coverage is checked against the areas already in the model, which is what
    makes a second run a no-op instead of a second stack of duplicates.
    Collision between two *new* areas cannot be settled here — their boundaries
    do not exist until Revit computes them — so that falls to the trial pass.
    """
    options = options or {}
    ordered = sorted(rooms or [], key=sort_key)

    seeds = []
    blocked = []
    for room in ordered:
        point, note = seed_from_room(room)
        if point is None:
            blocked.append({'record': room, 'reason': note})
            continue
        seed = dict(room)
        seed['point_xy'] = point
        seed['note'] = note
        covered_by = None
        for area in existing_areas or []:
            if point_in_loops(point, area.get('loops')):
                covered_by = area
                break
        if covered_by is not None:
            blocked.append({
                'record': room, 'reason': BLOCK_ALREADY_COVERED,
                'covered_by': covered_by})
            continue
        seeds.append(seed)

    rows = assign_values(seeds, number_source, name_source, options)

    existing_numbers = set()
    for area in existing_areas or []:
        number = _text(area.get('number'))
        if number:
            existing_numbers.add(number.upper())

    creates = []
    claimed = set()
    for row in rows:
        number = _text(row.get('number'))
        if number:
            key = number.upper()
            if key in existing_numbers:
                blocked.append({'record': row,
                                'reason': BLOCK_NUMBER_COLLISION})
                continue
            if key in claimed:
                blocked.append({'record': row,
                                'reason': BLOCK_SELF_COLLISION})
                continue
            claimed.add(key)
        creates.append(row)

    return {
        'number_source': number_source,
        'name_source': name_source,
        'total_rooms': len(rooms or []),
        'existing_areas': len(existing_areas or []),
        'creates': creates,
        'blocked': blocked,
        'trialled': False,
    }


def apply_trial_result(plan, trial_rows):
    """Fold Revit's own answer back into the plan.

    ``trial_rows`` maps a room id to ``{'enclosed': bool, 'self_covered': bool,
    'area_sqft': float}`` as observed while the areas were briefly placed
    inside a rolled-back Transaction. Anything Revit refused to enclose, or
    that landed inside an area created earlier in the same run, moves out of
    the write list — which is the only reliable way to know before committing.
    """
    by_id = {}
    for key, value in (trial_rows or {}).items():
        by_id[key] = value

    writes = []
    blocked = list(plan['blocked'])
    for row in plan['creates']:
        result = by_id.get(row.get('id'))
        if result is None:
            blocked.append({'record': row, 'reason': BLOCK_NOT_ENCLOSED})
            continue
        if result.get('self_covered'):
            blocked.append({'record': row, 'reason': BLOCK_SELF_COVERED})
            continue
        if not result.get('enclosed'):
            blocked.append({'record': row, 'reason': BLOCK_NOT_ENCLOSED})
            continue
        write = dict(row)
        write['area_sqft'] = _number(result.get('area_sqft'))
        writes.append(write)

    updated = dict(plan)
    updated['writes'] = writes
    updated['blocked'] = blocked
    updated['trialled'] = True
    return updated


def sequence_is_gapped(plan):
    """A blocked row under a generated sequence means the numbering skips.

    Copying a room number carries no order, so a partial run is fine there; a
    sequence that jumps from A3 to A5 is not, and is refused instead.
    """
    return (plan.get('number_source') == NUMBER_SEQUENCE
            and bool(plan.get('blocked')))


def gross_scheme_warning(plan):
    """Whether most seeds collapsed into one region — the wrong-scheme signal.

    A gross-area scheme measures one region per floor, so seeding it per room
    makes every seed after the first land inside the first area. Saying that
    plainly beats reporting 「阻擋 47 筆」 with no explanation.
    """
    blocked = plan.get('blocked') or []
    covered = len([row for row in blocked
                   if row.get('reason') == BLOCK_SELF_COVERED])
    attempted = covered + len(plan.get('writes') or [])
    if attempted < 3 or covered < attempted * 0.6:
        return u''
    return (u'※ {} 個種子落在同一個封閉區域裡。'
            u'這個面積計畫可能是「一層一個大區」的類型，'
            u'不適合逐房放置面積。'.format(covered))


def plan_lines(plan, scheme_label, view_label):
    lines = [
        u'面積計畫：{}'.format(_text(scheme_label)),
        u'面積平面：{}'.format(_text(view_label)),
        u'',
        u'掃描房間 {} 個，既有面積 {} 個'.format(
            plan['total_rooms'], plan['existing_areas']),
        u'',
    ]
    rows = plan.get('writes') if plan.get('trialled') else plan.get('creates')
    rows = rows or []
    verb = u'將建立' if plan.get('trialled') else u'預計建立'
    lines.append(u'{} {} 個面積：'.format(verb, len(rows)))
    for row in rows[:20]:
        label = u'　{}'.format(_text(row.get('number')) or u'(自動編號)')
        name = _text(row.get('name'))
        if name:
            label += u'　{}'.format(name)
        if row.get('area_sqft'):
            label += u'　{:.2f} m²'.format(
                _number(row.get('area_sqft')) * SQ_FT_TO_SQ_M)
        if row.get('note'):
            label += u'　（{}）'.format(row['note'])
        lines.append(label)
    if len(rows) > 20:
        lines.append(u'　…（其餘 {} 個見輸出視窗）'.format(len(rows) - 20))

    blocked = plan.get('blocked') or []
    if blocked:
        lines.append(u'')
        lines.append(u'✗ 阻擋 {} 個：'.format(len(blocked)))
        reasons = {}
        for row in blocked:
            reasons[row['reason']] = reasons.get(row['reason'], 0) + 1
        for reason in sorted(reasons, key=lambda item: -reasons[item]):
            lines.append(u'　{}：{} 個'.format(reason, reasons[reason]))
    hint = gross_scheme_warning(plan)
    if hint:
        lines.append(u'')
        lines.append(hint)
    return u'\n'.join(lines)
