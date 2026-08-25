# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Pure rules for 面積重新編號 (JAC 01.03).

Renumbering differs from filling a blank in one way that decides the whole
design: the numbers being handed out are **already in use by the same set of
elements**. Renumbering A1→A2 while A2→A1 is a swap, and writing it in one pass
leaves a moment where two areas both claim A2. Revit only warns about duplicate
numbers rather than refusing them, so a naive pass can silently commit a
duplicate and call it success.

So the plan detects that case and, when it occurs, routes the write through a
temporary numbering pass first. :func:`needs_two_phase` is what decides; the
caller does the two writes.

A collision with an area *outside* the selected range is a different problem —
no ordering of writes fixes it, because the other area is not being renumbered.
Those rows are blocked instead.

All coordinates are millimetres in model space, never view space: ordering by
where things sit on screen would make the result depend on which view happened
to be open, but model XY is stable, so 「由左至右」 means the same thing on every
run.
"""

import area_placement_logic as base
import duplicate_mark_logic as identity


ORDER_BY_NUMBER = 'number'
ORDER_BY_NAME = 'name'
ORDER_BY_AREA_DESC = 'area_desc'
ORDER_BY_AREA_ASC = 'area_asc'
ORDER_BY_ROW = 'row'
ORDER_BY_COLUMN = 'column'

ORDER_LABELS = {
    ORDER_BY_NUMBER: u'現有編號（自然序）',
    ORDER_BY_NAME: u'面積名稱',
    ORDER_BY_AREA_DESC: u'面積大小（大→小）',
    ORDER_BY_AREA_ASC: u'面積大小（小→大）',
    ORDER_BY_ROW: u'位置：由左至右、由上至下',
    ORDER_BY_COLUMN: u'位置：由上至下、由左至右',
}

POSITION_ORDERS = (ORDER_BY_ROW, ORDER_BY_COLUMN)

# Areas in one row of a plan are never at exactly the same Y, so a band width
# decides what counts as "the same row". 1 m is a sensible starting point for
# rooms; the caller must be able to override it.
DEFAULT_BAND_MM = 1000.0

BLOCK_OUTSIDE_COLLISION = u'新編號已被範圍外的面積佔用'
BLOCK_DUPLICATE_TARGET = u'本次產生的編號互相重複'
BLOCK_NOT_WRITABLE = u'編號無法寫入'

SQ_FT_TO_SQ_M = 0.09290304


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


def _key(value):
    """Comparison key for a 編號.

    Reuses the folding the 門窗編號重複 check already defines (NFKC, spaces
    removed, uppercased), so ``A1`` and ``Ａ１`` count as the same number here
    exactly as they do there. Two definitions of 「同一個編號」 in one codebase
    is how a collision check and a renumber end up disagreeing.
    """
    return identity.normalize_mark(value)


# --- ordering --------------------------------------------------------------

def _band(rows, primary, secondary, band_mm, primary_reverse,
          secondary_reverse):
    """Group by one axis into bands, then sort within each band by the other.

    Rows are formed from the *first* member's coordinate rather than a running
    average, so a long diagonal run of areas cannot drift the band sideways and
    swallow a genuinely different row.
    """
    ordered = sorted(rows, key=lambda row: primary(row),
                     reverse=primary_reverse)
    bands = []
    for row in ordered:
        value = primary(row)
        if bands and abs(value - bands[-1]['anchor']) <= band_mm:
            bands[-1]['rows'].append(row)
        else:
            bands.append({'anchor': value, 'rows': [row]})
    result = []
    for band in bands:
        result.extend(sorted(band['rows'],
                             key=lambda row: secondary(row),
                             reverse=secondary_reverse))
    return result


def order_rows(rows, strategy=ORDER_BY_NUMBER, band_mm=DEFAULT_BAND_MM):
    """Deterministic order for the run; unplaced areas always come last.

    An unplaced area has no coordinate, so it cannot take part in a positional
    order at all. Dropping it would silently exclude it from renumbering, so it
    is appended in natural-number order instead.
    """
    rows = list(rows or [])
    if strategy in (ORDER_BY_NUMBER, ORDER_BY_NAME, ORDER_BY_AREA_DESC,
                    ORDER_BY_AREA_ASC):
        if strategy == ORDER_BY_NUMBER:
            return sorted(rows, key=base.sort_key)
        if strategy == ORDER_BY_NAME:
            return sorted(rows, key=lambda row: (
                _number(row.get('level_elevation')),
                base.natural_key(row.get('name')),
                int(_number(row.get('id')))))
        reverse = strategy == ORDER_BY_AREA_DESC
        return sorted(rows, key=lambda row: (
            _number(row.get('level_elevation')),
            -_number(row.get('area_sqft')) if reverse
            else _number(row.get('area_sqft')),
            int(_number(row.get('id')))))

    if strategy not in POSITION_ORDERS:
        raise ValueError('unknown strategy: {}'.format(strategy))

    placed = [row for row in rows if row.get('point_xy')]
    unplaced = sorted([row for row in rows if not row.get('point_xy')],
                      key=base.sort_key)

    def x_of(row):
        return _number(row['point_xy'][0])

    def y_of(row):
        return _number(row['point_xy'][1])

    result = []
    # Levels are ordered first regardless of strategy: a plan's reading order
    # only means anything within one floor.
    elevations = sorted(set(_number(row.get('level_elevation'))
                            for row in placed))
    for elevation in elevations:
        floor = [row for row in placed
                 if _number(row.get('level_elevation')) == elevation]
        if strategy == ORDER_BY_ROW:
            # Top row first (Y descending), left to right within the row.
            result.extend(_band(floor, y_of, x_of, band_mm, True, False))
        else:
            # Leftmost column first, top to bottom within the column.
            result.extend(_band(floor, x_of, y_of, band_mm, False, True))
    result.extend(unplaced)
    return result


# --- numbering -------------------------------------------------------------

def format_number(prefix, value, pad):
    text = u'{}'.format(value)
    if pad > 0:
        text = text.zfill(pad)
    return u'{}{}'.format(_text(prefix), text)


def assign_numbers(ordered, prefix=u'', start=1, pad=0, per_level=False):
    """Attach ``target`` to every row, in the order given."""
    rows = []
    counters = {}
    for index, row in enumerate(ordered or []):
        if per_level:
            key = _number(row.get('level_elevation'))
            counters.setdefault(key, int(start))
            value = counters[key]
            counters[key] += 1
        else:
            value = int(start) + index
        item = dict(row)
        item['target'] = format_number(prefix, value, int(pad))
        rows.append(item)
    return rows


def needs_two_phase(rows):
    """Whether a straight pass would create a transient duplicate 編號.

    True exactly when some row's target is currently held by a *different* row
    in the same run — the swap case. Revit only warns about duplicates rather
    than rejecting them, so without this the run would commit a duplicate and
    still report success.
    """
    holders = {}
    for row in rows or []:
        current = _key(row.get('number'))
        if current:
            holders[current] = row.get('id')
    for row in rows or []:
        holder = holders.get(_key(row.get('target')))
        if holder is not None and holder != row.get('id'):
            return True
    return False


def temporary_numbers(rows, taken=None, marker=u'~R'):
    """Collision-proof placeholder numbers for the first pass of a swap.

    The marker is extended until it clashes with nothing at all, so the
    temporary pass cannot itself create the duplicate it exists to avoid.
    """
    reserved = set(_key(value) for value in (taken or []))
    for row in rows or []:
        reserved.add(_key(row.get('number')))
        reserved.add(_key(row.get('target')))
    prefix = marker
    while any(key.startswith(_key(prefix)) for key in reserved if key):
        prefix += u'~'
    return [u'{}{}'.format(prefix, index + 1) for index in range(len(rows))]


def build_plan(areas, strategy=ORDER_BY_NUMBER, prefix=u'', start=1, pad=0,
               per_level=False, band_mm=DEFAULT_BAND_MM, outside_numbers=None):
    """Work out the new numbering, what stays put, and what cannot be done.

    ``outside_numbers`` are the 編號 held by areas in the same scheme that are
    *not* in this run. A target landing on one of those is refused: reordering
    the writes cannot help, because nothing is going to free that number.
    """
    ordered = order_rows(areas, strategy, band_mm)
    rows = assign_numbers(ordered, prefix, start, pad, per_level)

    outside = set(_key(value) for value in (outside_numbers or []) if
                  _key(value))

    blocked = []
    candidates = []
    seen = {}
    for row in rows:
        target = _key(row.get('target'))
        if target in outside:
            blocked.append({'record': row, 'reason': BLOCK_OUTSIDE_COLLISION})
            continue
        if target in seen:
            # Reachable through a per-level restart, where two floors both
            # produce A1. Catching it here is also what keeps an unchanged row
            # from being stolen from: its target equals its own number, so any
            # other row aiming at that number lands in this branch.
            blocked.append({'record': row, 'reason': BLOCK_DUPLICATE_TARGET})
            continue
        seen[target] = row.get('id')
        candidates.append(row)

    writes = []
    unchanged = []
    for row in candidates:
        if _key(row.get('number')) == _key(row.get('target')):
            unchanged.append(row)
        else:
            writes.append(row)

    return {
        'strategy': strategy,
        'total': len(areas or []),
        'writes': writes,
        'unchanged': unchanged,
        'blocked': blocked,
        # Decided over unchanged rows too. They cannot actually be the victim
        # of a collision — the duplicate-target check above already rules that
        # out — but passing the full set costs nothing and keeps this correct
        # if the target generator ever changes.
        'two_phase': needs_two_phase(candidates) and bool(writes),
    }


def plan_lines(plan, scheme_label, scope_label):
    lines = [
        u'面積計畫：{}'.format(_text(scheme_label)),
        u'範圍：{}'.format(_text(scope_label)),
        u'排序依據：{}'.format(ORDER_LABELS.get(plan['strategy'],
                                            plan['strategy'])),
        u'',
        u'掃描 {} 個面積'.format(plan['total']),
        u'編號不變、不動：{} 個'.format(len(plan['unchanged'])),
        u'',
        u'將重新編號 {} 個：'.format(len(plan['writes'])),
    ]
    for row in plan['writes'][:20]:
        lines.append(u'　{} → {}　{}'.format(
            _text(row.get('number')) or u'(空白)', row['target'],
            _text(row.get('name'))[:20]))
    if len(plan['writes']) > 20:
        lines.append(u'　…（其餘 {} 個見輸出視窗）'.format(
            len(plan['writes']) - 20))
    if plan['two_phase']:
        lines.append(u'')
        lines.append(
            u'※ 新舊編號互相交換，將先寫入暫時編號再寫入正式編號，'
            u'避免中途出現重複編號。')
    if plan['blocked']:
        lines.append(u'')
        lines.append(u'✗ 阻擋 {} 個：'.format(len(plan['blocked'])))
        reasons = {}
        for row in plan['blocked']:
            reasons[row['reason']] = reasons.get(row['reason'], 0) + 1
        for reason in sorted(reasons, key=lambda item: -reasons[item]):
            lines.append(u'　{}：{} 個'.format(reason, reasons[reason]))
    return u'\n'.join(lines)
