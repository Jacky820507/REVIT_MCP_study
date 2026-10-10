# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""批量建立明細表／批量新增欄位的純邏輯。

不碰 Revit、不碰 WPF，IronPython 2.7 與 CPython 3 都能跑（測試在
``tests/test_schedule_batch_logic.py``）。Revit 端的讀寫在
``schedule_batch_revit.py``；兩顆按鈕（建立明細表、新增明細表欄位）共用這裡。

欄位一律以**名稱**比對（不分大小寫）：同一個名稱在不同品類對到的可排程欄位
不同（各自的參數），所以「選欄位」選的是名稱，實際加進哪個欄位由 Revit 端
依各明細表的可用欄位解析。
"""

# Revit 不允許出現在檢視名稱裡的字元。
FORBIDDEN_NAME_CHARS = u'\\:{}[]|;<>?`~'

DEFAULT_TEMPLATE = u'{category}明細表'

CONFLICT_SKIP = 'skip'
CONFLICT_SUFFIX = 'suffix'


def text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value)
    except Exception:
        return u''


def sanitize_name(name):
    """把 Revit 不允許的字元換成 ``-``；空字串回 ``明細表``。"""
    cleaned = u''.join(u'-' if c in FORBIDDEN_NAME_CHARS else c
                       for c in text(name)).strip()
    return cleaned or u'明細表'


def render_name(template, category):
    """名稱樣板的 ``{category}`` 換成品類名稱。

    樣板沒有 ``{category}`` 時，名稱後面補上品類，否則一次建多個品類會得到
    同一個名稱而全部撞名。
    """
    category = text(category).strip()
    template = text(template).strip() or DEFAULT_TEMPLATE
    name = template.replace(u'{category}', category)
    if category and category not in name:
        name = name + category
    return sanitize_name(name)


def plan_creations(categories, template, existing_names, on_conflict):
    """決定每個品類要建的名稱與狀態。

    ``existing_names`` 是專案裡既有明細表名稱。回傳依 ``categories`` 順序的
    ``[{'category', 'name', 'status', 'note'}]``，``status`` 為：

    - ``create``：會建立；
    - ``skip``：撞名且選擇略過（不動既有明細表）。

    ``suffix`` 模式撞名時改成 ``名稱 (2)``、``名稱 (3)``…，批次內互相撞名
    也一併處理。名稱不分大小寫比對，因為 Revit 的檢視名稱不分大小寫。
    """
    taken = set(text(n).lower() for n in existing_names)
    plans = []
    for category in categories:
        name = render_name(template, category)
        status, note = 'create', u''
        if name.lower() in taken:
            if on_conflict == CONFLICT_SUFFIX:
                number = 2
                candidate = u'{} ({})'.format(name, number)
                while candidate.lower() in taken:
                    number += 1
                    candidate = u'{} ({})'.format(name, number)
                note = u'名稱已存在，改為「{}」'.format(candidate)
                name = candidate
            else:
                status, note = 'skip', u'名稱已存在，略過'
        if status == 'create':
            taken.add(name.lower())
        plans.append({'category': text(category), 'name': name,
                      'status': status, 'note': note})
    return plans


def field_union(names_by_group):
    """多個群組（品類或明細表）各自的欄位名稱 → 聯集。

    回傳 ``[(name, [group, ...])]``：``name`` 保留第一次出現的大小寫，依名稱
    排序；``groups`` 是有這個欄位的群組，依傳入順序。用來讓使用者看到
    「這個欄位在幾個品類有」，選了只在部分品類存在的欄位時不會意外。
    """
    order = []
    display = {}
    owners = {}
    for group, names in names_by_group:
        seen = set()
        for name in names:
            key = text(name).strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            if key not in display:
                display[key] = text(name).strip()
                order.append(key)
                owners[key] = []
            owners[key].append(group)
    order.sort(key=lambda k: display[k].lower())
    return [(display[k], owners[k]) for k in order]


def resolve_fields(wanted, available):
    """把想要的欄位名稱對到可用欄位。

    ``wanted`` 與 ``available`` 都是名稱清單，不分大小寫。回傳
    ``(found, missing)``：``found`` 是可用欄位的**原樣名稱**（依 wanted 順序、
    去重），``missing`` 是對不到的 wanted。
    """
    by_key = {}
    for name in available:
        by_key.setdefault(text(name).strip().lower(), text(name).strip())
    found, missing, seen = [], [], set()
    for name in wanted:
        key = text(name).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        if key in by_key:
            found.append(by_key[key])
        else:
            missing.append(text(name).strip())
    return found, missing


def split_by_presence(found, present_names):
    """``found`` 裡已經在明細表上的歸 ``already``，其餘歸 ``to_add``。"""
    present = set(text(n).strip().lower() for n in present_names)
    to_add, already = [], []
    for name in found:
        (already if name.lower() in present else to_add).append(name)
    return to_add, already


def summarize(plans):
    """預覽用的計數。``plans`` 每一項至少有 ``status``。"""
    counts = {}
    for plan in plans:
        counts[plan['status']] = counts.get(plan['status'], 0) + 1
    return counts
