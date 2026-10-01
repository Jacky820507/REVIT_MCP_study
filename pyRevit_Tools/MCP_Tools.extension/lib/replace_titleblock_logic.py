# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""批量換圖框——不碰 Revit API 的部分（IronPython 2.7 / CPython 3 雙相容）.

圖紙紀錄（record）格式::

    {'id': int, 'number': u'A-101', 'name': u'一層平面圖',
     'titleblocks': [{'id': int, 'type_id': int, 'label': u'族群：類型'}]}

規則（使用者 2026-10-01 決定）：

- 一張圖紙上的圖框**全部**換掉；有多個時照換，但在預覽標示出來。
- 沒有圖框的圖紙**略過**，不幫它放新圖框（那是「佔位圖紙轉正式圖紙」的事）。
- 已經是目標類型的圖框不動。
"""

from placeholder_sheet_logic import sheet_sort_key


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value)
    except Exception:
        return unicode(value)  # noqa: F821 - IronPython 2.7


def current_label(record):
    """清單上顯示的「目前圖框」，多個時以「、」串起來。"""
    labels = []
    for block in record.get('titleblocks') or []:
        label = _text(block.get('label'))
        if label not in labels:
            labels.append(label)
    if not labels:
        return u'(無圖框)'
    return u'、'.join(labels)


def sheet_label(record):
    return u'{}　{}　〔{}〕'.format(
        _text(record.get('number')) or u'(無圖號)',
        _text(record.get('name')) or u'(無圖名)',
        current_label(record))


def sort_records(records):
    return sorted(records or [], key=sheet_sort_key)


def build_plan(records, target_type_id):
    """回傳 ``{'change', 'unchanged', 'skipped', 'multi', 'count'}``。

    ``change``：``[(record, [block, ...])]``，block 是要換類型的圖框。
    ``count``：要換的圖框總數（不是圖紙數）。
    """
    change = []
    unchanged = []
    skipped = []
    multi = []
    count = 0
    for record in sort_records(records):
        blocks = list(record.get('titleblocks') or [])
        if not blocks:
            skipped.append({'record': record, 'reason': u'圖紙上沒有圖框'})
            continue
        if len(blocks) > 1:
            multi.append(record)
        todo = [block for block in blocks
                if block.get('type_id') != target_type_id]
        if not todo:
            unchanged.append(record)
            continue
        change.append((record, todo))
        count += len(todo)
    return {
        'change': change,
        'unchanged': unchanged,
        'skipped': skipped,
        'multi': multi,
        'count': count,
    }


def has_work(plan):
    return bool(plan['change'])


def plan_lines(plan):
    lines = [u'將更換：{} 張圖紙、{} 個圖框'.format(
        len(plan['change']), plan['count'])]
    if plan['unchanged']:
        lines.append(u'已是目標圖框（不動）：{} 張'.format(
            len(plan['unchanged'])))
    if plan['skipped']:
        lines.append(u'沒有圖框（略過）：{} 張'.format(len(plan['skipped'])))
    if plan['multi']:
        lines.append(u'一張圖紙上有多個圖框（全部換掉）：{} 張'.format(
            len(plan['multi'])))
    return u'\n'.join(lines)


# --- 換完之後對齊 ----------------------------------------------------------
#
# 換類型後圖框的插入點不變，但新舊族群的幾何相對插入點可能不同，外框就會
# 跑掉。做法是換之前記下舊圖框外框的某個角點，換完再把新圖框的同一個角點
# 搬回那裡——每張圖紙對齊「自己原本的位置」，不需要參考圖紙。
# 與 MCP 工具 align_titleblocks_on_sheets 用同一套角點定義（外框 bounding box）。

ANCHOR_NONE = 'none'
ANCHORS = (
    (u'不對齊（只換類型）', ANCHOR_NONE),
    (u'左下角對齊原位置', 'bottom-left'),
    (u'右下角對齊原位置', 'bottom-right'),
    (u'左上角對齊原位置', 'top-left'),
    (u'右上角對齊原位置', 'top-right'),
    (u'中心對齊原位置', 'center'),
)

# 1 ft = 304.8 mm；0.1 mm 以內視為已對齊，與 MCP 工具預設相同。
FEET_PER_MM = 1.0 / 304.8
TOLERANCE_FT = 0.1 * FEET_PER_MM


def anchor_point(min_xy, max_xy, anchor):
    """外框 ``(min_x, min_y)``、``(max_x, max_y)`` 的角點；不認得的 anchor 回 ``None``。"""
    if min_xy is None or max_xy is None:
        return None
    (x0, y0), (x1, y1) = min_xy, max_xy
    points = {
        'top-left': (x0, y1),
        'top-right': (x1, y1),
        'bottom-left': (x0, y0),
        'bottom-right': (x1, y0),
        'center': ((x0 + x1) / 2.0, (y0 + y1) / 2.0),
    }
    return points.get(anchor)


def align_delta(old_point, new_point, tolerance=TOLERANCE_FT):
    """把新角點搬回舊角點要移動的 ``(dx, dy)``；誤差內或缺點時回 ``None``。"""
    if old_point is None or new_point is None:
        return None
    dx = old_point[0] - new_point[0]
    dy = old_point[1] - new_point[1]
    if (dx * dx + dy * dy) ** 0.5 < tolerance:
        return None
    return (dx, dy)
