# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Pure rules for the door/window schedule (門窗表) Excel updater.

The 小計 sheet prices each door/window type as one row under 金屬門窗工程, with
the quantity hardcoded in the 數量 column. This module owns the matching: how a
Revit type name becomes the same key as an Excel item label, and what counts as
a safe row to overwrite.
"""

import re
import unicodedata

import room_takeoff_sources_logic as room_order_logic
import sheet_layout
import takeoff_standalone


SECTION_NAME = u'金屬門窗工程'
SOURCE_LABEL = u'門窗表'
# 小計 groups its items under 「…工程」 headings; the block ends at the next one.
SECTION_SUFFIX = u'工程'


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value)
    except Exception:
        return str(value)


def normalize_text(value):
    text = unicodedata.normalize('NFKC', _text(value)).lower()
    return re.sub(u'[\\s　]', u'', text)


def type_key(value):
    """``D3-180x220 cm`` and ``D3-180x220cm(WxH)雙開…`` collapse to one key.

    The stable part of both the Revit type name and the Excel item label is the
    leading ``<編號>-<寬>x<高>cm`` token, so the key is everything up to and
    including the first ``cm``. ``W6-R=100cm固定圓形窗`` has no ``(WxH)`` and
    still resolves, which a ``(WxH)``-based split would not.
    """
    text = normalize_text(value)
    if not text:
        return u''
    match = re.match(u'^(.*?cm)', text)
    if match:
        return match.group(1)
    # No cm token: fall back to the part before the first bracket so a type
    # without a size still groups consistently instead of collapsing to ''.
    return re.split(u'[（(]', text)[0]


HOST_SOURCE = 'host'


def level_key(source_key, level_id):
    """Composite level identity: ``host:123`` / ``link:456:789``.

    A level name alone is not unique across models — this project has both
    ``B-1F`` and ``D-1F`` — and even the ElementId repeats between documents,
    so the source model has to be part of the key.
    """
    return u'{}:{}'.format(source_key, level_id)


def link_source_key(link_id):
    return u'link:{}'.format(link_id)


def source_has_selection(source_key, selected_levels):
    """Whether any selected level belongs to this source model.

    Empty selection means no filtering at all, so every source is in scope.
    """
    if not selected_levels:
        return True
    prefix = u'{}:'.format(source_key)
    return any(u'{}'.format(key).startswith(prefix) for key in selected_levels)


def is_section_heading(value, unit=u''):
    """A 小計 section heading, e.g. 金屬門窗工程 or 外牆鋁包板工程(以面積計算).

    Two conditions, because neither alone is safe:
    - the label ends with 工程 once a trailing bracketed qualifier is stripped.
      「複層式金屬鋼浪板工程(以面積計算)」 is a heading, and a plain
      ``endswith`` misses it — which silently merges the following sections
      into this one (measured on 物流中心工項-0720.xls: the block ran from
      r142 to r196 instead of stopping at r175);
    - the row carries no unit, which is what structurally separates a heading
      from a priced item — every item has 樘 / M2 / M.
    """
    text = re.split(u'[（(]', normalize_text(value))[0]
    if not text or not text.endswith(SECTION_SUFFIX) or len(text) > 16:
        return False
    return not _text(unit).strip()


def find_section_rows(cells, section_name=SECTION_NAME, label_col=3,
                      unit_col=5):
    """``(first_item_row, last_item_row)`` for a 小計 section block.

    Items start on the row after the heading and stop before the next
    「…工程」 heading, so adding items to the sheet does not need this code
    changed.
    """
    needle = normalize_text(section_name)
    by_row = {}
    units = {}
    for row, col, value in cells:
        if int(col) == int(label_col):
            by_row[int(row)] = value
        elif int(col) == int(unit_col):
            units[int(row)] = value
    heading_rows = sorted(
        row for row, value in by_row.items()
        if is_section_heading(value, units.get(row, u'')))
    start = None
    for row in heading_rows:
        if needle in normalize_text(by_row[row]):
            start = row
            break
    if start is None:
        raise ValueError(u'小計 分頁找不到「{}」區塊。'.format(section_name))
    following = [row for row in heading_rows if row > start]
    end = (min(following) - 1) if following else max(by_row)
    return start + 1, end


def parse_items(cells, first_row, last_row, label_col=3, quantity_col=6,
                unit_col=5):
    """Excel item rows as ``[{row, name, key, quantity, unit}, ...]``."""
    by_cell = {}
    for row, col, value in cells:
        by_cell[(int(row), int(col))] = value
    items = []
    for row in range(int(first_row), int(last_row) + 1):
        name = _text(by_cell.get((row, label_col), u'')).strip()
        if not name:
            continue
        key = type_key(name)
        if not key:
            continue
        quantity = by_cell.get((row, quantity_col))
        try:
            quantity = float(quantity)
        except (TypeError, ValueError):
            quantity = None
        items.append({
            'row': row,
            'name': name,
            'key': key,
            'quantity': quantity,
            'unit': _text(by_cell.get((row, unit_col), u'')).strip(),
        })
    return items


def duplicate_keys(items):
    """Keys appearing on more than one Excel row — ambiguous, never written."""
    seen = {}
    for item in items:
        seen.setdefault(item['key'], []).append(item['row'])
    return dict((key, rows) for key, rows in seen.items() if len(rows) > 1)


def build_plan(items, revit_counts):
    """Reconcile Excel rows against Revit counts.

    ``revit_counts`` maps type key -> {'count': n, 'names': set/list}.
    Returns updates (row-level), plus both directions of mismatch so the
    preview can show what is missing from each side rather than silently
    writing a partial answer.
    """
    duplicates = duplicate_keys(items)
    updates = []
    zeroed = []
    blocked = []
    matched_keys = set()
    for item in items:
        key = item['key']
        if key in duplicates:
            blocked.append({
                'row': item['row'], 'name': item['name'],
                'reason': u'Excel 內有 {} 列使用同一型號鍵 {}'.format(
                    len(duplicates[key]), key)})
            continue
        entry = revit_counts.get(key)
        if entry is None:
            # Excel prices it, Revit has none: report, never silently zero.
            zeroed.append(item)
            continue
        matched_keys.add(key)
        new_value = int(entry['count'])
        if item['quantity'] is not None and abs(
                item['quantity'] - new_value) < 0.0001:
            continue
        updates.append({
            'row': item['row'], 'name': item['name'], 'key': key,
            'old': item['quantity'], 'new': new_value,
            'revit_names': sorted(entry.get('names') or []),
        })
    extras = []
    for key in sorted(revit_counts):
        if key in matched_keys:
            continue
        entry = revit_counts[key]
        extras.append({
            'key': key, 'count': int(entry['count']),
            'names': sorted(entry.get('names') or [])})
    return {
        'updates': updates,
        'unmatched_excel': zeroed,
        'unmatched_revit': extras,
        'blocked': blocked,
        'duplicates': duplicates,
    }


AUDIT_SHEET = u'門窗表稽核'
AUDIT_HEADERS = (u'來源模型', u'樓層', u'型號鍵', u'型號名稱', u'數量',
                 u'更新時間')
ALL_LEVELS = u'（全部樓層）'


def audit_scope(model_label, level_label):
    return (_text(model_label).strip(), _text(level_label).strip())


def replace_audit_rows(existing, run_rows, run_scopes):
    """Ledger merge: this run replaces only its own scopes.

    ``run_scopes`` is the set of ``(model, level)`` this run actually covered.
    A run over a whole model (no level filter) uses ``ALL_LEVELS`` and must
    clear every level row of that model — otherwise a previous per-level run
    would still be counted on top of the whole-model figure.
    """
    whole_models = set(model for model, level in run_scopes
                       if level == ALL_LEVELS)
    scoped = set(run_scopes)
    kept = []
    for row in existing or []:
        scope = audit_scope(row.get('model'), row.get('level'))
        if scope[0] in whole_models:
            continue
        if scope in scoped:
            continue
        kept.append(row)
    return kept + list(run_rows or [])


def aggregate_audit(rows):
    """``{key: {'count': n, 'names': [...], 'sources': [...]}}`` over all rows."""
    totals = {}
    for row in rows or []:
        key = _text(row.get('key')).strip()
        if not key:
            continue
        try:
            count = int(float(row.get('count') or 0))
        except (TypeError, ValueError):
            continue
        entry = totals.setdefault(key, {'count': 0, 'names': set(),
                                        'sources': set()})
        entry['count'] += count
        name = _text(row.get('name')).strip()
        if name:
            entry['names'].add(name)
        entry['sources'].add(u'{}｜{}'.format(
            _text(row.get('model')), _text(row.get('level'))))
    for entry in totals.values():
        entry['names'] = sorted(entry['names'])
        entry['sources'] = sorted(entry['sources'])
    return totals


def audit_values(rows):
    """Sheet values (header + rows) for the audit sheet."""
    values = [list(AUDIT_HEADERS)]
    for row in sorted(rows or [], key=lambda item: (
            _text(item.get('model')), _text(item.get('level')),
            _text(item.get('key')))):
        values.append([
            _text(row.get('model')),
            _text(row.get('level')),
            _text(row.get('key')),
            _text(row.get('name')),
            row.get('count'),
            _text(row.get('updated')),
        ])
    return values


def parse_audit_rows(cells, header_row=1):
    """Read back the ledger written by a previous run."""
    by_cell = {}
    max_row = header_row
    for row, col, value in cells:
        by_cell[(int(row), int(col))] = value
        max_row = max(max_row, int(row))
    rows = []
    for row in range(int(header_row) + 1, max_row + 1):
        model = _text(by_cell.get((row, 1), u'')).strip()
        key = _text(by_cell.get((row, 3), u'')).strip()
        if not model or not key:
            continue
        try:
            count = int(float(by_cell.get((row, 5)) or 0))
        except (TypeError, ValueError):
            continue
        rows.append({
            'model': model,
            'level': _text(by_cell.get((row, 2), u'')).strip(),
            'key': key,
            'name': _text(by_cell.get((row, 4), u'')).strip(),
            'count': count,
            'updated': _text(by_cell.get((row, 6), u'')).strip(),
        })
    return rows


def is_safe_quantity_cell(formula):
    """Only a blank or a plain number may be overwritten.

    The 小計 數量 cells in this workbook are hardcoded numbers and the 小計 column
    mirrors them with ``=F<row>``. A formula in the quantity cell itself means
    someone wired it to another sheet, which this button must not clobber.
    """
    value = _text(formula).replace(u' ', u'')
    if not value:
        return True
    return not value.startswith(u'=')


def relocate_safe_updates(updates, current_items, protected):
    """Resolve preview updates by current key and recheck formula protection.

    Row numbers can move between preview and write.  The normalized item key
    is identity; the current row is only the final address.
    """
    by_key = {}
    for item in current_items or []:
        by_key.setdefault(item.get('key'), []).append(item)
    protected_rows = set(
        int(item.get('row')) for item in protected or []
        if item.get('row') is not None)
    relocated = []
    for update in updates or []:
        matches = by_key.get(update.get('key')) or []
        if len(matches) != 1:
            raise ValueError(
                u'工項「{}」自預覽後找不到唯一對應列。'.format(
                    update.get('name') or update.get('key')))
        current = matches[0]
        row = int(current['row'])
        if row in protected_rows:
            raise ValueError(
                u'第 {} 列「{}」的數量欄自預覽後已改為公式，禁止覆寫。'
                .format(row, current.get('name') or update.get('key')))
        item = dict(update)
        item['row'] = row
        relocated.append(item)
    return relocated


def plan_summary(plan, revit_total, excel_total):
    lines = [
        u'Revit 門窗合計：{} 樘（{} 種型號）'.format(
            revit_total, len(plan['unmatched_revit']) + len(
                set(u['key'] for u in plan['updates']))),
        u'Excel 工項列：{} 列'.format(excel_total),
        u'',
        u'將更新 {} 列'.format(len(plan['updates'])),
    ]
    for item in plan['updates']:
        old = u'(空白)' if item['old'] is None else u'{:g}'.format(item['old'])
        lines.append(u'  r{:<4} {} : {} → {}'.format(
            item['row'], item['name'][:38], old, item['new']))
    if plan['unmatched_excel']:
        lines.extend([u'', u'⚠ Excel 有工項但 Revit 找不到對應型號（不會改動）：'])
        for item in plan['unmatched_excel']:
            lines.append(u'  r{:<4} {}（現值 {}）'.format(
                item['row'], item['name'][:38],
                u'空白' if item['quantity'] is None
                else u'{:g}'.format(item['quantity'])))
    if plan['unmatched_revit']:
        lines.extend([u'', u'⚠ Revit 有門窗但 Excel 沒有對應工項列（需人工新增）：'])
        for item in plan['unmatched_revit']:
            lines.append(u'  {} × {}　{}'.format(
                item['key'], item['count'], u' / '.join(item['names'][:3])))
    if plan['blocked']:
        lines.extend([u'', u'✗ 阻擋項：'])
        for item in plan['blocked']:
            lines.append(u'  r{:<4} {}'.format(item['row'], item['reason']))
    return u'\n'.join(lines)


STANDALONE_DETAIL_HEADERS = (
    u'來源鍵', u'來源模型', u'樓層', u'類型鍵', u'Revit 類型', u'數量')
STANDALONE_FORMULA_HEADERS = (
    u'類型鍵', u'Revit 類型', u'數量公式')
STANDALONE_AUDIT_HEADERS = (
    u'檢核項目', u'結果', u'說明')

# 獨立匯出兩張分頁的欄位。公式以前把 D/F/C 這幾個字母寫死，
# 跟上面表頭的排列順序是兩套各自維護的真相。
STANDALONE_DETAIL_COLUMNS = [
    'source_key', 'model', 'level', 'type_key', 'type_name', 'count',
]
STANDALONE_FORMULA_COLUMNS = ['type_key', 'type_name', 'quantity']
for _names, _headers, _label in (
        (STANDALONE_DETAIL_COLUMNS, STANDALONE_DETAIL_HEADERS, 'DETAIL'),
        (STANDALONE_FORMULA_COLUMNS, STANDALONE_FORMULA_HEADERS, 'FORMULA')):
    if len(_names) != len(_headers):
        raise AssertionError(
            u'STANDALONE_{0} 的欄位與表頭長度不一致'.format(_label))
STANDALONE_DETAIL = sheet_layout.SheetLayout(
    STANDALONE_DETAIL_COLUMNS, first_data_row=2,
    name=takeoff_standalone.DETAIL_SHEET)
STANDALONE_FORMULA = sheet_layout.SheetLayout(
    STANDALONE_FORMULA_COLUMNS, first_data_row=2,
    name=takeoff_standalone.FORMULA_SHEET)


def _abs_detail_range(key, last_row):
    """絕對位址的跨分頁範圍（SUMIF 需要）。"""
    col = STANDALONE_DETAIL.col(key)
    return u"'{0}'!${1}${2}:${1}${3}".format(
        takeoff_standalone.DETAIL_SHEET, col,
        STANDALONE_DETAIL.first_data_row, last_row)


def _formula_cell(key, row):
    return u"'{0}'!{1}".format(takeoff_standalone.FORMULA_SHEET,
                               STANDALONE_FORMULA.cell(key, row))



def standalone_tables(takeoff):
    """Build the standardized 門窗 standalone rows without Revit/Excel."""
    audit_source_rows = list((takeoff or {}).get('audit_rows') or [])
    ordered = sorted(audit_source_rows, key=lambda row: (
        _text(row.get('source_key')),
        _text(row.get('model')),
        _text(row.get('level')),
        room_order_logic.room_number_sort_key(row.get('key'))))
    detail_rows = []
    for row in ordered:
        detail_rows.append([
            _text(row.get('source_key')) or _text(row.get('model')),
            _text(row.get('model')),
            _text(row.get('level')),
            _text(row.get('key')),
            _text(row.get('name')),
            int(float(row.get('count') or 0)),
        ])

    names = {}
    for row in ordered:
        key = _text(row.get('key'))
        name = _text(row.get('name'))
        if key and name and key not in names:
            names[key] = name
    keys = sorted(
        set(
            _text(row.get('key')) for row in ordered
            if _text(row.get('key'))),
        key=room_order_logic.room_number_sort_key)
    detail_last = max(2, len(detail_rows) + 1)
    formula_rows = []
    for index, key in enumerate(keys, 2):
        formula_rows.append([
            key,
            names.get(key, u''),
            u'=SUMIF({0},{1},{2})'.format(
                _abs_detail_range('type_key', detail_last),
                STANDALONE_FORMULA.cell('type_key', index),
                _abs_detail_range('count', detail_last)),
        ])
    total_formula = (
        u'=SUM({})'.format(STANDALONE_FORMULA.rng(
            'quantity', STANDALONE_FORMULA.first_data_row,
            len(formula_rows) + 1))
        if formula_rows else u'=0')
    formula_rows.append([u'合計', u'全部門窗', total_formula])

    source_keys = sorted(set(
        _text(row.get('source_key')) or _text(row.get('model'))
        for row in ordered))
    total_row = len(formula_rows) + 1
    audit_rows = [
        [u'既有主檔契約', u'INFO', u'只直接更新小計（金屬門窗工程）'],
        [u'來源身分', u'PASS', u'、'.join(source_keys) or u'(無資料)'],
        [u'來源摘要', u'INFO',
         u'；'.join(_text(item) for item in
                    ((takeoff or {}).get('sources') or []))],
        [u'總數公式', u'CHECK',
         u'=' + _formula_cell('quantity', total_row)],
    ]
    return {
        'detail_headers': list(STANDALONE_DETAIL_HEADERS),
        'detail_rows': detail_rows,
        'formula_headers': list(STANDALONE_FORMULA_HEADERS),
        'formula_rows': formula_rows,
        'audit_headers': list(STANDALONE_AUDIT_HEADERS),
        'audit_rows': audit_rows,
    }
