# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""門窗圖例的排版與參數文字——純邏輯，不碰 Revit。

流程圖的六步裡，前五步都是 Revit API 的事（見 ``legend_sources``），只有最後
一步「**底部對齊平均展開**」是真正的計算，加上「選擇列出參數」要決定文字長
什麼樣。兩件都在這裡，因此可以在 CPython 下被 pytest 蓋到。

兩個排版決定值得寫下來，因為選錯的結果看起來只是「有點醜」，實際上是錯的：

**底部對齊，不是置中或置頂。** 一扇 300 cm 的窗和一扇 210 cm 的門並排時，
置中會讓兩者的窗台浮在不同高度，置頂會讓門懸空。門窗立面都站在樓板上，
底部才是它們共同的基準線。

**平均展開是「邊界之間的空隙相等」，不是「中心距相等」。** 元件寬度不一，
等中心距會讓寬元件之間幾乎貼在一起、窄元件之間空一大片，看起來像沒有排版。

長度單位一律毫米。
"""


LAYOUT_HORIZONTAL = 'horizontal'
LAYOUT_VERTICAL = 'vertical'

LAYOUT_LABELS = {
    LAYOUT_HORIZONTAL: u'水平排列（填滿一列再換下一列）',
    LAYOUT_VERTICAL: u'垂直排列（填滿一欄再換下一欄）',
}

TEXT_LEFT = 'left'
TEXT_CENTER = 'center'

TEXT_ALIGN_LABELS = {
    TEXT_LEFT: u'文字靠元件左緣',
    TEXT_CENTER: u'文字對齊元件中心',
}

DEFAULT_GAP_X_MM = 500.0
DEFAULT_GAP_Y_MM = 800.0
DEFAULT_TEXT_GAP_MM = 150.0

# 阻擋原因。每一種都要說得出「為什麼這一筆沒被畫出來」，
# 因為一個沒出現在圖例上的門窗，看圖的人不會知道它被略過了。
BLOCK_NO_SYMBOL = u'讀不到對應的族群類型'
BLOCK_NO_BOX = u'在圖例視圖裡量不到邊界框（元件可能沒有可見幾何）'
BLOCK_COPY_FAILED = u'複製圖例元件失敗'
BLOCK_RETARGET_FAILED = u'複製成功但無法改成目標類型'


def _number(value, fallback=0.0):
    try:
        if value is None:
            return fallback
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value).strip()
    except Exception:
        return u''


# --- 參數文字 --------------------------------------------------------------

def parameter_union(records):
    """所有選定類型的參數名稱聯集，依第一次出現的順序。

    不同族群的參數集不一樣，取聯集才不會因為第一個類型剛好沒有某個參數就讓
    它從清單裡消失。順序取「第一次出現」而不是排序，因為那通常反映族群作者
    安排的閱讀順序。
    """
    order = []
    seen = set()
    for record in records or []:
        for name in record.get('parameters') or []:
            if name not in seen:
                seen.add(name)
                order.append(name)
    return order


def compose_text(record, parameter_names, include_missing=False,
                 separator=u'：'):
    """一個類型要印出來的文字（多行）。

    ``include_missing=False`` 時，這個類型沒有的參數整行省略；為 ``True`` 時
    留一行空值。兩者都有道理——省略比較乾淨，留空讓每一格行數一致而對得齊——
    所以交給呼叫端決定，不在這裡挑一個。
    """
    values = record.get('values') or {}
    lines = []
    missing = []
    for name in parameter_names or []:
        if name in values:
            lines.append(u'{}{}{}'.format(name, separator,
                                          _text(values.get(name))))
        else:
            missing.append(name)
            if include_missing:
                lines.append(u'{}{}'.format(name, separator))
    return u'\n'.join(lines), missing


# --- 排版 ------------------------------------------------------------------

def chunk(items, per_line):
    """切成每列 ``per_line`` 個。``per_line`` 小於 1 時視為一整列。"""
    entries = list(items or [])
    if not entries:
        return []
    size = int(_number(per_line, 0))
    if size < 1:
        return [entries]
    rows = []
    current = []
    for item in entries:
        current.append(item)
        if len(current) == size:
            rows.append(current)
            current = []
    if current:
        rows.append(current)
    return rows


def plan_layout(items, per_line, origin, direction=LAYOUT_HORIZONTAL,
                gap_x_mm=DEFAULT_GAP_X_MM, gap_y_mm=DEFAULT_GAP_Y_MM,
                text_gap_mm=DEFAULT_TEXT_GAP_MM, text_align=TEXT_LEFT,
                text_height_mm=0.0):
    """算出每個元件與它的文字要移到哪裡。

    ``items`` 為 ``[{'id', 'width_mm', 'height_mm', 'min_x_mm', 'min_y_mm',
    'text'}]``——``min_*`` 是元件目前在圖例視圖裡的邊界框左下角，因為
    ``MoveElement`` 收的是位移量而不是絕對座標。

    回傳 ``[{'id', 'dx_mm', 'dy_mm', 'text_x_mm', 'text_y_mm', ...}]``。
    """
    origin_x, origin_y = origin
    gap_x = _number(gap_x_mm, DEFAULT_GAP_X_MM)
    gap_y = _number(gap_y_mm, DEFAULT_GAP_Y_MM)
    text_gap = _number(text_gap_mm, DEFAULT_TEXT_GAP_MM)
    text_height = _number(text_height_mm)

    lines = chunk(items, per_line)
    moves = []
    cursor = origin_y

    if direction == LAYOUT_VERTICAL:
        # 垂直：每一「列」其實是一欄，往右推進；欄內由上往下堆。
        column_x = origin_x
        for column in lines:
            widest = max([_number(item.get('width_mm'))
                          for item in column] or [0.0])
            top = origin_y
            for item in column:
                height = _number(item.get('height_mm'))
                bottom = top - height
                moves.append(_move(item, column_x, bottom, text_gap,
                                   text_align))
                top = bottom - text_gap - text_height - gap_y
            column_x += widest + gap_x
        return moves

    for line in lines:
        # 底部對齊：同一列所有元件的邊界框底緣都放在同一個 y。
        tallest = max([_number(item.get('height_mm')) for item in line]
                      or [0.0])
        baseline = cursor - tallest
        x = origin_x
        for item in line:
            moves.append(_move(item, x, baseline, text_gap, text_align))
            x += _number(item.get('width_mm')) + gap_x
        # 下一列往下讓開：這一列最高的元件 + 文字 + 列距。
        cursor = baseline - text_gap - text_height - gap_y
    return moves


def _move(item, target_x, target_y, text_gap, text_align):
    width = _number(item.get('width_mm'))
    current_x = _number(item.get('min_x_mm'))
    current_y = _number(item.get('min_y_mm'))
    if text_align == TEXT_CENTER:
        text_x = target_x + width / 2.0
    else:
        text_x = target_x
    return {
        'id': item.get('id'),
        'dx_mm': target_x - current_x,
        'dy_mm': target_y - current_y,
        'x_mm': target_x,
        'y_mm': target_y,
        'text_x_mm': text_x,
        # 文字掛在元件底緣下方；TextNote 的插入點是它的**上緣**，
        # 所以這裡給的就是文字要開始的那條線。
        'text_y_mm': target_y - text_gap,
        'text': item.get('text') or u'',
    }


def bounds_of(moves, items=None):
    """整份排版的外框 ``(min_x, min_y, max_x, max_y)``，空的話回 ``None``。

    只用來回報「這份圖例會佔多大」，讓人在按下去之前知道會不會爆出圖框。
    """
    if not moves:
        return None
    widths = {}
    heights = {}
    for item in items or []:
        widths[item.get('id')] = _number(item.get('width_mm'))
        heights[item.get('id')] = _number(item.get('height_mm'))
    xs = []
    ys = []
    for move in moves:
        x = _number(move.get('x_mm'))
        y = _number(move.get('y_mm'))
        xs.append(x)
        xs.append(x + widths.get(move.get('id'), 0.0))
        ys.append(y)
        ys.append(y + heights.get(move.get('id'), 0.0))
    return (min(xs), min(ys), max(xs), max(ys))


# --- 計畫 ------------------------------------------------------------------

def build_plan(records, parameter_names, per_line, direction,
               include_missing=False, **layout):
    """把選定的類型變成一份可執行的計畫。

    ``records`` 每筆需要 ``{'id', 'label', 'parameters', 'values'}``。
    尺寸與位置要等元件實際複製出來才知道，所以這裡只準備文字與順序，
    真正的座標由 ``plan_layout`` 在複製之後算。
    """
    rows = []
    blocked = []
    for record in records or []:
        if not record.get('id'):
            blocked.append({'record': record, 'reason': BLOCK_NO_SYMBOL})
            continue
        text, missing = compose_text(record, parameter_names, include_missing)
        rows.append({
            'id': record['id'],
            'label': record.get('label') or u'',
            'text': text,
            'missing': missing,
        })
    return {
        'rows': rows,
        'blocked': blocked,
        'parameters': list(parameter_names or []),
        'per_line': int(_number(per_line, 1)) or 1,
        'direction': direction,
        'layout': dict(layout),
    }


def has_work(plan):
    return bool((plan or {}).get('rows'))


def plan_lines(plan, view_label=u''):
    """給預覽對話框看的摘要。"""
    lines = []
    if view_label:
        lines.append(u'圖例視圖：{}'.format(view_label))
    lines.append(u'將放置 {} 個門窗圖例元件。'.format(len(plan.get('rows') or [])))
    parameters = plan.get('parameters') or []
    if parameters:
        lines.append(u'每個元件下方列出 {} 個參數：{}'.format(
            len(parameters), u'、'.join(parameters)))
    else:
        lines.append(u'不列出參數文字。')
    lines.append(u'排版：{}，每{} {} 個'.format(
        LAYOUT_LABELS.get(plan.get('direction'), plan.get('direction')),
        u'欄' if plan.get('direction') == LAYOUT_VERTICAL else u'列',
        plan.get('per_line')))

    shortfall = [row for row in plan.get('rows') or [] if row.get('missing')]
    if shortfall:
        lines.append(
            u'有 {} 個類型缺少部分參數，那幾行不會印出來（明細見輸出視窗）。'
            .format(len(shortfall)))
    if plan.get('blocked'):
        lines.append(u'{} 個類型無法放置。'.format(len(plan['blocked'])))
    return u'\n'.join(lines)
