# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Pure rules for the 門窗編號重複 check (JAC 10.08).

Records arrive from Revit as plain dicts, so every rule here is unit-testable
without a document open. The button decides *how* to read a 編號 and whether an
instance sits in a curtain wall; what counts as a duplicate lives here.

Two readings of 「編號重複」 exist in practice and they are not interchangeable,
so the caller has to say which one it wants:

``DISTINCT_BY_TYPE``
    The 門窗表 reading. 編號 identifies a *type*, so many instances legitimately
    share ``D1``; the defect is ``D1`` naming two different types, because the
    schedule then prices one 編號 at two sizes.

``DISTINCT_BY_INSTANCE``
    The strict reading. Every element must carry its own 編號, so any repeat is
    a defect. Correct when 編號 is written per opening (常見於門窗清單逐樘標號).
"""

import re
import unicodedata

import room_takeoff_sources_logic as sort_logic


DISTINCT_BY_TYPE = 'type'
DISTINCT_BY_INSTANCE = 'instance'

MODE_LABELS = {
    DISTINCT_BY_TYPE: u'同一編號用在不同類型',
    DISTINCT_BY_INSTANCE: u'同一編號用在多個元件',
}


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value).strip()
    except Exception:
        return str(value).strip()


def normalize_mark(value):
    """Fold the differences that are typos rather than distinct 編號.

    ``Ｄ１``, ``D 1`` and ``d1`` are the same 編號 to a human reading the
    schedule, and treating them as three keys is the failure mode that lets a
    real collision through. NFKC folds fullwidth to ASCII first, then spaces
    (including 全形空白) go, then case.
    """
    text = unicodedata.normalize('NFKC', _text(value))
    return re.sub(u'[\\s　]', u'', text).upper()


def split_curtain(records, exclude_curtain=True):
    """``(kept, excluded)`` — curtain-hosted openings are separated, not dropped.

    Doors and windows swapped into a curtain grid inherit the panel family's
    naming and routinely share a blank or repeated 編號. They are a different
    conversation from a real 門窗表 collision, which is why JAC labels this
    check 帷幕X. They are still counted and reported so the number is auditable.
    """
    kept = []
    excluded = []
    for record in records or []:
        if exclude_curtain and record.get('curtain'):
            excluded.append(record)
        else:
            kept.append(record)
    return kept, excluded


def _type_identity(record):
    """What counts as "a different type" — family plus type, not type alone.

    Two families can each own a type called ``單開``; comparing type names only
    would call that one type and hide a genuine collision.
    """
    return (_text(record.get('family_name')), _text(record.get('type_name')))


def analyze(records, distinct_by=DISTINCT_BY_TYPE, exclude_curtain=True):
    """Group records by normalized 編號 and keep only the colliding groups."""
    if distinct_by not in (DISTINCT_BY_TYPE, DISTINCT_BY_INSTANCE):
        raise ValueError('unknown distinct_by: {}'.format(distinct_by))

    kept, excluded = split_curtain(records, exclude_curtain)

    blank = []
    buckets = {}
    order = []
    for record in kept:
        key = normalize_mark(record.get('mark'))
        if not key:
            # Blank 編號 is a separate defect (JAC 10.09) and must never be
            # bucketed together — every blank would read as one huge collision.
            blank.append(record)
            continue
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(record)

    groups = []
    for key in order:
        members = buckets[key]
        identities = []
        for record in members:
            identity = _type_identity(record)
            if identity not in identities:
                identities.append(identity)
        if distinct_by == DISTINCT_BY_TYPE:
            if len(identities) < 2:
                continue
        elif len(members) < 2:
            continue
        variants = []
        for record in members:
            raw = _text(record.get('mark'))
            if raw and raw not in variants:
                variants.append(raw)
        groups.append({
            'key': key,
            'variants': variants,
            'records': list(members),
            'type_names': [name for unused, name in identities],
            'identities': identities,
            'instance_count': len(members),
            'type_count': len(identities),
        })

    groups.sort(key=lambda group: sort_logic.room_number_sort_key(
        group['key']))
    return {
        'mode': distinct_by,
        'total': len(records or []),
        'checked': len(kept),
        'excluded_curtain': excluded,
        'blank': blank,
        'groups': groups,
        'flagged_instances': sum(
            group['instance_count'] for group in groups),
    }


def group_label(group):
    """One line per colliding 編號, e.g. ``D1  2 種類型 / 7 樘``."""
    label = u'{}　{} 種類型 / {} 樘'.format(
        group['key'], group['type_count'], group['instance_count'])
    if len(group['variants']) > 1:
        label += u'　（寫法不一致：{}）'.format(u'、'.join(group['variants']))
    return label


def report_lines(report, parameter_label, exclude_curtain=True):
    """Summary text for the alert; the full table goes to the output window."""
    lines = [
        u'編號來源：{}'.format(parameter_label),
        u'判定方式：{}'.format(MODE_LABELS[report['mode']]),
        u'',
        u'掃描 {} 樘，實際檢查 {} 樘'.format(
            report['total'], report['checked']),
    ]
    if exclude_curtain:
        lines.append(u'排除帷幕牆門窗：{} 樘'.format(
            len(report['excluded_curtain'])))
    else:
        lines.append(u'帷幕牆門窗：一併檢查')
    lines.append(u'編號空白：{} 樘'.format(len(report['blank'])))
    lines.append(u'')
    if not report['groups']:
        lines.append(u'✓ 沒有重複編號。')
        return u'\n'.join(lines)
    lines.append(u'✗ 重複編號 {} 組，共 {} 樘：'.format(
        len(report['groups']), report['flagged_instances']))
    for group in report['groups'][:20]:
        lines.append(u'　{}'.format(group_label(group)))
    if len(report['groups']) > 20:
        lines.append(u'　…（其餘 {} 組見輸出視窗）'.format(
            len(report['groups']) - 20))
    return u'\n'.join(lines)


def flagged_ids(report):
    """Element ids behind every collision, for selecting them in Revit."""
    ids = []
    for group in report['groups']:
        for record in group['records']:
            value = record.get('id')
            if value is not None and value not in ids:
                ids.append(value)
    return ids
