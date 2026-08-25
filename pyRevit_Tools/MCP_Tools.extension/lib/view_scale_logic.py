# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Pure rules for 視圖／圖紙比例管理 (JAC 02.06 + 02.07).

The two JAC entries are one operation in Revit. A sheet has no scale of its
own — what reads as 「圖紙比例」 is the scale of the views placed on it — so
choosing 「這幾張圖紙」 and choosing 「這幾個視圖」 are two ways of naming the
same set of ``View.Scale`` values, and both end in the same write.

That has one consequence this module exists to enforce: a view placed on three
sheets is still one scale. Collecting per viewport would plan three writes to
one property and report a number the user cannot reconcile against the model,
so records are keyed by view.
"""

import re
import unicodedata


# Revit accepts 1..24000 for View.Scale; outside that the write throws rather
# than clamping, so it is rejected before the Transaction opens.
MIN_SCALE = 1
MAX_SCALE = 24000

STATUS_OK = 'ok'

BLOCK_NO_PARAMETER = u'此視圖類型沒有比例'
BLOCK_READONLY = u'比例唯讀'
BLOCK_TEMPLATE = u'比例由視圖樣板控制'


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value).strip()
    except Exception:
        return str(value).strip()


def parse_scale(value):
    """``'1:100'``, ``'1/100'``, ``'100'``, ``'１：１００'`` -> ``100``.

    Returns ``None`` when the text is not a scale this can act on. Accepting
    the ``1:x`` forms matters because that is how the number is written on
    every drawing, and refusing it would train people to type the bare number
    they did not mean.
    """
    text = unicodedata.normalize('NFKC', _text(value))
    text = re.sub(u'[\\s　]', u'', text)
    if not text:
        return None
    match = re.match(u'^1\\s*[:/：]\\s*(\\d+)$', text)
    if match:
        text = match.group(1)
    if not re.match(u'^\\d+$', text):
        return None
    scale = int(text)
    if scale < MIN_SCALE or scale > MAX_SCALE:
        return None
    return scale


def scale_label(scale):
    try:
        value = int(scale)
    except (TypeError, ValueError):
        return u'(無)'
    if value <= 0:
        return u'(無)'
    return u'1:{}'.format(value)


def scale_distribution(records):
    """``[{scale, count, names}]`` sorted by scale — the read-only answer.

    This is 02.06/02.07 used as a survey: 「這批圖現在各是什麼比例」, which is
    the question people open twenty views one at a time to answer.
    """
    buckets = {}
    for record in records or []:
        scale = record.get('scale')
        key = int(scale) if scale else 0
        entry = buckets.setdefault(key, {'scale': key, 'count': 0,
                                         'names': []})
        entry['count'] += 1
        entry['names'].append(_text(record.get('name')))
    ordered = []
    for key in sorted(buckets):
        entry = buckets[key]
        entry['names'].sort()
        ordered.append(entry)
    return ordered


def build_plan(records, target_scale):
    """Split the views into what will change, what already matches, what cannot.

    ``already`` is kept separate from ``writes`` rather than folded into it:
    rewriting a value that is already correct dirties the model and inflates
    the reported count for no benefit.
    """
    scale = parse_scale(target_scale)
    if scale is None:
        raise ValueError(u'比例必須是 1~{} 的整數，或 1:N 格式。'.format(
            MAX_SCALE))

    writes = []
    already = []
    blocked = []
    for record in sorted(records or [],
                         key=lambda item: _text(item.get('name'))):
        status = _text(record.get('writable'))
        if status != STATUS_OK:
            blocked.append({'record': record, 'reason': status or
                            BLOCK_READONLY})
            continue
        current = record.get('scale')
        try:
            current = int(current)
        except (TypeError, ValueError):
            current = 0
        if current == scale:
            already.append(record)
            continue
        writes.append({'record': record, 'old': current, 'new': scale})
    return {
        'target_scale': scale,
        'total': len(records or []),
        'writes': writes,
        'already': already,
        'blocked': blocked,
    }


def survey_lines(records):
    lines = [u'共 {} 個視圖'.format(len(records or [])), u'']
    distribution = scale_distribution(records)
    if not distribution:
        lines.append(u'沒有可讀取比例的視圖。')
        return u'\n'.join(lines)
    lines.append(u'目前比例分布：')
    for entry in distribution:
        sample = u'、'.join(entry['names'][:3])
        if len(entry['names']) > 3:
            sample += u' …'
        lines.append(u'　{}　{} 個　{}'.format(
            scale_label(entry['scale']), entry['count'], sample))
    if len(distribution) > 1:
        lines.append(u'')
        lines.append(u'※ 這批圖有 {} 種比例，出圖前通常應統一。'.format(
            len(distribution)))
    return u'\n'.join(lines)


def plan_lines(plan):
    lines = [
        u'目標比例：{}'.format(scale_label(plan['target_scale'])),
        u'',
        u'掃描 {} 個視圖'.format(plan['total']),
        u'已經是目標比例、不動：{} 個'.format(len(plan['already'])),
        u'',
        u'將變更 {} 個視圖：'.format(len(plan['writes'])),
    ]
    for row in plan['writes'][:20]:
        lines.append(u'　{}　{} → {}'.format(
            _text(row['record'].get('name'))[:40],
            scale_label(row['old']), scale_label(row['new'])))
    if len(plan['writes']) > 20:
        lines.append(u'　…（其餘 {} 個見輸出視窗）'.format(
            len(plan['writes']) - 20))
    if plan['blocked']:
        lines.append(u'')
        lines.append(u'✗ 阻擋 {} 個：'.format(len(plan['blocked'])))
        reasons = {}
        for row in plan['blocked']:
            reasons[row['reason']] = reasons.get(row['reason'], 0) + 1
        for reason in sorted(reasons, key=lambda item: -reasons[item]):
            lines.append(u'　{}：{} 個'.format(reason, reasons[reason]))
    return u'\n'.join(lines)


def sheets_needing_viewport_resync(plan):
    """Sheets whose viewport title types may no longer match the new scale.

    domain/viewport-type-scale-sync.md derives the viewport title type from the
    placed view's scale, so changing the scale silently invalidates the title
    that was synced to the old one. Naming the affected sheets lets the user
    re-run that sync instead of discovering it at print time.
    """
    sheets = []
    for row in plan['writes']:
        for number in row['record'].get('sheet_numbers') or []:
            if number not in sheets:
                sheets.append(number)
    sheets.sort()
    return sheets
