# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Pure rules for 區域線重新生成 (JAC 01.05).

Two jobs that share one notion of "the same line":

**依房間邊界生成**
    Take the boundary curves Revit already computed for the rooms on a level
    and redraw them as area boundary lines. The rooms are the architecture's
    own answer to where the walls are, so the area plan stops drifting from the
    model every time a wall moves.

**清理重複區域線**
    Collapse boundary lines that sit on top of each other. Duplicates are what
    raises 「面積邊界線重疊」, and they accumulate quietly because nothing in
    Revit stops you drawing the same line twice.

Both lean on :func:`area_copy_logic.curve_key`, which is the single definition
of when two curves are the same line — direction-independent and quantised to a
tolerance. Having a second definition here is how a generator and a cleaner end
up disagreeing about their own output.

One consequence worth stating because it changes what the user should pick:
with ``Finish`` boundaries, two rooms sharing a wall each report their own face,
so a shared wall yields **two parallel lines** a wall-thickness apart rather
than one. ``Center`` puts both on the same curve and they collapse to one.
"""

import area_copy_logic as curves
import room_takeoff_sources_logic as sort_logic


DEFAULT_TOLERANCE_MM = curves.DEFAULT_TOLERANCE_MM

SKIP_ALREADY_PRESENT = u'目標平面已有相同的區域線'
SKIP_SHARED_BOUNDARY = u'與其他房間共用同一條邊界'
BLOCK_NO_GEOMETRY = u'讀不到邊界幾何'

REASON_DUPLICATE = u'與其他區域線完全重合'


def _reason_counts(rows):
    counts = {}
    for row in rows or []:
        counts[row['reason']] = counts.get(row['reason'], 0) + 1
    return counts


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value).strip()
    except Exception:
        return str(value).strip()


def room_summary(room_curves):
    """``[{'room_id', 'room_number', 'segments'}]`` for the room picker.

    Boundary curves arrive one row per *segment*, so a room with twelve walls
    is twelve rows. Anything choosing rooms has to fold them back up first —
    picking by segment would be meaningless.
    """
    buckets = {}
    order = []
    for row in room_curves or []:
        key = row.get('room_id')
        if key not in buckets:
            buckets[key] = {'room_id': key,
                            'room_number': _text(row.get('room_number')),
                            'room_name': _text(row.get('room_name')),
                            'segments': 0}
            order.append(key)
        buckets[key]['segments'] += 1
    return [buckets[key] for key in order]


def room_sort_key(item):
    """A-2 before A-10. Reuses the room-number key so 編號 sorts once."""
    return sort_logic.room_number_sort_key(_text(item.get('room_number')))


def filter_rooms(room_curves, room_ids=None):
    """Keep only the segments belonging to the chosen rooms.

    ``room_ids`` of ``None`` means every room — the whole-level behaviour this
    button had before rooms could be picked individually.
    """
    if room_ids is None:
        return list(room_curves or [])
    wanted = set(room_ids)
    return [row for row in room_curves or []
            if row.get('room_id') in wanted]


def plan_from_rooms(room_curves, existing_lines, tolerance_mm=None,
                    clear_existing=False):
    """Which room boundary curves become new area boundary lines.

    ``clear_existing`` changes the meaning of the existing lines rather than
    just adding deletions: once they are all going away, none of them can make
    a new curve redundant, so nothing is skipped as already-present.
    """
    tolerance = (DEFAULT_TOLERANCE_MM if tolerance_mm is None
                 else float(tolerance_mm))

    present = set()
    if not clear_existing:
        for line in existing_lines or []:
            key = line.get('key') or curves.curve_key(line.get('points'),
                                                      tolerance)
            if key is not None:
                present.add(key)

    draws = []
    skipped = []
    blocked = []
    seen = set()
    for row in room_curves or []:
        key = row.get('key') or curves.curve_key(row.get('points'), tolerance)
        if key is None:
            blocked.append({'record': row, 'reason': BLOCK_NO_GEOMETRY})
            continue
        if key in present:
            skipped.append({'record': row, 'reason': SKIP_ALREADY_PRESENT})
            continue
        if key in seen:
            # Adjacent rooms both report the wall between them. Under Center
            # boundaries those are the same curve, so the second one is not a
            # second wall — it is the same wall seen from the other side.
            skipped.append({'record': row, 'reason': SKIP_SHARED_BOUNDARY})
            continue
        seen.add(key)
        item = dict(row)
        item['key'] = key
        draws.append(item)

    deletes = list(existing_lines or []) if clear_existing else []
    return {
        'mode': 'rooms',
        'tolerance_mm': tolerance,
        'clear_existing': bool(clear_existing),
        'source_count': len(room_curves or []),
        'existing_count': len(existing_lines or []),
        'draws': draws,
        'deletes': deletes,
        'skipped': skipped,
        'blocked': blocked,
    }


def plan_dedup(existing_lines, tolerance_mm=None):
    """Keep one line per distinct curve, delete the rest.

    The survivor is the first one seen in the collection order, which is stable
    for a given model — so re-running finds nothing left to do rather than
    churning a different element each time.
    """
    tolerance = (DEFAULT_TOLERANCE_MM if tolerance_mm is None
                 else float(tolerance_mm))
    keeps = []
    deletes = []
    blocked = []
    seen = {}
    for line in existing_lines or []:
        key = line.get('key') or curves.curve_key(line.get('points'),
                                                  tolerance)
        if key is None:
            blocked.append({'record': line, 'reason': BLOCK_NO_GEOMETRY})
            continue
        if key in seen:
            row = dict(line)
            row['duplicate_of'] = seen[key]
            deletes.append({'record': row, 'reason': REASON_DUPLICATE})
            continue
        seen[key] = line.get('id')
        keeps.append(line)
    return {
        'mode': 'dedup',
        'tolerance_mm': tolerance,
        'existing_count': len(existing_lines or []),
        'draws': [],
        'keeps': keeps,
        'deletes': deletes,
        'skipped': [],
        'blocked': blocked,
    }


def delete_ids(plan):
    """Element ids to remove, whichever plan shape produced them."""
    ids = []
    for row in plan.get('deletes') or []:
        record = row.get('record') if isinstance(row, dict) and \
            'record' in row else row
        value = (record or {}).get('id')
        if value is not None and value not in ids:
            ids.append(value)
    return ids


def has_work(plan):
    return bool(plan.get('draws')) or bool(delete_ids(plan))


def plan_summary(plan, view_label, location_label=u''):
    lines = [u'面積平面：{}'.format(view_label)]
    if plan['mode'] == 'rooms':
        if location_label:
            lines.append(u'邊界位置：{}'.format(location_label))
        lines.append(u'')
        lines.append(u'房間邊界共 {} 段，目前區域線 {} 條'.format(
            plan['source_count'], plan['existing_count']))
        if plan['clear_existing']:
            lines.append(u'將先刪除既有區域線：{} 條'.format(
                len(plan['deletes'])))
        lines.append(u'將新增區域線：{} 條'.format(len(plan['draws'])))
        for reason, count in sorted(_reason_counts(
                plan['skipped'] + plan['blocked']).items()):
            lines.append(u'　{}：{} 段'.format(reason, count))
    else:
        lines.append(u'')
        lines.append(u'目前區域線 {} 條'.format(plan['existing_count']))
        lines.append(u'保留 {} 條，刪除重複 {} 條'.format(
            len(plan['keeps']), len(plan['deletes'])))
        for reason, count in sorted(_reason_counts(plan['blocked']).items()):
            lines.append(u'　{}：{} 條'.format(reason, count))
    lines.append(u'')
    if not has_work(plan):
        lines.append(u'✓ 沒有需要變更的區域線。')
    return u'\n'.join(lines)
