# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Pure rules for 明細表選取範圍生成圖紙 (JAC 02.03).

Rows added to a Sheet List schedule become **placeholder sheets**: real
``ViewSheet`` elements that hold a number and a name but carry no titleblock
and cannot take a viewport. Revit converts them one at a time, by right-click,
and a drawing register of eighty rows therefore costs eighty round trips
through a dialog. This turns the schedule range into one batch.

Two things shape the module.

**Selection is not readable from a schedule.** ``Selection.GetElementIds()``
returns selected *elements* and ``TableSectionData`` reads any cell by index,
but nothing in the API exposes the highlighted range. So the scope is resolved
from whatever the selection happens to contain, falling back to a picker over
every placeholder — the caller decides, and neither path depends on
undocumented schedule behaviour.

**Order has to be natural.** A register sorted as text puts A-10 before A-2,
and a picker in that order is one the user has to read twice. Sheet numbers go
through the same key as room numbers so 編號 sorts one way in this codebase.

Nothing here touches Revit; the caller supplies plain dicts.
"""

import re

import room_takeoff_sources_logic as sort_logic


BLOCK_NOT_PLACEHOLDER = u'已經是正式圖紙，不需轉換'
BLOCK_NOT_A_SHEET = u'不是圖紙元素'

WARN_NO_NUMBER = u'圖號空白，轉出來的圖紙也會沒有圖號'
WARN_NO_NAME = u'圖名空白'

# Everything up to the last run of digits: "A-101" -> "A-", "SK12" -> "SK".
# Taken from the raw number rather than the normalised one, because this is
# shown to a person and folding would change what they see.
_PREFIX = re.compile(r'^(.*?)(\d+)\s*$')
NO_PREFIX = u'（無前綴）'


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value).strip()
    except Exception:
        return str(value).strip()


def sheet_prefix(number):
    """The grouping label for a sheet number, as typed."""
    raw = _text(number)
    if not raw:
        return NO_PREFIX
    match = _PREFIX.match(raw)
    if not match or not match.group(1):
        return NO_PREFIX
    return match.group(1)


def sheet_sort_key(record):
    """A-2 before A-10. Reuses the room-number key so 編號 sorts once."""
    return sort_logic.room_number_sort_key(_text(record.get('number')))


def block_reason(record):
    if not record.get('is_sheet', True):
        return BLOCK_NOT_A_SHEET
    if not record.get('is_placeholder'):
        return BLOCK_NOT_PLACEHOLDER
    return u''


def warnings_for(record):
    notes = []
    if not _text(record.get('number')):
        notes.append(WARN_NO_NUMBER)
    if not _text(record.get('name')):
        notes.append(WARN_NO_NAME)
    return notes


def group_by_prefix(records):
    """``[{'prefix':…, 'records':[…]}]``, each group naturally ordered.

    Registers are organised by discipline prefix, and converting 「所有 A- 開頭
    的」 with one titleblock then 「所有 S- 開頭的」 with another is the usual
    shape of the job. Grouping makes that selection possible without a second
    mode.
    """
    buckets = {}
    order = []
    for record in records or []:
        prefix = sheet_prefix(record.get('number'))
        if prefix not in buckets:
            buckets[prefix] = []
            order.append(prefix)
        buckets[prefix].append(record)
    groups = []
    for prefix in sorted(order):
        groups.append({
            'prefix': prefix,
            'records': sorted(buckets[prefix], key=sheet_sort_key),
        })
    return groups


def build_plan(records):
    """Split the candidates into what will convert and what will not."""
    convert = []
    blocked = []
    warnings = []
    for record in records or []:
        reason = block_reason(record)
        if reason:
            blocked.append({'record': record, 'reason': reason})
            continue
        convert.append(record)
        for note in warnings_for(record):
            warnings.append({'record': record, 'note': note})

    convert.sort(key=sheet_sort_key)
    return {
        'convert': convert,
        'blocked': blocked,
        'warnings': warnings,
        'groups': group_by_prefix(convert),
        'count': len(convert),
        'ids': [record.get('id') for record in convert],
    }


def has_work(plan):
    return bool(plan.get('convert'))


def plan_lines(plan):
    lines = []
    if not has_work(plan):
        lines.append(u'沒有可轉換的佔位圖紙。')
    else:
        lines.append(u'將轉換 {} 張佔位圖紙為正式圖紙：'.format(plan['count']))
        for group in plan['groups']:
            numbers = [_text(record.get('number')) or u'(無圖號)'
                       for record in group['records']]
            shown = u'、'.join(numbers[:8])
            if len(numbers) > 8:
                shown += u' …等 {} 張'.format(len(numbers))
            lines.append(u'　{}（{} 張）：{}'.format(
                group['prefix'], len(group['records']), shown))

    if plan['warnings']:
        lines.append(u'')
        lines.append(u'注意 {} 項：'.format(len(plan['warnings'])))
        for entry in plan['warnings'][:8]:
            lines.append(u'　{}　{}'.format(
                _text(entry['record'].get('number')) or u'(無圖號)',
                entry['note']))
        if len(plan['warnings']) > 8:
            lines.append(u'　…（其餘 {} 項見輸出視窗）'.format(
                len(plan['warnings']) - 8))

    if plan['blocked']:
        lines.append(u'')
        lines.append(u'略過 {} 項：'.format(len(plan['blocked'])))
        counts = {}
        for entry in plan['blocked']:
            counts[entry['reason']] = counts.get(entry['reason'], 0) + 1
        for reason in sorted(counts):
            lines.append(u'　{}：{} 項'.format(reason, counts[reason]))

    return u'\n'.join(lines)
