# -*- coding: utf-8 -*-
"""Excel contract and validation for the Taiwan building-code input checker.

The pyRevit button deliberately keeps Revit API calls out of this module.  It
builds simple ``.xlsx`` sheet specifications for the existing OpenXML writer
and reads only the standard worksheet parts needed by this button.  Import is
treated as a controlled patch operation: users may edit only the proposed
value column; keys and identity columns are checked before any Revit
transaction is considered.

This module is compatible with IronPython 2.7 and CPython so its rules can be
unit-tested without Revit.
"""

from __future__ import unicode_literals
from __future__ import print_function

import datetime
import os
import re
import zipfile

try:
    import xml.etree.ElementTree as ElementTree
except ImportError:
    ElementTree = None

import xlsx_xml


CONTRACT_VERSION = u'1.0'
WORKBOOK_TYPE = u'taiwan-building-code-model-integrity'

INFO_SHEET = u'說明'
PROJECT_SHEET = u'專案輸入'
AREA_SHEET = u'Area輸入'
FINDINGS_SHEET = u'檢核結果'

INFO_HEADERS = [u'欄位', u'內容']
INPUT_HEADERS = [
    u'Key', u'範圍', u'ElementId', u'元素名稱', u'參數名稱',
    u'儲存類型', u'目前值', u'新值（可編輯）', u'存在', u'唯讀',
    u'資料狀態', u'備註',
]
FINDING_HEADERS = [u'Status', u'Id', u'Message', u'Reference']

KEY_HEADER = INPUT_HEADERS[0]
SCOPE_HEADER = INPUT_HEADERS[1]
ELEMENT_ID_HEADER = INPUT_HEADERS[2]
ELEMENT_NAME_HEADER = INPUT_HEADERS[3]
PARAMETER_HEADER = INPUT_HEADERS[4]
STORAGE_HEADER = INPUT_HEADERS[5]
CURRENT_HEADER = INPUT_HEADERS[6]
PROPOSED_HEADER = INPUT_HEADERS[7]

_XML_MAIN = u'{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
_XML_REL = u'{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
_XML_PACKAGE_REL = u'{http://schemas.openxmlformats.org/package/2006/relationships}'
_CELL_REF_RE = re.compile(r'^([A-Za-z]+)([0-9]+)$')

try:
    _TEXT_TYPE = unicode  # noqa: F821  (IronPython 2 only)
    _BINARY_TYPE = str
except NameError:
    _TEXT_TYPE = str
    _BINARY_TYPE = bytes


class WorkbookError(Exception):
    """A user-facing workbook contract or parsing error."""


def _text(value):
    if value is None:
        return u''
    if isinstance(value, _TEXT_TYPE):
        return value
    if isinstance(value, _BINARY_TYPE):
        try:
            return value.decode('utf-8')
        except Exception:
            return value.decode('cp950', 'replace')
    try:
        return _TEXT_TYPE(value)
    except Exception:
        return u'{}'.format(value)


def _strip(value):
    return _text(value).strip()


def _now_local_text():
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def make_key(scope, element_id, parameter_name):
    """Return the stable identity used to match an Excel row to the model."""
    try:
        element_id = int(element_id)
    except (TypeError, ValueError):
        element_id = 0
    return u'{}|{}|{}'.format(
        _strip(scope), element_id, _strip(parameter_name))


def row_key(row):
    return make_key(row.get('scope'), row.get('element_id'),
                    row.get('parameter_name'))


def _bool_label(value):
    return u'是' if bool(value) else u'否'


def _row_note(row):
    if not row.get('exists'):
        return u'參數不存在；不可匯回。'
    if row.get('readonly'):
        return u'唯讀參數；不可匯回。'
    storage = _strip(row.get('storage'))
    if storage not in (u'String', u'Integer', u'Double'):
        return u'不支援的 Revit 儲存類型；不可匯回。'
    return u'只編輯「新值（可編輯）」；Key 與識別欄不可修改。'


def _as_element_id(value):
    text = _strip(value)
    if not re.match(r'^[+-]?[0-9]+$', text):
        return None
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def parse_integer(value):
    """Parse the same integer convention used by the Revit button."""
    normalized = _strip(value)
    if normalized.endswith(u'%'):
        normalized = normalized[:-1].strip()
    if not re.match(r'^[+-]?[0-9]+$', normalized):
        return None
    try:
        return int(normalized)
    except (TypeError, ValueError):
        return None


def validate_proposed(storage, value):
    """Return ``None`` when a proposed cell is valid for its storage type."""
    storage = _strip(storage)
    value = _text(value)
    stripped = value.strip()
    if not stripped:
        return u'新值不可為空白；本工具不以空白清除模型值。'
    if stripped.startswith(u'='):
        return u'新值不可使用 Excel 公式；請貼上計算後的實際值。'
    if u'\x00' in value:
        return u'新值含有無法寫入 Revit 的控制字元。'
    if storage == u'Integer' and parse_integer(value) is None:
        return u'整數欄位請輸入整數；百分比可寫成 60 或 60%。'
    if storage not in (u'String', u'Integer', u'Double'):
        return u'不支援 {} 參數類型。'.format(storage or u'(未知)')
    return None


def _input_rows(rows):
    output = [list(INPUT_HEADERS)]
    for row in rows or []:
        element_id = row.get('element_id')
        try:
            element_id = int(element_id)
        except (TypeError, ValueError):
            element_id = 0
        output.append([
            row_key(row),
            _text(row.get('scope')),
            element_id,
            _text(row.get('element_name')),
            _text(row.get('parameter_name')),
            _text(row.get('storage')),
            _text(row.get('current')),
            _text(row.get('proposed')),
            _bool_label(row.get('exists')),
            _bool_label(row.get('readonly')),
            _text(row.get('value_status')),
            _row_note(row),
        ])
    return output


def _input_spec():
    return {
        'widths': [38, 20, 13, 28, 32, 16, 28, 28, 10, 10, 18, 42],
        'formats': {3: xlsx_xml.STYLE_INT},
        'freeze': 1,
    }


def _finding_rows(audit):
    rows = [list(FINDING_HEADERS)]
    for finding in (audit or {}).get('Findings') or []:
        rows.append([
            _text(finding.get('Status')),
            _text(finding.get('Id')),
            _text(finding.get('Message')),
            _text(finding.get('Reference')),
        ])
    return rows


def _metadata(audit, model_title, revit_version, exported_at=None):
    audit = audit or {}
    checked_at = _text(audit.get('CheckedAtUtc'))
    audit_id = _text(audit.get('AuditRunId'))
    return [
        (u'ContractVersion', CONTRACT_VERSION),
        (u'WorkbookType', WORKBOOK_TYPE),
        (u'ModelTitle', _text(model_title)),
        (u'RevitVersion', _text(revit_version)),
        (u'AuditRunId', audit_id),
        (u'CheckedAtUtc', checked_at),
        (u'ExportedAtLocal', _text(exported_at) or _now_local_text()),
        (u'RulePackId', _text(audit.get('RulePackId')) or
         u'taiwan-building-code-model-integrity'),
        (u'EditInstruction',
         u'只編輯「專案輸入」或「Area輸入」的「新值（可編輯）」欄；'
         u'不要修改 Key、範圍、ElementId、參數名稱、儲存類型。'),
        (u'ImportFlow', u'匯回後只建立預覽變更，必須回到 Revit 按「套用變更」才會寫入。'),
        (u'GeneratedBy', u'RevitMCP｜台灣建築法規模型資料完整性檢查器'),
    ]


def build_workbook(project_rows, area_rows, audit, model_title,
                   revit_version, exported_at=None):
    """Return ``(sheets, metadata)`` for :func:`xlsx_writer.write_workbook`."""
    metadata = _metadata(audit, model_title, revit_version, exported_at)
    info_rows = [list(INFO_HEADERS)] + [[key, value]
                                        for key, value in metadata]
    findings = _finding_rows(audit)
    sheets = [
        (INFO_SHEET, info_rows,
         {'widths': [24, 92], 'freeze': 1}),
        (PROJECT_SHEET, _input_rows(project_rows), _input_spec()),
        (AREA_SHEET, _input_rows(area_rows), _input_spec()),
        (FINDINGS_SHEET, findings,
         {'widths': [14, 26, 84, 64], 'freeze': 1}),
    ]
    return sheets, dict(metadata)


def _column_index(letters):
    value = 0
    for character in _text(letters).upper():
        if character < 'A' or character > 'Z':
            raise WorkbookError(u'Excel 儲存格欄位無效：{}'.format(letters))
        value = value * 26 + (ord(character) - ord('A') + 1)
    return value


def _cell_reference(cell):
    match = _CELL_REF_RE.match(_text(cell))
    if not match:
        return None, None
    return _column_index(match.group(1)), int(match.group(2))


def _element_text(element, tag):
    if element is None:
        return u''
    parts = []
    for item in element.iter(_XML_MAIN + tag):
        parts.append(_text(item.text))
    return u''.join(parts)


def _shared_strings(package):
    if 'xl/sharedStrings.xml' not in package.namelist():
        return []
    try:
        root = ElementTree.fromstring(package.read('xl/sharedStrings.xml'))
    except Exception as error:
        raise WorkbookError(u'Excel sharedStrings.xml 無法解析：{}'.format(error))
    values = []
    for item in root.findall(_XML_MAIN + 'si'):
        values.append(_element_text(item, 't'))
    return values


def _cell_value(cell, shared_strings):
    cell_type = _text(cell.attrib.get('t'))
    formula = cell.find(_XML_MAIN + 'f') is not None
    if cell_type == u'inlineStr':
        value = _element_text(cell.find(_XML_MAIN + 'is'), 't')
    else:
        value_node = cell.find(_XML_MAIN + 'v')
        value = _text(value_node.text if value_node is not None else u'')
        if cell_type == u's' and value:
            try:
                value = shared_strings[int(value)]
            except (IndexError, TypeError, ValueError):
                raise WorkbookError(u'Excel shared string 索引無效：{}'.format(value))
        elif cell_type == u'b':
            value = u'是' if value == u'1' else u'否'
    return value, formula


def _workbook_sheet_targets(package):
    required = ['xl/workbook.xml', 'xl/_rels/workbook.xml.rels']
    for name in required:
        if name not in package.namelist():
            raise WorkbookError(u'Excel 活頁簿缺少必要檔案：{}'.format(name))
    try:
        workbook = ElementTree.fromstring(package.read('xl/workbook.xml'))
        relationships = ElementTree.fromstring(
            package.read('xl/_rels/workbook.xml.rels'))
    except Exception as error:
        raise WorkbookError(u'Excel 活頁簿索引無法解析：{}'.format(error))

    rel_targets = {}
    for relationship in relationships.findall(_XML_PACKAGE_REL + 'Relationship'):
        target = _text(relationship.attrib.get('Target'))
        if target.startswith(u'/'):
            target = target[1:]
        elif not target.startswith(u'xl/'):
            target = u'xl/' + target
        rel_targets[_text(relationship.attrib.get('Id'))] = target

    result = []
    sheets = workbook.find(_XML_MAIN + 'sheets')
    if sheets is None:
        raise WorkbookError(u'Excel 活頁簿沒有工作表。')
    for sheet in sheets.findall(_XML_MAIN + 'sheet'):
        name = _text(sheet.attrib.get('name'))
        relationship_id = _text(sheet.attrib.get(_XML_REL + 'id'))
        target = rel_targets.get(relationship_id)
        if not target:
            raise WorkbookError(u'工作表「{}」找不到關聯檔案。'.format(name))
        result.append((name, target))
    return result


def _read_sheet(package, target, shared_strings):
    if target not in package.namelist():
        raise WorkbookError(u'工作表檔案不存在：{}'.format(target))
    try:
        root = ElementTree.fromstring(package.read(target))
    except Exception as error:
        raise WorkbookError(u'工作表「{}」無法解析：{}'.format(target, error))
    sheet_data = root.find(_XML_MAIN + 'sheetData')
    rows = []
    formula_cells = set()
    if sheet_data is None:
        return {'rows': rows, 'formula_cells': formula_cells}
    for row_node in sheet_data.findall(_XML_MAIN + 'row'):
        row_number = int(row_node.attrib.get('r') or len(rows) + 1)
        cells = {}
        for cell in row_node.findall(_XML_MAIN + 'c'):
            column, explicit_row = _cell_reference(cell.attrib.get('r'))
            if column is None:
                continue
            value, formula = _cell_value(cell, shared_strings)
            cells[column] = value
            if formula:
                formula_cells.add((row_number, column))
            if explicit_row is not None:
                row_number = explicit_row
        width = max(cells.keys()) if cells else 0
        rows.append({
            'row_number': row_number,
            'values': [cells.get(index, u'') for index in range(1, width + 1)],
        })
    return {'rows': rows, 'formula_cells': formula_cells}


def read_workbook(path):
    """Read the small subset of `.xlsx` OpenXML needed by this contract."""
    path = os.path.abspath(_text(path))
    if os.path.splitext(path)[1].lower() != u'.xlsx':
        raise WorkbookError(u'只支援新的 Excel 活頁簿 .xlsx；不直接讀取 .xls。')
    if not os.path.isfile(path):
        raise WorkbookError(u'找不到 Excel 檔案：{}'.format(path))
    if ElementTree is None:
        raise WorkbookError(u'目前 Python 環境缺少 XML 解析器。')
    try:
        package = zipfile.ZipFile(path, 'r')
    except Exception as error:
        raise WorkbookError(u'檔案不是可讀取的 .xlsx 活頁簿：{}'.format(error))
    try:
        shared_strings = _shared_strings(package)
        sheets = {}
        for name, target in _workbook_sheet_targets(package):
            sheets[name] = _read_sheet(package, target, shared_strings)
        return {'path': path, 'sheets': sheets}
    finally:
        package.close()


def _table(sheet, required_headers, sheet_name):
    if sheet is None:
        raise WorkbookError(u'缺少工作表「{}」。'.format(sheet_name))
    raw_rows = sheet.get('rows') or []
    if not raw_rows:
        raise WorkbookError(u'工作表「{}」沒有標題列。'.format(sheet_name))
    header_row = raw_rows[0].get('values') or []
    headers = [_text(item).strip() for item in header_row]
    header_index = {}
    for index, header in enumerate(headers):
        if header:
            if header in header_index:
                raise WorkbookError(u'工作表「{}」有重複欄位「{}」。'.format(
                    sheet_name, header))
            header_index[header] = index
    missing = [header for header in required_headers
               if header not in header_index]
    if missing:
        raise WorkbookError(u'工作表「{}」缺少欄位：{}。'.format(
            sheet_name, u'、'.join(missing)))
    records = []
    for raw_row in raw_rows[1:]:
        values = raw_row.get('values') or []
        record = {}
        for header, index in header_index.items():
            record[header] = values[index] if index < len(values) else u''
        record['_row_number'] = raw_row.get('row_number')
        formula_columns = set(
            column for row_number, column in sheet.get('formula_cells') or set()
            if row_number == raw_row.get('row_number'))
        record['_formula_columns'] = formula_columns
        record['_formula_headers'] = set(
            header for header, index in header_index.items()
            if index in formula_columns)
        if any(_strip(value) for value in record.values()
               if not isinstance(value, set)):
            records.append(record)
    return records


def _manifest(sheet):
    records = _table(sheet, INFO_HEADERS, INFO_SHEET)
    result = {}
    for record in records:
        key = _strip(record.get(INFO_HEADERS[0]))
        value = _text(record.get(INFO_HEADERS[1]))
        if not key:
            continue
        if key in result:
            raise WorkbookError(u'「說明」工作表重複欄位「{}」。'.format(key))
        result[key] = value
    return result


def _same_value(actual, expected):
    return _strip(actual) == _strip(expected)


def _identity_error(record, current, header, expected):
    actual = record.get(header)
    if header == ELEMENT_ID_HEADER:
        actual_id = _as_element_id(actual)
        try:
            expected_id = int(current.get('element_id'))
        except (TypeError, ValueError):
            expected_id = 0
        if actual_id != expected_id:
            return u'{} 應為 {}，實際為 {}。'.format(
                header, expected_id, _text(actual))
        return None
    if not _same_value(actual, expected):
        return u'{} 與目前模型列不一致（應為「{}」，實際為「{}」）。'.format(
            header, _text(expected), _text(actual))
    return None


def import_workbook(path, project_rows, area_rows, expected_model_title=u'',
                    expected_revit_version=u''):
    """Validate an Excel file and return proposed patches without mutating rows.

    Return keys:
    ``changes`` contains ``key``, ``value``, ``row`` and ``sheet``;
    ``warnings`` are non-blocking metadata/current-value drift notices;
    ``errors`` block merging and model writes.
    """
    package = read_workbook(path)
    sheets = package.get('sheets') or {}
    errors = []
    warnings = []
    try:
        manifest = _manifest(sheets.get(INFO_SHEET))
        project_records = _table(sheets.get(PROJECT_SHEET), INPUT_HEADERS,
                                 PROJECT_SHEET)
        area_records = _table(sheets.get(AREA_SHEET), INPUT_HEADERS, AREA_SHEET)
    except WorkbookError as error:
        return {
            'path': package.get('path'), 'metadata': {}, 'changes': [],
            'warnings': [], 'errors': [_text(error)],
        }

    if manifest.get('ContractVersion') != CONTRACT_VERSION:
        errors.append(u'Excel 契約版本不符：需要 {}，實際為 {}。'.format(
            CONTRACT_VERSION, manifest.get('ContractVersion') or u'(空白)'))
    if manifest.get('WorkbookType') != WORKBOOK_TYPE:
        errors.append(u'這不是台灣建築法規模型資料完整性檢查器匯出的活頁簿。')
    if expected_model_title and manifest.get('ModelTitle') and not _same_value(
            manifest.get('ModelTitle'), expected_model_title):
        warnings.append(u'Excel 的 ModelTitle 與目前模型不同；仍會以 Key 逐列比對。')
    if expected_revit_version and manifest.get('RevitVersion') and not _same_value(
            manifest.get('RevitVersion'), expected_revit_version):
        warnings.append(u'Excel 的 RevitVersion 與目前版本不同；Double 值仍交由目前專案單位解析。')

    current_rows = list(project_rows or []) + list(area_rows or [])
    current_by_key = {}
    for row in current_rows:
        key = row_key(row)
        if key in current_by_key:
            errors.append(u'目前模型產生重複 Key：{}。'.format(key))
        current_by_key[key] = row

    changes = []
    seen = set()
    for sheet_name, records in ((PROJECT_SHEET, project_records),
                                (AREA_SHEET, area_records)):
        for record in records:
            row_number = record.get('_row_number')
            key = _strip(record.get(KEY_HEADER))
            if not key:
                # Completely blank rows were already discarded; a row with
                # only notes is not a valid import row and must not be silent.
                if any(_strip(record.get(header)) for header in INPUT_HEADERS
                       if header != KEY_HEADER):
                    errors.append(u'{} 第 {} 列缺少 Key。'.format(
                        sheet_name, row_number))
                continue
            if key in seen:
                errors.append(u'Excel 的 Key 重複：{}（{} 第 {} 列）。'.format(
                    key, sheet_name, row_number))
                continue
            seen.add(key)
            current = current_by_key.get(key)
            if current is None:
                errors.append(u'{} 第 {} 列的 Key 不存在於目前模型：{}。'.format(
                    sheet_name, row_number, key))
                continue

            identity_checks = [
                (SCOPE_HEADER, current.get('scope')),
                (ELEMENT_ID_HEADER, current.get('element_id')),
                (PARAMETER_HEADER, current.get('parameter_name')),
                (STORAGE_HEADER, current.get('storage')),
            ]
            for header, expected in identity_checks:
                identity_error = _identity_error(record, current, header, expected)
                if identity_error:
                    errors.append(u'{} 第 {} 列：{}。'.format(
                        sheet_name, row_number, identity_error))

            imported_current = _text(record.get(CURRENT_HEADER))
            if imported_current != _text(current.get('current')):
                warnings.append(u'{} 第 {} 列的目前值與模型已不同；將以匯入的新值預覽。'.format(
                    sheet_name, row_number))

            proposed = _text(record.get(PROPOSED_HEADER))
            if PROPOSED_HEADER in record.get('_formula_headers') or proposed.strip().startswith(u'='):
                errors.append(u'{} 第 {} 列的新值不可是 Excel 公式。'.format(
                    sheet_name, row_number))
                continue
            if proposed.strip() == _text(current.get('current')).strip():
                continue
            if not proposed.strip():
                continue
            if not current.get('exists'):
                errors.append(u'{} 第 {} 列：參數不存在，不能匯回。'.format(
                    sheet_name, row_number))
                continue
            if current.get('readonly'):
                errors.append(u'{} 第 {} 列：參數唯讀，不能匯回。'.format(
                    sheet_name, row_number))
                continue
            validation_error = validate_proposed(current.get('storage'), proposed)
            if validation_error:
                errors.append(u'{} 第 {} 列：{}。'.format(
                    sheet_name, row_number, validation_error))
                continue
            changes.append({
                'key': key,
                'value': proposed,
                'row': current,
                'sheet': sheet_name,
                'row_number': row_number,
            })

    if errors:
        changes = []
    return {
        'path': package.get('path'),
        'metadata': manifest,
        'changes': changes,
        'warnings': warnings,
        'errors': errors,
    }


def merge_changes(rows, changes):
    """Apply validated proposed values to the in-memory UI rows only."""
    by_key = dict((row_key(row), row) for row in rows or [])
    applied = 0
    for change in changes or []:
        row = by_key.get(change.get('key'))
        if row is None:
            continue
        row['proposed'] = _text(change.get('value'))
        applied += 1
    return applied
