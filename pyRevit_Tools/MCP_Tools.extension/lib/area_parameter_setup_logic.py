# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Pure rules for 新增 AREA 基本項目 — JAC 04.06.

The Area buttons in this extension all stop and ask the user which parameter
holds 戶別, 分類, 棟別, 權屬 — because those are project parameters and every
office names them differently. This is the button that creates them in the
first place, so a fresh project can actually run the rest.

**The GUID is the parameter, not the name.** A shared parameter is identified
by its GUID; two projects that each invent a 戶別 with a fresh random GUID end
up with two parameters that look identical in every dialog and are not the same
parameter — they will not schedule together, will not tag consistently, and map
differently on IFC export. So when this tool has to mint a definition itself it
derives the GUID **deterministically from the name**, and the same name yields
the same parameter in every project it touches.

That is still second best. An office with its own shared-parameter file already
has the real GUIDs, and the button prefers that file when one is available; the
derived GUIDs exist so a project with no file is not stuck, and the report says
plainly which of the two happened.

Nothing here touches Revit.
"""

import hashlib


KIND_TEXT = 'text'
KIND_INTEGER = 'integer'
KIND_NUMBER = 'number'
KIND_AREA = 'area'
KIND_LENGTH = 'length'
KIND_YESNO = 'yesno'

KIND_LABELS = {
    KIND_TEXT: u'文字',
    KIND_INTEGER: u'整數',
    KIND_NUMBER: u'數值',
    KIND_AREA: u'面積',
    KIND_LENGTH: u'長度',
    KIND_YESNO: u'是/否',
}

BLOCK_ALREADY_BOUND = u'目標已綁定同名參數'
BLOCK_BAD_NAME = u'名稱空白或含不合法字元'

# Revit rejects these in parameter names.
ILLEGAL_CHARACTERS = u'\\:{}[]|;<>?`~'

# Namespace for derived GUIDs. Fixed forever: changing it would make every
# project created after the change disagree with every project before it.
GUID_NAMESPACE = u'RevitMCP.AreaParameters.v1'

# The set the other Area buttons expect to find. Names are defaults the user
# edits before anything is created — see
# domain/user-specified-runtime-parameters.md.
DEFAULT_PARAMETERS = (
    {'name': u'棟別', 'kind': KIND_TEXT,
     'used_by': u'面積計算式、無障礙樓梯數量檢核（分棟）'},
    {'name': u'戶別', 'kind': KIND_TEXT,
     'used_by': u'面積計算式（依戶分組列式）'},
    {'name': u'分類', 'kind': KIND_TEXT,
     'used_by': u'面積計算式（居室／陽台／梯廳…）'},
    {'name': u'權屬', 'kind': KIND_TEXT,
     'used_by': u'專有共用分類（專有／共用）'},
    {'name': u'公設分攤', 'kind': KIND_TEXT,
     'used_by': u'專有共用分類（大公／小公）'},
)


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value).strip()
    except Exception:
        return str(value).strip()


def _fold(value):
    return u''.join(_text(value).split()).lower()


def kind_label(kind):
    return KIND_LABELS.get(kind, _text(kind))


def default_parameters():
    """A fresh copy, so the caller can edit names without touching the spec."""
    return [dict(item) for item in DEFAULT_PARAMETERS]


def deterministic_guid(name, namespace=GUID_NAMESPACE):
    """A stable GUID for a parameter name — same name, same parameter.

    Derived rather than random so that 戶別 created in one project is the *same*
    shared parameter as 戶別 created in the next. Built as a UUID v3 (MD5
    namespace UUID) so the value is well-formed rather than 16 arbitrary bytes.
    """
    digest = bytearray(hashlib.md5(
        (_text(namespace) + u'|' + _text(name)).encode('utf-8')).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30   # version 3
    digest[8] = (digest[8] & 0x3F) | 0x80   # RFC 4122 variant
    hexed = u''.join(u'{:02x}'.format(byte) for byte in digest)
    return u'{}-{}-{}-{}-{}'.format(hexed[0:8], hexed[8:12], hexed[12:16],
                                    hexed[16:20], hexed[20:32])


def name_problem(name):
    """``''`` when the name is usable as a Revit parameter name."""
    cleaned = _text(name)
    if not cleaned:
        return BLOCK_BAD_NAME
    for character in ILLEGAL_CHARACTERS:
        if character in cleaned:
            return BLOCK_BAD_NAME
    return u''


def build_plan(specs, existing_names=None, namespace=GUID_NAMESPACE):
    """Split the requested parameters into what gets created and what does not.

    Matching against the target is by **name**, because that is what a person
    sees in the parameter dialog: a second 戶別 with a different GUID would be
    indistinguishable there and is exactly the confusion worth preventing.
    """
    taken = set(_fold(value) for value in existing_names or [])

    create = []
    blocked = []
    for spec in specs or []:
        item = dict(spec)
        problem = name_problem(item.get('name'))
        if problem:
            blocked.append({'record': item, 'reason': problem})
            continue
        if _fold(item.get('name')) in taken:
            blocked.append({'record': item, 'reason': BLOCK_ALREADY_BOUND})
            continue
        item['guid'] = item.get('guid') or deterministic_guid(
            item.get('name'), namespace)
        create.append(item)

    counts = {}
    for entry in blocked:
        counts[entry['reason']] = counts.get(entry['reason'], 0) + 1

    return {
        'create': create,
        'blocked': blocked,
        'block_counts': counts,
        'count': len(create),
        'names': [item['name'] for item in create],
    }


def has_work(plan):
    return bool(plan.get('create'))


def plan_lines(plan, from_shared_file=False):
    lines = []
    if not has_work(plan):
        lines.append(u'沒有要建立的參數，模型不會變更。')
    else:
        lines.append(u'將建立並綁定到「面積」的 {} 個專案參數：'.format(
            plan['count']))
        for item in plan['create']:
            lines.append(u'　{}（{}）　{}'.format(
                item['name'], kind_label(item.get('kind')),
                item.get('used_by') or u''))

    if plan['blocked']:
        lines.append(u'')
        lines.append(u'略過 {} 個：'.format(len(plan['blocked'])))
        for reason in sorted(plan['block_counts']):
            lines.append(u'　{}：{} 個'.format(reason,
                                              plan['block_counts'][reason]))

    lines.append(u'')
    if from_shared_file:
        lines.append(u'定義來自你指定的共用參數檔，GUID 是貴單位既有的。')
    else:
        lines.append(u'GUID 由參數名稱推導而得（同名在每個專案都會是同一個'
                     u'共用參數）。若貴單位已有共用參數檔，改用那個檔會更好'
                     u'——那裡的 GUID 才是你們的標準。')
    return u'\n'.join(lines)
