# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""房間參數表：表格操作與 Excel 往返的純邏輯。

不碰 Revit、不碰 WPF，IronPython 2.7 與 CPython 3 都能跑（測試在
``tests/test_room_param_grid_logic.py``）。

表格以「第幾列、第幾欄」定位；欄位是 ``columns`` 清單，每欄是
``{'key', 'header', 'editable'}``。唯讀欄（ElementId、樓層、面積、周長…）
在貼上、填滿、清除、匯入時一律略過，不是報錯——使用者選一整片範圍時
本來就會框到唯讀欄。
"""

ID_HEADER = u'ElementId'
LEVEL_HEADER = u'樓層'
SHEET_NAME = u'房間參數'
NOTE_SHEET_NAME = u'說明'

_YES = (u'是', u'1', u'yes', u'y', u'true', u'v', u'✓')
_NO = (u'否', u'0', u'no', u'n', u'false', u'')


def text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value)
    except Exception:
        return u''


def parse_yesno(value):
    """``是/否``、``1/0``、``Yes/No``… → 1 / 0；看不懂回 ``None``。"""
    word = text(value).strip().lower()
    if word in _YES:
        return 1
    if word in _NO:
        return 0
    return None


def yesno_text(flag):
    return u'是' if flag else u'否'


# ── 剪貼簿 ──────────────────────────────────────────────────────────

def parse_clipboard(raw):
    """Excel / 表格複製出來的 Tab 分隔文字 → 二維清單。

    Excel 複製一定在最後多一個換行，那一列不是資料，要丟掉；但中間的空白列
    是使用者真的要貼的空值，保留。
    """
    raw = text(raw).replace(u'\r\n', u'\n').replace(u'\r', u'\n')
    if raw.endswith(u'\n'):
        raw = raw[:-1]
    if raw == u'':
        return [[u'']]
    return [line.split(u'\t') for line in raw.split(u'\n')]


def _editable(columns, col):
    return 0 <= col < len(columns) and bool(columns[col].get('editable'))


def paste_plan(block, anchor, selected, n_rows, columns):
    """貼上要寫哪些格。回傳 ``(writes, skipped_readonly)``。

    ``writes`` 是 ``[(row, col, value)]``。
    - 剪貼簿只有一格、但選了多格：每一個選取的可編輯格都填這個值
      （Excel 的行為，「一個值貼滿一片」）。
    - 其他情況：以 ``anchor``（選取範圍左上角）為起點照原形狀貼，
      超出表格的部分丟掉。
    唯讀格只計數不寫。
    """
    writes = []
    skipped = 0
    if not block:
        return writes, skipped
    single = len(block) == 1 and len(block[0]) == 1
    if single and len(selected) > 1:
        value = block[0][0]
        for row, col in sorted(selected):
            if _editable(columns, col):
                writes.append((row, col, value))
            else:
                skipped += 1
        return writes, skipped
    if anchor is None:
        return writes, skipped
    top, left = anchor
    for r_offset, line in enumerate(block):
        row = top + r_offset
        if row >= n_rows:
            break
        for c_offset, value in enumerate(line):
            col = left + c_offset
            if col >= len(columns):
                break
            if _editable(columns, col):
                writes.append((row, col, value))
            else:
                skipped += 1
    return writes, skipped


def anchor_of(selected):
    """選取範圍的左上角 ``(row, col)``；沒選回 ``None``。"""
    if not selected:
        return None
    return (min(row for row, col in selected),
            min(col for row, col in selected))


def fill_down_plan(selected, value_at, columns):
    """Ctrl+D：每一欄取選取範圍最上面那格的值，往下填滿同欄其他選取格。

    ``value_at(row, col)`` 讀目前值。只選一格時沒有東西可填（Excel 會拿
    上一列，但這裡的列順序可能被排序過，拿上一列容易填錯，所以不做）。
    """
    by_col = {}
    for row, col in selected:
        by_col.setdefault(col, []).append(row)
    writes = []
    skipped = 0
    for col in sorted(by_col):
        rows = sorted(by_col[col])
        if len(rows) < 2:
            continue
        if not _editable(columns, col):
            skipped += len(rows) - 1
            continue
        value = value_at(rows[0], col)
        for row in rows[1:]:
            writes.append((row, col, value))
    return writes, skipped


def clear_plan(selected, columns):
    writes = []
    skipped = 0
    for row, col in sorted(selected):
        if _editable(columns, col):
            writes.append((row, col, u''))
        else:
            skipped += 1
    return writes, skipped


# ── 變更追蹤 ────────────────────────────────────────────────────────

def changes(rows, original, columns):
    """``rows`` / ``original`` 都是 ``{room_id: {key: value}}``。

    回傳 ``[{'id', 'key', 'header', 'old', 'new'}]``，只算可編輯欄。
    比對時忽略前後空白，避免 Excel 帶回來的尾端空白被當成修改。
    """
    result = []
    editable = [column for column in columns if column.get('editable')]
    for room_id in sorted(rows):
        current = rows[room_id]
        before = original.get(room_id, {})
        for column in editable:
            key = column['key']
            new = text(current.get(key))
            old = text(before.get(key))
            if new.strip() != old.strip():
                result.append({'id': room_id, 'key': key,
                               'header': column['header'],
                               'old': old, 'new': new})
    return result


def changed_count_by_room(change_list):
    counts = {}
    for change in change_list:
        counts[change['id']] = counts.get(change['id'], 0) + 1
    return counts


# ── Excel 往返 ──────────────────────────────────────────────────────

def export_rows(columns, records, values):
    """匯出成 ``[[...]]``，第一列是標題。

    ``records`` 決定列順序（每筆要有 ``id``）；``values`` 是
    ``{room_id: {key: value}}``。ElementId 欄寫成數字，其他一律文字——
    參數值是 Revit 的顯示字串（含單位），寫成文字才能原樣往返。
    """
    rows = [[column['header'] for column in columns]]
    for record in records:
        current = values.get(record['id'], {})
        line = []
        for column in columns:
            if column['header'] == ID_HEADER:
                line.append(record['id'])
            else:
                line.append(text(current.get(column['key'])))
        rows.append(line)
    return rows


def note_rows(columns):
    rows = [[u'欄位', u'可否匯入更新']]
    for column in columns:
        rows.append([column['header'],
                     u'可' if column.get('editable') else u'唯讀（匯入時略過）'])
    rows.append([u'', u''])
    rows.append([u'說明', u'以 ElementId 對回房間；不要改 ElementId 欄與標題列。'])
    return rows


def _id_from_cell(value):
    word = text(value).strip()
    if not word:
        return None
    try:
        return int(float(word))
    except (TypeError, ValueError):
        return None


def import_plan(sheet_rows, columns, known_ids):
    """把 Excel 一張表對回表格。

    ``sheet_rows`` 是 ``[[cell, ...]]``（第一列標題）。以標題名稱對欄、
    以 ElementId 對列。回傳::

        {'writes': [(room_id, key, value)],
         'unknown_ids': [...], 'bad_rows': [excel 列號],
         'readonly_headers': [...], 'ignored_headers': [...],
         'error': u''}
    """
    result = {'writes': [], 'unknown_ids': [], 'bad_rows': [],
              'readonly_headers': [], 'ignored_headers': [], 'error': u''}
    if not sheet_rows:
        result['error'] = u'工作表是空的。'
        return result
    headers = [text(cell).strip() for cell in sheet_rows[0]]
    if ID_HEADER not in headers:
        result['error'] = u'標題列找不到「{}」欄，無法對回房間。'.format(ID_HEADER)
        return result
    id_index = headers.index(ID_HEADER)
    by_header = dict((column['header'], column) for column in columns)
    targets = []
    for index, header in enumerate(headers):
        if not header or index == id_index:
            continue
        column = by_header.get(header)
        if column is None:
            result['ignored_headers'].append(header)
        elif not column.get('editable'):
            if header != LEVEL_HEADER:
                result['readonly_headers'].append(header)
        else:
            targets.append((index, column['key']))
    known = set(known_ids)
    for offset, line in enumerate(sheet_rows[1:]):
        if not any(text(cell).strip() for cell in line):
            continue
        room_id = _id_from_cell(line[id_index] if id_index < len(line)
                                else u'')
        if room_id is None:
            result['bad_rows'].append(offset + 2)
            continue
        if room_id not in known:
            result['unknown_ids'].append(room_id)
            continue
        for index, key in targets:
            value = text(line[index]) if index < len(line) else u''
            result['writes'].append((room_id, key, value))
    return result


def import_summary(plan, applied):
    lines = [u'已從 Excel 帶入 {} 格修改（尚未寫入模型）。'.format(applied)]
    if plan['unknown_ids']:
        lines.append(u'不在目前清單的房間 {} 列（略過）。'.format(
            len(plan['unknown_ids'])))
    if plan['bad_rows']:
        lines.append(u'ElementId 讀不懂的列：{}'.format(
            u'、'.join(text(row) for row in plan['bad_rows'][:20])))
    if plan['readonly_headers']:
        lines.append(u'唯讀欄略過：{}'.format(
            u'、'.join(plan['readonly_headers'])))
    if plan['ignored_headers']:
        lines.append(u'表格裡沒有的欄位略過：{}'.format(
            u'、'.join(plan['ignored_headers'])))
    return u'\n'.join(lines)


# ── 清單標籤 ────────────────────────────────────────────────────────

def room_label(record):
    """``101 會議室〔1F〕``，未放置的房間加註。"""
    head = u' '.join(part for part in (record.get('number'),
                                       record.get('name')) if part)
    label = u'{}〔{}〕'.format(head or u'(未命名)', record.get('level') or u'-')
    if not record.get('placed', True):
        label += u'（未放置）'
    return label


def param_label(info):
    return u'{}（唯讀）'.format(info['name']) if not info.get('editable') \
        else info['name']


def sort_params(infos, preferred=()):
    """``preferred``（編號、名稱）排最前，其餘可編輯在前、唯讀在後，再依名稱。"""
    order = dict((name, index) for index, name in enumerate(preferred))

    def key(info):
        return (order.get(info['name'], len(order)),
                0 if info.get('editable') else 1, info['name'])
    return sorted(infos, key=key)
