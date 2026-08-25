# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Safe publication helpers for standalone takeoff workbooks.

The takeoff scripts continue to build a fresh temporary ``.xlsx`` with their
existing OpenXML writers.  This module then copies only the explicitly managed
worksheets into an existing user workbook.  The existing workbook is never
passed to a ``FileMode.Create`` writer.

Excel and CLR imports are deliberately lazy so the pure identity/stat helpers
remain testable with ordinary CPython.
"""

import copy
import datetime
import os
import re
import tempfile

try:
    text_type = unicode
except NameError:  # CPython 3 tests
    text_type = str


FORMULA_ERROR_TOKENS = (
    '#NULL!',
    '#DIV/0!',
    '#VALUE!',
    '#REF!',
    '#NAME?',
    '#NUM!',
    '#N/A',
)
EXCEL_ERROR_CODE_TOKENS = {
    2000: '#NULL!',
    2007: '#DIV/0!',
    2015: '#VALUE!',
    2023: '#REF!',
    2029: '#NAME?',
    2036: '#NUM!',
    2042: '#N/A',
}
XL_PASTE_COLUMN_WIDTHS = 8
DEFAULT_INDEX_SHEET = u'小計'


class WorkbookPublishError(Exception):
    """Publication failed; ``backup_path`` identifies the recoverable copy."""

    def __init__(self, message, backup_path=None):
        Exception.__init__(self, message)
        self.backup_path = backup_path


def _text(value):
    if value is None:
        return ''
    if isinstance(value, text_type):
        return value
    return text_type(value)


def element_id_value(value):
    """Return a Revit element/id value as an integer."""
    item = getattr(value, 'Id', value)
    for attribute in ('Value', 'IntegerValue'):
        try:
            return int(getattr(item, attribute))
        except Exception:
            pass
    return int(item)


def composite_element_key(source_key, element_id):
    """Keep identical Revit ElementIds from different sources distinct."""
    return '{}:{}'.format(_text(source_key), element_id_value(element_id))


def rekey_room_records(source_key, source_label, rooms,
                       related_by_room=None):
    """Tag room records and re-key their related opening collections.

    ``rooms`` are modified in place because the existing report builders
    already consume mutable dictionaries.  A new related mapping is returned.
    """
    old_to_new = {}
    for room in rooms or []:
        old_id = room.get('element_id')
        new_id = composite_element_key(source_key, old_id)
        old_to_new[old_id] = new_id
        room['element_id'] = new_id
        room['source_key'] = _text(source_key)
        room['source_label'] = _text(source_label)

    rekeyed = {}
    for old_id, values in (related_by_room or {}).items():
        new_id = old_to_new.get(
            old_id, composite_element_key(source_key, old_id))
        tagged = []
        for value in values or []:
            item = value
            if isinstance(value, dict):
                item = dict(value)
                if item.get('id') is not None:
                    item['id'] = composite_element_key(
                        source_key, item.get('id'))
                if item.get('host_id') is not None:
                    item['host_id'] = composite_element_key(
                        source_key, item.get('host_id'))
                item['source_key'] = _text(source_key)
            tagged.append(item)
        rekeyed[new_id] = tagged
    for new_id in old_to_new.values():
        rekeyed.setdefault(new_id, [])
    return rooms, rekeyed


def merge_stats(target, incoming):
    """Recursively combine per-source takeoff statistics."""
    if target is None:
        target = {}
    for key, value in (incoming or {}).items():
        if key not in target:
            target[key] = copy.deepcopy(value)
            continue
        current = target[key]
        if isinstance(current, dict) and isinstance(value, dict):
            merge_stats(current, value)
        elif (isinstance(current, (int, float))
              and not isinstance(current, bool)
              and isinstance(value, (int, float))
              and not isinstance(value, bool)):
            target[key] = current + value
        elif isinstance(current, list) and isinstance(value, list):
            current.extend(copy.deepcopy(value))
        elif isinstance(current, set) and isinstance(value, set):
            current.update(value)
        elif not current:
            target[key] = copy.deepcopy(value)
        elif value and value != current:
            if isinstance(current, text_type) and isinstance(value, text_type):
                target[key] = '{}; {}'.format(current, value)
    return target


def make_backup_path(workbook_path, timestamp=None):
    """Return a timestamped sibling path without overwriting an old backup."""
    path = os.path.abspath(workbook_path)
    folder, filename = os.path.split(path)
    stem, extension = os.path.splitext(filename)
    stamp = timestamp or datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    candidate = os.path.join(
        folder, '{}_backup_{}{}'.format(stem, stamp, extension))
    suffix = 2
    while os.path.exists(candidate):
        candidate = os.path.join(
            folder,
            '{}_backup_{}_{}{}'.format(stem, stamp, suffix, extension))
        suffix += 1
    return candidate


def new_temp_xlsx_path():
    """Reserve and return a writable temporary ``.xlsx`` path."""
    handle, path = tempfile.mkstemp(prefix='revit_takeoff_', suffix='.xlsx')
    os.close(handle)
    return path


def remove_file_quietly(path):
    try:
        if path and os.path.isfile(path):
            os.remove(path)
    except Exception:
        pass


def _release_com(value):
    if value is None:
        return
    try:
        from System.Runtime.InteropServices import Marshal
        if Marshal.IsComObject(value):
            # A property access can return an RCW shared by another live
            # reference. FinalReleaseComObject disconnects every alias and
            # causes the next Excel call to fail with InvalidComObjectException.
            # Release only this reference; Quit + the final GC pass handle any
            # remaining wrappers after the workbook operation is complete.
            Marshal.ReleaseComObject(value)
    except Exception:
        pass


def _worksheet_by_name(workbook, name):
    sheets = workbook.Worksheets
    try:
        for index in range(1, int(sheets.Count) + 1):
            sheet = sheets.Item(index)
            try:
                if _text(sheet.Name) == _text(name):
                    return sheet
            finally:
                if _text(getattr(sheet, 'Name', '')) != _text(name):
                    _release_com(sheet)
        return None
    finally:
        _release_com(sheets)


def _managed_sheet_mappings(values):
    """Normalize ``name`` or ``(generated_name, target_name)`` entries."""
    result = []
    seen = set()
    for raw in values or []:
        if isinstance(raw, (tuple, list)) and len(raw) == 2:
            source_name = _text(raw[0]).strip()
            target_name = _text(raw[1]).strip()
        else:
            source_name = _text(raw).strip()
            target_name = source_name
        key = (source_name, target_name)
        if source_name and target_name and key not in seen:
            result.append(key)
            seen.add(key)
    return result


def _normalize_header_key(value):
    return re.sub(r'\s+', '', _text(value)).upper()


def _column_letters(number):
    value = int(number)
    result = ''
    while value:
        value, remainder = divmod(value - 1, 26)
        result = chr(65 + remainder) + result
    return result


def rebase_summary_formula(formula, sheet_name, old_row, new_row,
                           column_map=None):
    """Rebase direct references to a managed sheet's former summary row.

    ``column_map`` maps old one-based column numbers to new column numbers.
    A mapped ``None`` means the old material code is absent from the generated
    report, so that reference becomes the literal zero instead of silently
    pointing at another material column.
    """
    text = _text(formula)
    if not text.startswith('='):
        return text, 0, 0
    escaped_plain = re.escape(_text(sheet_name))
    escaped_quoted = re.escape(_text(sheet_name).replace("'", "''"))
    pattern = re.compile(
        u"(?P<sheet>'{0}'|{1})!"
        u"(?P<col_abs>\\$?)(?P<col>[A-Z]{{1,3}})"
        u"(?P<row_abs>\\$?)(?P<row>{2})(?!\\d)"
        .format(escaped_quoted, escaped_plain, int(old_row)),
        re.I)
    changed = [0]
    zeroed = [0]

    def replace(match):
        old_col = 0
        for character in match.group('col').upper():
            old_col = old_col * 26 + ord(character) - 64
        new_col = old_col
        if column_map is not None and old_col in column_map:
            new_col = column_map[old_col]
        changed[0] += 1
        if new_col is None:
            zeroed[0] += 1
            return '0'
        return u'{}!{}{}{}{}'.format(
            match.group('sheet'),
            match.group('col_abs'),
            _column_letters(new_col),
            match.group('row_abs'),
            int(new_row))

    return pattern.sub(replace, text), changed[0], zeroed[0]


def _sheet_label_rows(sheet, label):
    """Find every row containing an exact label without Excel Range.Find."""
    used = rows = columns = cells = start = end = data = None
    matches = set()
    try:
        used = sheet.UsedRange
        first_row = max(1, int(used.Row))
        first_col = max(1, int(used.Column))
        rows = used.Rows
        columns = used.Columns
        row_count = max(1, int(rows.Count))
        col_count = max(1, int(columns.Count))
        cells = sheet.Cells
        start = cells.Item(first_row, first_col)
        end = cells.Item(
            first_row + row_count - 1, first_col + col_count - 1)
        data = sheet.Range(start, end)
        values = data.Value2
        needle = _normalize_header_key(label)
        for row_offset in range(1, row_count + 1):
            for col_offset in range(1, col_count + 1):
                if _normalize_header_key(_matrix_value(
                        values, row_offset, col_offset,
                        row_count, col_count)) == needle:
                    matches.add(first_row + row_offset - 1)
    finally:
        for value in (data, end, start, cells, columns, rows, used):
            _release_com(value)
    return sorted(list(matches))


def _sheet_label_row(sheet, label, require_unique=False):
    """Return one exact label row, optionally enforcing a unique anchor."""
    matches = _sheet_label_rows(sheet, label)
    if require_unique and len(matches) != 1:
        raise Exception(
            u'Expected one "{}" label in {}, found {}.'
            .format(label, _text(sheet.Name), len(matches)))
    return matches[0] if matches else None


def _matrix_value(matrix, row, col, row_count, col_count):
    if row_count == 1 and col_count == 1:
        return matrix
    try:
        return matrix.GetValue(row, col)
    except Exception:
        try:
            return matrix[row - 1][col - 1]
        except Exception:
            return None


def _header_columns(sheet, header_row):
    used = columns = None
    result = {}
    try:
        used = sheet.UsedRange
        columns = used.Columns
        first_col = max(1, int(used.Column))
        last_col = first_col + max(1, int(columns.Count)) - 1
        for col in range(first_col, last_col + 1):
            cell = None
            try:
                cell = sheet.Cells.Item(int(header_row), col)
                key = _normalize_header_key(cell.Value2)
                if key:
                    result[col] = key
            finally:
                _release_com(cell)
    finally:
        _release_com(columns)
        _release_com(used)
    return result


def _summary_reference_pattern(sheet_name):
    escaped_plain = re.escape(_text(sheet_name))
    escaped_quoted = re.escape(_text(sheet_name).replace("'", "''"))
    return re.compile(
        u"(?:'{0}'|{1})!"
        u"(?P<col_abs>\\$?)(?P<col>[A-Z]{{1,3}})"
        u"(?P<row_abs>\\$?)(?P<row>\\d+)"
        .format(escaped_quoted, escaped_plain),
        re.I)


def summary_reference_rows(formula, sheet_name):
    """Return direct A1 references to ``sheet_name`` as ``(column, row)``.

    The returned references are used as a semantic contract for the index
    sheet.  A formula may remain valid Excel while pointing at last run's data
    row; checking the referenced row against the labelled summary row catches
    that silent failure.
    """
    text = _text(formula)
    if not text.startswith('='):
        return []
    return [
        (match.group('col').upper(), int(match.group('row')))
        for match in _summary_reference_pattern(sheet_name).finditer(text)
    ]


def summary_sum_formula_issue(formula, formula_column,
                              first_data_row, last_data_row):
    """Describe a stale summary ``SUM`` formula, or return ``None``.

    This validates meaning rather than Excel syntax: the formula must sum its
    own column and exactly the rows between the semantic data header and the
    labelled summary row.
    """
    text = re.sub(r'\s+', '', _text(formula)).upper()
    expected_col = _column_letters(int(formula_column))
    if int(last_data_row) < int(first_data_row):
        if text == '=0':
            return None
        return u'expected =0 for an empty data region'
    match = re.match(
        r'^=SUM\(\$?([A-Z]{1,3})\$?(\d+):'
        r'\$?([A-Z]{1,3})\$?(\d+)\)$',
        text)
    if not match:
        return u'expected a direct SUM over the complete data region'
    start_col, start_row, end_col, end_row = match.groups()
    if start_col != expected_col or end_col != expected_col:
        return u'expected SUM to use its own column {}'.format(expected_col)
    if (int(start_row) != int(first_data_row) or
            int(end_row) != int(last_data_row)):
        return u'expected rows {}:{}, found {}:{}'.format(
            int(first_data_row), int(last_data_row),
            int(start_row), int(end_row))
    return None


def _summary_header_row(sheet, spec, summary_row):
    """Resolve a material/type header by label, with legacy row fallback."""
    header_label = spec.get('header_label')
    if header_label:
        header_row = _sheet_label_row(
            sheet, header_label, require_unique=True)
    else:
        header_row = spec.get('header_row')
    if header_row is None:
        return None
    header_row = int(header_row)
    if header_row >= int(summary_row):
        raise Exception(
            u'Header row {} is not above summary row {} in {}.'
            .format(header_row, summary_row, _text(sheet.Name)))
    return header_row


def _summary_data_header_row(sheet, spec, summary_row):
    label = spec.get('data_header_label')
    if not label:
        return None
    row = _sheet_label_row(sheet, label, require_unique=True)
    if int(row) >= int(summary_row):
        raise Exception(
            u'Data header row {} is not above summary row {} in {}.'
            .format(row, summary_row, _text(sheet.Name)))
    return int(row)


def _prepare_summary_rebases(source_book, target_book, mappings,
                             summary_specs):
    """Capture old/new summary locations before managed sheets are replaced."""
    plans = []
    specs = summary_specs or {}
    for source_name, target_name in mappings:
        spec = specs.get(target_name)
        if not spec:
            continue
        source_sheet = _worksheet_by_name(source_book, source_name)
        target_sheet = _worksheet_by_name(target_book, target_name)
        if source_sheet is None or target_sheet is None:
            _release_com(source_sheet)
            _release_com(target_sheet)
            continue
        try:
            label = spec.get('label')
            old_row = _sheet_label_row(
                target_sheet, label, require_unique=True)
            new_row = _sheet_label_row(
                source_sheet, label, require_unique=True)
            column_map = None
            old_header_row = _summary_header_row(
                target_sheet, spec, old_row)
            new_header_row = _summary_header_row(
                source_sheet, spec, new_row)
            if old_header_row is not None and new_header_row is not None:
                old_headers = _header_columns(target_sheet, old_header_row)
                new_headers = _header_columns(source_sheet, new_header_row)
                new_by_key = dict(
                    (key, col) for col, key in new_headers.items())
                column_map = dict(
                    (old_col, new_by_key.get(key))
                    for old_col, key in old_headers.items())
            plans.append({
                'source_name': source_name,
                'sheet_name': target_name,
                'old_row': old_row,
                'new_row': new_row,
                'old_header_row': old_header_row,
                'new_header_row': new_header_row,
                'old_data_header_row': _summary_data_header_row(
                    target_sheet, spec, old_row),
                'new_data_header_row': _summary_data_header_row(
                    source_sheet, spec, new_row),
                'column_map': column_map,
            })
        finally:
            _release_com(target_sheet)
            _release_com(source_sheet)
    return plans


def _scan_index_summary_contract(workbook, index_sheet_name, plans,
                                 row_key):
    """Find valid-looking workbook formulas that reference the wrong row.

    ``index_sheet_name`` remains in the signature for compatibility.  Earlier
    versions checked only that sheet, which left comparison and update sheets
    pointing at the previous summary row.
    """
    found = []
    sheets = workbook.Worksheets
    try:
        for sheet_index in range(1, int(sheets.Count) + 1):
            sheet = sheets.Item(sheet_index)
            used = rows = columns = formulas = None
            try:
                sheet_name = _text(sheet.Name)
                used = sheet.UsedRange
                first_row = max(1, int(used.Row))
                first_col = max(1, int(used.Column))
                rows = used.Rows
                columns = used.Columns
                row_count = max(1, int(rows.Count))
                col_count = max(1, int(columns.Count))
                formulas = used.Formula
                for row_offset in range(1, row_count + 1):
                    for col_offset in range(1, col_count + 1):
                        formula = _text(_matrix_value(
                            formulas, row_offset, col_offset,
                            row_count, col_count))
                        if not formula.startswith('='):
                            continue
                        cell_row = first_row + row_offset - 1
                        cell_col = first_col + col_offset - 1
                        cell_address = u'{}!{}{}'.format(
                            sheet_name, _column_letters(cell_col), cell_row)
                        for plan in plans or []:
                            expected_row = int(plan[row_key])
                            refs = summary_reference_rows(
                                formula, plan['sheet_name'])
                            for ref_col, ref_row in refs:
                                if ref_row == expected_row:
                                    continue
                                found.append(
                                    u'{} references {}!{}{}, expected '
                                    u'summary row {}'.format(
                                        cell_address, plan['sheet_name'],
                                        ref_col, ref_row, expected_row))
            finally:
                for value in (formulas, columns, rows, used, sheet):
                    _release_com(value)
    finally:
        _release_com(sheets)
    return found


def _scan_managed_summary_contract(workbook, plans, generated):
    """Validate summary ranges against labelled data and summary rows."""
    found = []
    for plan in plans or []:
        if generated:
            sheet_name = plan['source_name']
            summary_row = int(plan['new_row'])
            data_header_row = plan.get('new_data_header_row')
        else:
            sheet_name = plan['sheet_name']
            summary_row = int(plan['new_row'])
            data_header_row = plan.get('new_data_header_row')
        if data_header_row is None:
            continue
        sheet = _worksheet_by_name(workbook, sheet_name)
        used = columns = None
        try:
            if sheet is None:
                found.append(u'missing managed worksheet {}'.format(
                    sheet_name))
                continue
            used = sheet.UsedRange
            columns = used.Columns
            first_col = max(1, int(used.Column))
            last_col = first_col + max(1, int(columns.Count)) - 1
            first_data_row = int(data_header_row) + 1
            last_data_row = summary_row - 1
            for col in range(first_col, last_col + 1):
                cell = None
                try:
                    cell = sheet.Cells.Item(summary_row, col)
                    formula = _text(cell.Formula)
                    if not formula.startswith('='):
                        continue
                    issue = summary_sum_formula_issue(
                        formula, col, first_data_row, last_data_row)
                    if issue:
                        found.append(u'{}!{}{} {}: {}'.format(
                            sheet_name, _column_letters(col), summary_row,
                            formula, issue))
                finally:
                    _release_com(cell)
        finally:
            for value in (columns, used, sheet):
                _release_com(value)
    return found


def _apply_summary_rebases(workbook, index_sheet_name, plans):
    """Rewrite every workbook formula that points at an old summary row."""
    changed_total = 0
    zeroed_total = 0
    details = []
    sheets = workbook.Worksheets
    try:
        for sheet_index in range(1, int(sheets.Count) + 1):
            sheet = sheets.Item(sheet_index)
            used = rows = columns = cells = start = end = data = None
            formulas = None
            try:
                sheet_name = _text(sheet.Name)
                used = sheet.UsedRange
                first_row = max(1, int(used.Row))
                first_col = max(1, int(used.Column))
                rows = used.Rows
                columns = used.Columns
                row_count = max(1, int(rows.Count))
                col_count = max(1, int(columns.Count))
                cells = sheet.Cells
                start = cells.Item(first_row, first_col)
                end = cells.Item(
                    first_row + row_count - 1,
                    first_col + col_count - 1)
                data = sheet.Range(start, end)
                formulas = data.Formula
                for row_offset in range(1, row_count + 1):
                    for col_offset in range(1, col_count + 1):
                        formula = _text(_matrix_value(
                            formulas, row_offset, col_offset,
                            row_count, col_count))
                        if not formula.startswith('='):
                            continue
                        rewritten = formula
                        cell_changed = 0
                        cell_zeroed = 0
                        for plan in plans or []:
                            rewritten, changed, zeroed = (
                                rebase_summary_formula(
                                    rewritten,
                                    plan['sheet_name'],
                                    plan['old_row'],
                                    plan['new_row'],
                                    plan.get('column_map')))
                            cell_changed += changed
                            cell_zeroed += zeroed
                        if not cell_changed or rewritten == formula:
                            continue
                        row = first_row + row_offset - 1
                        col = first_col + col_offset - 1
                        cell = None
                        try:
                            cell = cells.Item(row, col)
                            cell.Formula = rewritten
                        finally:
                            _release_com(cell)
                        changed_total += cell_changed
                        zeroed_total += cell_zeroed
                        details.append({
                            'cell': u'{}!{}{}'.format(
                                sheet_name, _column_letters(col), row),
                            'old_formula': formula,
                            'new_formula': rewritten,
                        })
            finally:
                for value in (
                        formulas, data, end, start, cells, columns, rows,
                        used, sheet):
                    _release_com(value)
    finally:
        _release_com(sheets)
    return {
        'changed': changed_total,
        'zeroed': zeroed_total,
        'details': details,
    }


def _formula_error_tokens(value):
    """Return Excel error tokens embedded in a formula or literal value."""
    text = _text(value).upper()
    return [token for token in FORMULA_ERROR_TOKENS if token in text]


def _value_error_token(value):
    """Translate an Excel ErrorWrapper or displayed error string."""
    if value is None:
        return None
    try:
        code = int(value.ErrorCode) & 0xFFFF
        token = EXCEL_ERROR_CODE_TOKENS.get(code)
        if token:
            return token
    except Exception:
        pass
    text = _text(value).strip().upper()
    if text in FORMULA_ERROR_TOKENS:
        return text
    return None


def _scan_workbook_formula_errors(workbook):
    """Return every workbook error location as stable sheet/address tokens.

    Formula and value matrices are read once per sheet.  Range.FindNext is
    deliberately avoided: when a search wraps to its first match Excel can
    return the same RCW, and releasing the previous hit disconnects the object
    that the next iteration is about to use.
    """
    found = set()
    sheets = workbook.Worksheets
    try:
        for index in range(1, int(sheets.Count) + 1):
            sheet = sheets.Item(index)
            used = rows = columns = formulas = values = None
            try:
                sheet_name = _text(sheet.Name)
                used = sheet.UsedRange
                first_row = max(1, int(used.Row))
                first_col = max(1, int(used.Column))
                rows = used.Rows
                columns = used.Columns
                row_count = max(1, int(rows.Count))
                col_count = max(1, int(columns.Count))
                formulas = used.Formula
                values = used.Value2
                for row_offset in range(1, row_count + 1):
                    for col_offset in range(1, col_count + 1):
                        tokens = set(_formula_error_tokens(_matrix_value(
                            formulas, row_offset, col_offset,
                            row_count, col_count)))
                        value_token = _value_error_token(_matrix_value(
                            values, row_offset, col_offset,
                            row_count, col_count))
                        if value_token:
                            tokens.add(value_token)
                        if not tokens:
                            continue
                        row = first_row + row_offset - 1
                        col = first_col + col_offset - 1
                        address = u'${}${}'.format(
                            _column_letters(col), row)
                        for token in tokens:
                            found.add('{}!{}|{}'.format(
                                sheet_name, address, token))
            finally:
                for value in (
                        values, formulas, columns, rows, used, sheet):
                    _release_com(value)
    finally:
        _release_com(sheets)
    return found


def _merge_area_bounds(cell):
    """Return a merged cell's bounds, or ``None`` for a normal cell."""
    merge_area = None
    try:
        if not cell.MergeCells:
            return None
        merge_area = cell.MergeArea
        return (
            int(merge_area.Row),
            int(merge_area.Column),
            int(merge_area.Row) + int(merge_area.Rows.Count) - 1,
            int(merge_area.Column) + int(merge_area.Columns.Count) - 1,
        )
    except Exception:
        return None
    finally:
        _release_com(merge_area)


def _clear_values_preserving_merges(target_sheet, target_used):
    """Clear target values without unmerging or changing cell formatting."""
    try:
        target_used.ClearContents()
        return
    except Exception:
        # Excel may reject a UsedRange that clips a merged area.  Retry each
        # cell/complete merge area so the target layout remains untouched.
        pass

    first_row = int(target_used.Row)
    first_col = int(target_used.Column)
    last_row = first_row + int(target_used.Rows.Count) - 1
    last_col = first_col + int(target_used.Columns.Count) - 1
    handled = set()
    for row in range(first_row, last_row + 1):
        for col in range(first_col, last_col + 1):
            cell = None
            try:
                cell = target_sheet.Cells.Item(row, col)
                bounds = _merge_area_bounds(cell)
                if bounds is None:
                    cell.ClearContents()
                    continue
                if bounds in handled:
                    continue
                handled.add(bounds)
                top, left, bottom, right = bounds
                if (top < first_row or bottom > last_row or
                        left < first_col or right > last_col):
                    continue
                target_sheet.Range(
                    target_sheet.Cells.Item(top, left),
                    target_sheet.Cells.Item(bottom, right)).ClearContents()
            finally:
                _release_com(cell)


def _sheet_merge_addresses(sheet, row_count, col_count):
    """列出分頁在指定範圍內的所有合併範圍位址。

    先用「整列 MergeCells」篩掉沒有合併的列（回傳 False 代表整列都沒合併），
    只有少數幾列需要逐欄細掃，避免對數百列做逐格 COM 往返。
    """
    found = set()
    cells = sheet.Cells
    try:
        for row in range(1, row_count + 1):
            row_range = None
            try:
                row_range = sheet.Range(
                    cells.Item(row, 1), cells.Item(row, col_count))
                if row_range.MergeCells is False:
                    continue
            except Exception:
                pass
            finally:
                _release_com(row_range)
            col = 1
            while col <= col_count:
                cell = area = None
                try:
                    cell = cells.Item(row, col)
                    if not cell.MergeCells:
                        col += 1
                        continue
                    area = cell.MergeArea
                    found.add(_text(area.Address(False, False)))
                    col += max(1, int(area.Columns.Count))
                except Exception:
                    col += 1
                finally:
                    _release_com(area)
                    _release_com(cell)
    finally:
        _release_com(cells)
    return found


def _sync_merges(source_sheet, target_sheet, row_count, col_count):
    """讓目標分頁的合併範圍與來源一致。

    既有分頁刻意保留使用者的字型、填色、欄寬與列高，但「合併」不屬於使用者
    版面——合計列會隨資料列數上下移動。目標若留著上一輪合計列的合併，資料
    列數一變它就卡在資料中間，把該列 B:O 的內容整段藏起來（實測：舊的
    A662:O662 留在 668 列的新資料裡，第 662 列只看得到 A 欄）。
    """
    source_merges = _sheet_merge_addresses(source_sheet, row_count, col_count)
    target_merges = _sheet_merge_addresses(target_sheet, row_count, col_count)
    for address in sorted(target_merges - source_merges):
        stale = None
        try:
            stale = target_sheet.Range(address)
            stale.UnMerge()
        except Exception:
            pass
        finally:
            _release_com(stale)
    for address in sorted(source_merges - target_merges):
        wanted = None
        try:
            wanted = target_sheet.Range(address)
            wanted.UnMerge()
            wanted.Merge()
        except Exception:
            pass
        finally:
            _release_com(wanted)


def _copy_sheet_values(source_sheet, target_sheet):
    """Replace values/formulas without replacing target worksheet formatting."""
    source_used = None
    target_used = None
    source_rows = source_columns = target_columns = None
    source_formulas = None
    target_cells = None
    try:
        source_used = source_sheet.UsedRange
        target_used = target_sheet.UsedRange
        # Clear only values.  This deliberately keeps the desktop workbook's
        # fonts, fills, borders, widths, row heights and merge definitions.
        _clear_values_preserving_merges(target_sheet, target_used)

        source_rows = source_used.Rows
        source_columns = source_used.Columns
        row_count = max(1, int(source_rows.Count))
        col_count = max(1, int(source_columns.Count))
        first_row = int(source_used.Row)
        first_col = int(source_used.Column)
        source_formulas = source_used.Formula
        # 合併要在寫值之前同步：殘留的舊合併會讓該列非左上角的儲存格寫不進去
        _sync_merges(source_sheet, target_sheet, row_count, col_count)
        target_cells = target_sheet.Cells

        # Assign only non-empty cells so a target merge is never written to
        # through one of its non-top-left members.
        for row_offset in range(row_count):
            for col_offset in range(col_count):
                value = _matrix_value(
                    source_formulas, row_offset + 1, col_offset + 1,
                    row_count, col_count)
                if value is None or _text(value) == '':
                    continue
                target_cell = None
                try:
                    target_cell = target_cells.Item(
                        1 + row_offset, 1 + col_offset)
                    target_cell.Formula = value
                finally:
                    _release_com(target_cell)
    finally:
        _release_com(target_cells)
        _release_com(source_formulas)
        _release_com(source_columns)
        _release_com(source_rows)
        _release_com(target_used)
        _release_com(source_used)


def _copy_generated_row_fonts(source_sheet, target_sheet):
    """Apply generated row-role fonts while leaving all other target styling."""
    source_used = None
    target_used = None
    source_rows = source_columns = target_columns = None
    source_formulas = None
    source_cells = target_cells = None
    try:
        source_used = source_sheet.UsedRange
        target_used = target_sheet.UsedRange
        source_rows = source_used.Rows
        source_columns = source_used.Columns
        row_count = max(1, int(source_rows.Count))
        col_count = max(1, int(source_columns.Count))
        source_formulas = source_used.Formula
        source_first_row = int(source_used.Row)
        source_first_col = int(source_used.Column)
        target_columns = target_used.Columns
        target_last_col = max(
            1,
            int(target_used.Column) + int(target_columns.Count) - 1,
            source_first_col + col_count - 1)
        source_cells = source_sheet.Cells
        target_cells = target_sheet.Cells

        for row_offset in range(row_count):
            source_col = None
            for col_offset in range(col_count):
                value = _matrix_value(
                    source_formulas, row_offset + 1, col_offset + 1,
                    row_count, col_count)
                if value is not None and _text(value) != '':
                    source_col = source_first_col + col_offset
                    break
            if source_col is None:
                continue

            source_cell = source_font = target_range = target_font = None
            try:
                row_number = source_first_row + row_offset
                source_cell = source_cells.Item(row_number, source_col)
                source_font = source_cell.Font
                target_range = target_sheet.Range(
                    target_cells.Item(row_number, 1),
                    target_cells.Item(row_number, target_last_col))
                target_font = target_range.Font
                target_font.Name = source_font.Name
                target_font.Size = source_font.Size
                target_font.Bold = source_font.Bold
            finally:
                _release_com(target_font)
                _release_com(target_range)
                _release_com(source_font)
                _release_com(source_cell)
    finally:
        _release_com(target_cells)
        _release_com(source_cells)
        _release_com(source_formulas)
        _release_com(target_columns)
        _release_com(source_columns)
        _release_com(source_rows)
        _release_com(target_used)
        _release_com(source_used)


def _apply_generated_table_borders(source_sheet, target_sheet):
    """Apply a thin grid to the generated report range.

    The desktop workbook remains the source of truth for fills, merges,
    widths, row heights, and border colors.  The line style and weight are
    normalized here because an older target sheet may have no borders at all.
    Applying the six Excel edge/inside definitions covers every cell without
    clearing or rebuilding the existing worksheet layout.
    """
    source_used = None
    target_used = None
    source_rows = source_columns = target_rows = target_columns = None
    target_range = borders = None
    try:
        source_used = source_sheet.UsedRange
        target_used = target_sheet.UsedRange
        source_rows = source_used.Rows
        source_columns = source_used.Columns
        target_rows = target_used.Rows
        target_columns = target_used.Columns

        source_first_row = int(source_used.Row)
        source_first_col = int(source_used.Column)
        source_last_row = source_first_row + int(source_rows.Count) - 1
        source_last_col = source_first_col + int(source_columns.Count) - 1
        target_first_row = int(target_used.Row)
        target_first_col = int(target_used.Column)
        target_last_row = target_first_row + int(target_rows.Count) - 1
        target_last_col = target_first_col + int(target_columns.Count) - 1

        first_row = min(1, source_first_row, target_first_row)
        first_col = min(1, source_first_col, target_first_col)
        last_row = max(source_last_row, target_last_row)
        last_col = max(source_last_col, target_last_col)
        target_range = target_sheet.Range(
            target_sheet.Cells.Item(first_row, first_col),
            target_sheet.Cells.Item(last_row, last_col))
        borders = target_range.Borders
        # Setting the collection applies the outer and inner grid in one COM
        # call. Do not iterate Borders.Item here: Excel can return shared RCWs
        # for those child objects, and releasing one child can detach the RCW
        # used by the next child.
        borders.LineStyle = 1  # xlContinuous
        try:
            borders.Weight = 2  # xlThin
        except Exception:
            pass
    finally:
        _release_com(borders)
        _release_com(target_range)
        _release_com(target_columns)
        _release_com(target_rows)
        _release_com(source_columns)
        _release_com(source_rows)
        _release_com(target_used)
        _release_com(source_used)


def _copy_sheet_contents(source_sheet, target_sheet, app):
    """Replace contents while preserving the target worksheet identity/style."""
    _copy_sheet_values(source_sheet, target_sheet)
    _copy_generated_row_fonts(source_sheet, target_sheet)
    _apply_generated_table_borders(source_sheet, target_sheet)


def _clear_beyond_generated(target_sheet, row_count, col_count):
    """清掉超出來源範圍的殘留列／欄。

    Range.Copy 只會覆寫「貼上範圍內」的內容與合併，範圍外原封不動。所以某一
    輪產出的列數比上一輪少時，下方會留著前一版的資料列與合併——畫面上像資料
    中間插了一段舊內容（實測：舊合計列的 A662:O662 卡在新資料中間，把
    B662:O662 藏起來）。這張分頁由發布流程全權管理，超出來源範圍的一律清除。
    """
    cells = used = None
    try:
        cells = target_sheet.Cells
        used = target_sheet.UsedRange
        last_row = int(used.Row) + int(used.Rows.Count) - 1
        last_col = int(used.Column) + int(used.Columns.Count) - 1
    except Exception:
        _release_com(used)
        _release_com(cells)
        return
    try:
        if last_row > row_count:
            tail = None
            try:
                tail = target_sheet.Range(
                    cells.Item(row_count + 1, 1),
                    cells.Item(last_row, max(last_col, col_count)))
                tail.UnMerge()
                tail.Clear()
            except Exception:
                pass
            finally:
                _release_com(tail)
        if last_col > col_count:
            side = None
            try:
                side = target_sheet.Range(
                    cells.Item(1, col_count + 1),
                    cells.Item(max(last_row, row_count), last_col))
                side.UnMerge()
                side.Clear()
            except Exception:
                pass
            finally:
                _release_com(side)
    finally:
        _release_com(used)
        _release_com(cells)


def _copy_generated_sheet_to_new_target(source_sheet, target_sheet, app):
    """Populate a new target sheet without copying the whole worksheet.

    Excel refuses to insert an OpenXML worksheet into a legacy ``.xls``
    workbook because the two formats have different row and column limits.
    Copying only the source UsedRange is supported and retains cell formats
    and merges. Column widths and row heights are transferred separately.
    """
    source_used = source_used_rows = source_used_columns = None
    target_rows = target_columns = target_cells = target_start = None
    source_columns = source_rows = None
    try:
        source_used = source_sheet.UsedRange
        source_used_rows = source_used.Rows
        source_used_columns = source_used.Columns
        row_count = max(1, int(source_used_rows.Count))
        col_count = max(1, int(source_used_columns.Count))
        source_first_row = max(1, int(source_used.Row))
        source_first_col = max(1, int(source_used.Column))

        target_rows = target_sheet.Rows
        target_columns = target_sheet.Columns
        if row_count > int(target_rows.Count):
            raise Exception(
                'Generated worksheet has {} rows but the target format '
                'supports only {}.'.format(row_count, target_rows.Count))
        if col_count > int(target_columns.Count):
            raise Exception(
                'Generated worksheet has {} columns but the target format '
                'supports only {}.'.format(col_count, target_columns.Count))

        target_cells = target_sheet.Cells
        target_start = target_cells.Item(1, 1)

        # 這張分頁由本函式整片覆寫，來源才是合併範圍的唯一依據。殘留的舊合併
        # 不會被貼上動作清掉：資料列數一變（例如合計列從 662 移到 668），舊的
        # A662:O662 就卡在資料中間，把貼進去的 B662:O662 藏起來，新的合計列
        # 合併也貼不上去。所以先解除目標既有的合併。
        target_used = None
        try:
            target_used = target_sheet.UsedRange
            target_used.UnMerge()
        except Exception:
            pass
        finally:
            _release_com(target_used)

        source_used.Copy(target_start)

        _clear_beyond_generated(target_sheet, row_count, col_count)

        source_columns = source_sheet.Columns
        for col_offset in range(col_count):
            source_column = target_column = None
            try:
                source_column = source_columns.Item(
                    source_first_col + col_offset)
                target_column = target_columns.Item(1 + col_offset)
                target_column.ColumnWidth = source_column.ColumnWidth
            finally:
                _release_com(target_column)
                _release_com(source_column)

        source_rows = source_sheet.Rows
        for row_offset in range(row_count):
            source_row = target_row = None
            try:
                source_row = source_rows.Item(source_first_row + row_offset)
                target_row = target_rows.Item(1 + row_offset)
                target_row.RowHeight = source_row.RowHeight
            finally:
                _release_com(target_row)
                _release_com(source_row)
    finally:
        for value in (
                source_rows, source_columns,
                target_start, target_cells, target_columns, target_rows,
                source_used_columns, source_used_rows, source_used):
            _release_com(value)

    # Re-write formulas as literal Formula values after the range copy so
    # Excel does not retain an external link to the temporary source workbook.
    _copy_sheet_contents(source_sheet, target_sheet, app)


def _calculate_full(app):
    try:
        app.CalculateFullRebuild()
    except Exception:
        app.Calculate()


def publish_generated_workbook(workbook_path, generated_path,
                               managed_sheet_names, summary_specs=None,
                               index_sheet_name=DEFAULT_INDEX_SHEET):
    """Copy managed sheets from a generated workbook into an existing one.

    A timestamped sibling backup is created before Excel opens the target.
    The target is saved only after every sheet copy and formula-error scan
    succeeds.  On failure it is closed without saving; the backup is retained.
    """
    target_path = os.path.abspath(workbook_path)
    source_path = os.path.abspath(generated_path)
    mappings = _managed_sheet_mappings(managed_sheet_names)
    if not os.path.isfile(target_path):
        raise WorkbookPublishError(
            'The main Excel workbook does not exist: {}'.format(target_path))
    if not os.path.isfile(source_path):
        raise WorkbookPublishError(
            'The generated takeoff workbook does not exist: {}'.format(
                source_path))
    if not mappings:
        raise WorkbookPublishError('No managed worksheet names were supplied.')
    if os.path.normcase(target_path) == os.path.normcase(source_path):
        raise WorkbookPublishError(
            'The generated workbook must not be the main workbook.')

    backup_path = make_backup_path(target_path)
    try:
        import shutil
        shutil.copy2(target_path, backup_path)
    except Exception as exc:
        raise WorkbookPublishError(
            'Could not create a backup before updating Excel: {}'.format(exc))

    app = None
    workbooks = None
    source_book = None
    target_book = None
    saved = False
    failed = False
    stage = 'starting Excel'
    index_result = {'changed': 0, 'zeroed': 0, 'details': []}
    try:
        from System import Activator, Type
        xl_type = Type.GetTypeFromProgID('Excel.Application')
        if xl_type is None:
            raise Exception(
                'Microsoft Excel is not installed or COM is unavailable.')
        app = Activator.CreateInstance(xl_type)
        app.Visible = False
        app.DisplayAlerts = False
        app.AskToUpdateLinks = False
        try:
            app.EnableEvents = False
            app.AutomationSecurity = 3
            app.ScreenUpdating = False
        except Exception:
            pass

        stage = 'opening generated workbook'
        workbooks = app.Workbooks
        source_book = workbooks.Open(source_path, 0, True)
        stage = 'opening main workbook'
        target_book = workbooks.Open(target_path, 0, False)
        # Establish the baseline after a full calculation.  Otherwise an old
        # but not-yet-recalculated error could first appear after publication
        # and be incorrectly blamed on the new managed sheets.
        stage = 'initial workbook calculation'
        _calculate_full(app)
        stage = 'scanning generated workbook formulas'
        source_errors = sorted(list(
            _scan_workbook_formula_errors(source_book)))
        if source_errors:
            raise Exception(
                'Generated takeoff workbook contains formula errors: {}'
                .format('; '.join(source_errors)))
        stage = 'scanning main workbook baseline formulas'
        baseline_errors = _scan_workbook_formula_errors(target_book)
        stage = 'preparing summary formula updates'
        rebase_plans = _prepare_summary_rebases(
            source_book, target_book, mappings, summary_specs)
        stage = 'validating existing summary formula references'
        existing_contract_issues = _scan_index_summary_contract(
            target_book, index_sheet_name, rebase_plans, 'old_row')
        if existing_contract_issues:
            raise Exception(
                'Existing index formulas do not reference the labelled '
                'summary rows: {}'.format(
                    '; '.join(existing_contract_issues)))
        stage = 'validating generated summary formula ranges'
        generated_contract_issues = _scan_managed_summary_contract(
            source_book, rebase_plans, True)
        if generated_contract_issues:
            raise Exception(
                'Generated summary formulas do not cover the complete data '
                'region: {}'.format(
                    '; '.join(generated_contract_issues)))

        for source_name, target_name in mappings:
            stage = 'copying worksheet {}'.format(target_name)
            source_sheet = _worksheet_by_name(source_book, source_name)
            if source_sheet is None:
                raise Exception(
                    'Generated workbook is missing worksheet: {}'.format(
                        source_name))
            old_sheet = None
            last_sheet = None
            new_sheet = None
            target_sheets = None
            try:
                old_sheet = _worksheet_by_name(target_book, target_name)
                if old_sheet is not None:
                    _copy_sheet_contents(
                        source_sheet, old_sheet, app)
                else:
                    target_sheets = target_book.Worksheets
                    last_sheet = target_sheets.Item(target_sheets.Count)
                    # Add a target-format sheet first, then copy only the used
                    # range. Copying an entire .xlsx worksheet into .xls fails
                    # because their maximum row/column counts differ.
                    new_sheet = target_sheets.Add(last_sheet)
                    new_sheet.Name = target_name
                    _copy_generated_sheet_to_new_target(
                        source_sheet, new_sheet, app)
            finally:
                _release_com(new_sheet)
                _release_com(last_sheet)
                _release_com(target_sheets)
                _release_com(old_sheet)
                _release_com(source_sheet)

        stage = 'updating summary formulas'
        index_result = _apply_summary_rebases(
            target_book, index_sheet_name, rebase_plans)
        stage = 'validating updated summary formula references'
        updated_contract_issues = _scan_index_summary_contract(
            target_book, index_sheet_name, rebase_plans, 'new_row')
        if updated_contract_issues:
            raise Exception(
                'Updated index formulas do not reference the new labelled '
                'summary rows: {}'.format(
                    '; '.join(updated_contract_issues)))
        stage = 'validating copied summary formula ranges'
        copied_contract_issues = _scan_managed_summary_contract(
            target_book, rebase_plans, False)
        if copied_contract_issues:
            raise Exception(
                'Copied summary formulas do not cover the complete data '
                'region: {}'.format('; '.join(copied_contract_issues)))
        stage = 'final workbook calculation'
        _calculate_full(app)
        stage = 'scanning final workbook formulas'
        final_errors = _scan_workbook_formula_errors(target_book)
        new_errors = sorted(list(final_errors.difference(baseline_errors)))
        if new_errors:
            raise Exception(
                'Excel formula validation found new errors: {}'.format(
                    '; '.join(new_errors)))

        stage = 'saving main workbook'
        target_book.Save()
        saved = True
        return {
            'workbook_path': target_path,
            'backup_path': backup_path,
            'managed_sheets': [item[1] for item in mappings],
            'index_rebases': index_result,
        }
    except Exception as exc:
        failed = True
        message = (
            'Main Excel workbook update failed. The original was not '
            'intentionally overwritten and will be restored from its backup '
            'when possible. Backup: {}. Stage: {}. Error: {}'
            .format(backup_path, stage, exc))
        raise WorkbookPublishError(message, backup_path)
    finally:
        if source_book is not None:
            try:
                source_book.Close(False)
            except Exception:
                pass
        if target_book is not None:
            try:
                target_book.Close(bool(saved))
            except Exception:
                pass
        if app is not None:
            try:
                app.DisplayAlerts = True
            except Exception:
                pass
            try:
                app.EnableEvents = True
                app.ScreenUpdating = True
            except Exception:
                pass
            try:
                app.Quit()
            except Exception:
                pass
        _release_com(source_book)
        _release_com(target_book)
        _release_com(workbooks)
        _release_com(app)
        try:
            from System import GC
            GC.Collect()
            GC.WaitForPendingFinalizers()
            GC.Collect()
            GC.WaitForPendingFinalizers()
        except Exception:
            pass
        if failed and os.path.isfile(backup_path):
            try:
                shutil.copy2(backup_path, target_path)
            except Exception:
                # The recoverable backup is intentionally retained even when
                # a file lock prevents the automatic restore.
                pass
