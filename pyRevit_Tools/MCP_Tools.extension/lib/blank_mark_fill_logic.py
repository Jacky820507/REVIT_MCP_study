# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Pure rules for 門窗編號補空值 (JAC 10.09).

The companion to :mod:`duplicate_mark_logic`, and deliberately built on its
identity rules — 「什麼算空白」 and 「什麼算同一個編號」 must have exactly one
definition, or the check button and the fill button will disagree about the
same model.

Scope is strictly *blank* 編號. Overwriting a 編號 that already has a value is
renumbering, not filling, and is a different operation with different risks.

Two things here exist because filling naively creates the very defect 10.08
looks for:

- a value written to a *type* parameter lands once per type, not once per
  opening, so type-scoped writes are collapsed and the preview says how many
  樘 each one moves;
- a generated value that matches an 編號 already in the model, or another value
  generated in the same run, is refused rather than written.
"""

import duplicate_mark_logic as identity


# Where the value lands. A type parameter is shared, an instance parameter is
# not, and that difference decides how many writes a plan actually contains.
TARGET_INSTANCE = 'instance'
TARGET_TYPE = 'type'

SOURCE_TYPE_MARK = 'type_mark'
SOURCE_TYPE_NAME = 'type_name'
SOURCE_OTHER = 'other'
SOURCE_SEQUENCE = 'sequence'
SOURCE_CONSTANT = 'constant'

SOURCE_LABELS = {
    SOURCE_TYPE_MARK: u'由類型註記帶入',
    SOURCE_TYPE_NAME: u'由類型名稱帶入',
    SOURCE_OTHER: u'由其他參數帶入',
    SOURCE_SEQUENCE: u'產生流水號',
    SOURCE_CONSTANT: u'填入固定文字',
}

STATUS_OK = 'ok'

BLOCK_NOT_WRITABLE = u'參數不可寫入'
BLOCK_EMPTY_SOURCE = u'來源值也是空的'
BLOCK_COLLISION = u'與既有編號重複'
BLOCK_SELF_COLLISION = u'本次產生的值互相重複'


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value).strip()
    except Exception:
        return str(value).strip()


def is_blank(value):
    """Blank by the same folding 10.08 uses — ``'　'`` is blank, not an 編號."""
    return not identity.normalize_mark(value)


# Doors before windows, matching the D/W convention 門窗表 is written in.
# Sorting the labels themselves would order 窗 (U+7A97) before 門 (U+9580),
# which is a codepoint accident rather than a decision.
CATEGORY_ORDER = (u'門', u'窗')


def category_rank(value):
    text = _text(value)
    if text in CATEGORY_ORDER:
        return (CATEGORY_ORDER.index(text), u'')
    return (len(CATEGORY_ORDER), text)


def sort_key(record):
    """Deterministic run order, so a sequence is reproducible.

    Elevation first (低樓層先編), then 門 before 窗, then type, then ElementId.
    View position is deliberately not used: it would make the result depend on
    which view happened to be open.
    """
    try:
        elevation = float(record.get('level_elevation') or 0.0)
    except (TypeError, ValueError):
        elevation = 0.0
    try:
        element_id = int(record.get('id') or 0)
    except (TypeError, ValueError):
        element_id = 0
    return (elevation,
            category_rank(record.get('category')),
            _text(record.get('type_name')),
            element_id)


def target_key(record, target_scope):
    """Identity of the thing being written to — the type, or the opening."""
    if target_scope == TARGET_TYPE:
        return (TARGET_TYPE, record.get('type_id'))
    return (TARGET_INSTANCE, record.get('id'))


def group_targets(records, target_scope):
    """Collapse records onto write targets, preserving run order.

    A type-scoped write touches one parameter no matter how many blank
    openings share that type, so emitting one write per opening would write the
    same cell repeatedly and report a count nobody can reconcile.
    """
    order = []
    targets = {}
    for record in sorted(records, key=sort_key):
        key = target_key(record, target_scope)
        if key not in targets:
            targets[key] = {'key': key, 'records': [], 'record': record}
            order.append(key)
        targets[key]['records'].append(record)
    return [targets[key] for key in order]


def _source_value(target, source, options, index):
    record = target['record']
    if source == SOURCE_TYPE_MARK:
        return _text(record.get('type_mark'))
    if source == SOURCE_TYPE_NAME:
        return _text(record.get('type_name'))
    if source == SOURCE_OTHER:
        return _text(record.get('other'))
    if source == SOURCE_CONSTANT:
        return _text(options.get('constant'))
    if source == SOURCE_SEQUENCE:
        try:
            start = int(options.get('start', 1))
        except (TypeError, ValueError):
            start = 1
        try:
            pad = int(options.get('pad', 0))
        except (TypeError, ValueError):
            pad = 0
        number = u'{}'.format(start + index)
        if pad > 0:
            number = number.zfill(pad)
        return u'{}{}'.format(_text(options.get('prefix')), number)
    raise ValueError('unknown source: {}'.format(source))


def build_plan(records, target_scope=TARGET_INSTANCE,
               source=SOURCE_TYPE_MARK, options=None,
               exclude_curtain=True):
    """Work out what would be written, and what must not be.

    Returns writes, blocked rows, and the counts behind both, so the preview
    can show the whole picture instead of a number with no provenance.
    """
    if target_scope not in (TARGET_INSTANCE, TARGET_TYPE):
        raise ValueError('unknown target_scope: {}'.format(target_scope))
    if source not in SOURCE_LABELS:
        raise ValueError('unknown source: {}'.format(source))
    options = options or {}

    kept, excluded = identity.split_curtain(records, exclude_curtain)

    blank = []
    existing = set()
    for record in kept:
        if is_blank(record.get('current')):
            blank.append(record)
        else:
            # Everything already numbered is what a generated value must not
            # collide with, including the rows this run will not touch.
            existing.add(identity.normalize_mark(record.get('current')))

    targets = group_targets(blank, target_scope)

    writes = []
    blocked = []
    claimed = {}
    for index, target in enumerate(targets):
        record = target['record']
        row = {
            'key': target['key'],
            'record': record,
            'records': target['records'],
            'instance_count': len(target['records']),
        }
        if _text(record.get('writable')) != STATUS_OK:
            row['reason'] = u'{}（{}）'.format(
                BLOCK_NOT_WRITABLE, _text(record.get('writable')))
            blocked.append(row)
            continue
        value = _source_value(target, source, options, index)
        row['value'] = value
        if is_blank(value):
            row['reason'] = BLOCK_EMPTY_SOURCE
            blocked.append(row)
            continue
        normalized = identity.normalize_mark(value)
        if normalized in existing:
            row['reason'] = BLOCK_COLLISION
            blocked.append(row)
            continue
        if normalized in claimed:
            # Two different types resolving to one 編號 is exactly the 10.08
            # defect; writing it would mean this button manufactures the thing
            # the sibling button reports.
            row['reason'] = BLOCK_SELF_COLLISION
            blocked.append(row)
            continue
        claimed[normalized] = row
        writes.append(row)

    return {
        'target_scope': target_scope,
        'source': source,
        'total': len(records or []),
        'excluded_curtain': excluded,
        'already_filled': len(kept) - len(blank),
        'blank_instances': len(blank),
        'writes': writes,
        'blocked': blocked,
        'affected_instances': sum(row['instance_count'] for row in writes),
    }


def sequence_is_gapped(plan):
    """A blocked row inside a sequence run means the numbering would skip.

    Constant and copy-from sources do not care about order, so a partial apply
    is fine there; a sequence that silently jumps from D3 to D5 is not.
    """
    return plan['source'] == SOURCE_SEQUENCE and bool(plan['blocked'])


def plan_lines(plan, target_label, exclude_curtain=True):
    """Summary text for the confirm dialog; the table goes to the output pane."""
    lines = [
        u'寫入目標：{}'.format(target_label),
        u'取值方式：{}'.format(SOURCE_LABELS[plan['source']]),
        u'',
        u'掃描 {} 樘'.format(plan['total']),
    ]
    if exclude_curtain:
        lines.append(u'排除帷幕牆門窗：{} 樘'.format(
            len(plan['excluded_curtain'])))
    lines.append(u'已有編號、不動：{} 樘'.format(plan['already_filled']))
    lines.append(u'編號空白：{} 樘'.format(plan['blank_instances']))
    lines.append(u'')
    if plan['target_scope'] == TARGET_TYPE:
        lines.append(u'將寫入 {} 個類型參數，影響 {} 樘'.format(
            len(plan['writes']), plan['affected_instances']))
    else:
        lines.append(u'將寫入 {} 樘'.format(len(plan['writes'])))
    for row in plan['writes'][:20]:
        record = row['record']
        label = u'　{} / {} → {}'.format(
            _text(record.get('family_name')),
            _text(record.get('type_name')), row['value'])
        if plan['target_scope'] == TARGET_TYPE and row['instance_count'] > 1:
            label += u'（{} 樘）'.format(row['instance_count'])
        lines.append(label)
    if len(plan['writes']) > 20:
        lines.append(u'　…（其餘 {} 筆見輸出視窗）'.format(
            len(plan['writes']) - 20))
    if plan['blocked']:
        lines.append(u'')
        lines.append(u'✗ 阻擋 {} 筆：'.format(len(plan['blocked'])))
        reasons = {}
        for row in plan['blocked']:
            reasons[row['reason']] = reasons.get(row['reason'], 0) + 1
        for reason in sorted(reasons, key=lambda item: -reasons[item]):
            lines.append(u'　{}：{} 筆'.format(reason, reasons[reason]))
    return u'\n'.join(lines)
