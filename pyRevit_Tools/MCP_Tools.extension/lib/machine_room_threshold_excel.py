# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Revit door reader and guarded Excel COM updater for machine-room thresholds.

The threshold length is computed entirely from Revit: rooms are classified in
Revit, doors touching a selected machine room are collected, their widths are
summed, and the total is written as ``=SUM(...)`` into the single
"不銹鋼門檻機房" length cell. Excel is used only to locate that target cell —
no source-sheet room list and no quantity*length chain formula is required.
"""

import os
import re
import shutil
from datetime import datetime

from pyrevit import DB, forms
from System import Activator, GC, Type
from System.Runtime.InteropServices import Marshal
from System.Windows import Thickness, Visibility
from System.Windows.Controls import CheckBox

import machine_room_threshold_logic as logic
import room_takeoff_sources_logic as room_order_logic
import takeoff_entry
import takeoff_standalone

try:
    reload(logic)
except Exception:
    pass


TITLE = u'不鏽鋼門檻（機房）Excel'
XL_CALCULATION_AUTOMATIC = -4105
# Read caps per worksheet. Hitting a cap is reported (and blocks the write when
# that sheet carries the item label) rather than silently truncating the scan.
MAX_SHEET_ROWS = 3000
MAX_SHEET_COLS = 80


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value).strip()
    except Exception:
        return str(value).strip()


def _id_value(value):
    for name in ('Value', 'IntegerValue'):
        try:
            return int(getattr(value, name))
        except Exception:
            pass
    try:
        return int(value)
    except Exception:
        return None


def _excel_open(path, read_only):
    xl_type = Type.GetTypeFromProgID('Excel.Application')
    if xl_type is None:
        raise Exception(u'找不到 Excel COM；此功能需要本機安裝 Microsoft Excel。')
    excel = Activator.CreateInstance(xl_type)
    excel.Visible = False
    excel.DisplayAlerts = False
    try:
        excel.EnableEvents = False
        excel.AskToUpdateLinks = False
        excel.AutomationSecurity = 3
    except Exception:
        pass
    workbooks = None
    try:
        workbooks = excel.Workbooks
        workbook = workbooks.Open(path, 0, bool(read_only))
    except Exception:
        try:
            excel.Quit()
        except Exception:
            pass
        raise
    finally:
        _release_com(workbooks)
    return excel, workbook


def _release_com(value):
    if value is None:
        return
    try:
        Marshal.FinalReleaseComObject(value)
    except Exception:
        try:
            Marshal.ReleaseComObject(value)
        except Exception:
            pass


def _excel_close(excel, workbook):
    try:
        if workbook is not None:
            try:
                workbook.Close(False)
            finally:
                _release_com(workbook)
    finally:
        if excel is not None:
            try:
                excel.Quit()
            except Exception:
                pass
            _release_com(excel)
        try:
            GC.Collect()
            GC.WaitForPendingFinalizers()
            GC.Collect()
            GC.WaitForPendingFinalizers()
        except Exception:
            pass


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


def _used_bounds(ws):
    """``(first_row, first_col, last_row, last_col, truncated)`` for the sheet.

    ``truncated`` says the caps clipped the used range, so the caller can
    report it instead of silently deciding on a partial read.
    """
    used = rows = columns = None
    try:
        used = ws.UsedRange
        first_row = max(1, int(used.Row))
        first_col = max(1, int(used.Column))
        rows = used.Rows
        columns = used.Columns
        total_rows = int(rows.Count)
        total_cols = int(columns.Count)
    finally:
        _release_com(columns)
        _release_com(rows)
        _release_com(used)
    row_count = max(1, min(MAX_SHEET_ROWS, total_rows))
    col_count = max(1, min(MAX_SHEET_COLS, total_cols))
    return (first_row, first_col,
            first_row + row_count - 1, first_col + col_count - 1,
            row_count < total_rows or col_count < total_cols)


def _range_cells(ws, first_row, first_col, last_row, last_col):
    """Read one rectangle as ``[(row, col, value), ...]``, blanks dropped."""
    if last_row < first_row or last_col < first_col:
        return []
    row_count = last_row - first_row + 1
    col_count = last_col - first_col + 1
    cells = start_cell = end_cell = data_range = None
    try:
        cells = ws.Cells
        start_cell = cells.Item(first_row, first_col)
        end_cell = cells.Item(last_row, last_col)
        data_range = ws.Range(start_cell, end_cell)
        values = data_range.Value2
    finally:
        _release_com(data_range)
        _release_com(end_cell)
        _release_com(start_cell)
        _release_com(cells)
    result = []
    for row_offset in range(1, row_count + 1):
        for col_offset in range(1, col_count + 1):
            value = _matrix_value(
                values, row_offset, col_offset, row_count, col_count)
            if _text(value):
                result.append((
                    first_row + row_offset - 1,
                    first_col + col_offset - 1,
                    value,
                ))
    return result


def _worksheet_cells(ws):
    """``(cells, truncated)`` for the sheet's used range."""
    first_row, first_col, last_row, last_col, truncated = _used_bounds(ws)
    return (_range_cells(ws, first_row, first_col, last_row, last_col),
            truncated)


_REFERENCE_IN_FORMULA = re.compile(
    r"(?:'(?P<quoted>(?:[^']|'')+)'|(?P<plain>[^!+*/^&(),\-=]+))"
    r"!\$?(?P<col>[A-Z]{1,3})\$?\d+", re.IGNORECASE)


def _opening_indexes(sheets):
    """Every sheet that indexes openings as 編號/空間名稱 + a single 寬 column.

    Discovered, never hardcoded: this workbook happens to qualify on both 內牆
    and 踢腳, so the caller has to pick one.
    """
    indexes = []
    for name, cells, _truncated, _labels in sheets:
        try:
            header_row, number_col, name_col = logic.find_room_header(cells)
            width_col = logic.find_opening_width_column(
                cells, header_row, name_col)
        except ValueError:
            continue
        openings = logic.index_openings(
            cells, header_row, number_col, name_col, width_col)
        if not openings:
            continue
        indexes.append({
            'sheet': name,
            'width_col': width_col,
            'width_letter': logic.column_letters(width_col),
            'openings': openings,
            'row_count': len(openings),
            'total_m': sum(item[3] for item in openings),
        })
    return indexes


def _suggest_index(workbook, target_sheet, target_row, length_col, indexes):
    """Prefer the index the neighbouring item rows already reference.

    The workbook states its own convention: the sibling 不銹鋼門檻 row holds
    ``=SUM(內牆!M16:M484)-F19``, so 內牆!M is the established basis for this
    item and is a better default than "first qualifying sheet".
    """
    if not indexes:
        return None
    by_key = dict(((item['sheet'], item['width_letter']), item['sheet'])
                  for item in indexes)
    ws = None
    try:
        ws = _worksheet(workbook, target_sheet)
        for offset in (1, -1, 2, -2, 3, -3, 4, -4, 5, -5):
            row = int(target_row) + offset
            if row < 1:
                continue
            cells = cell = None
            try:
                cells = ws.Cells
                cell = cells.Item(row, length_col)
                formula = _formula(cell)
            except Exception:
                formula = u''
            finally:
                _release_com(cell)
                _release_com(cells)
            for match in _REFERENCE_IN_FORMULA.finditer(formula):
                name = _text(match.group('quoted') or match.group('plain'))
                name = name.strip().replace(u"''", u"'")
                key = (name, match.group('col').upper())
                if key in by_key:
                    return by_key[key]
    except Exception:
        pass
    finally:
        _release_com(ws)
    return None


def _threshold_sheets(workbook):
    """Read every worksheet and keep the ones carrying the threshold label.

    Returns ``(sheets, blockers, notes)`` where ``sheets`` holds
    ``(sheet_name, label_cells, cells)``.

    Excel's native ``Range.Find`` looks like the obvious accelerator here and
    was used for exactly that, but it is not usable: in a real cost workbook
    the item label on the calculation sheet is a formula mirror of the subtotal
    sheet (``其他長度!C19`` is ``=小計!C93``), and Find returns no hit for such
    a cell under xlValues *or* xlFormulas — measured on 物流中心工項-0720.xls it
    saw 2 of the 5 門檻 cells and missed every formula-derived one, including
    the only writable target. Neither ``Application.Calculate`` nor activating
    the sheet changes that. ``Value2`` returns the cached result correctly, so
    the used range is read in one call per sheet (2.8 s / 74k cells / 19 sheets
    on that workbook) and matched in Python. Do not reintroduce Find.
    """
    result = []
    blockers = []
    notes = []
    worksheets = workbook.Worksheets
    try:
        count = int(worksheets.Count)
        for index in range(1, count + 1):
            ws = worksheets.Item(index)
            try:
                name = _text(ws.Name)
                cells, truncated = _worksheet_cells(ws)
                if truncated:
                    notes.append(
                        u'工作表「{}」超過 {} 列 / {} 欄的讀取上限，僅讀取前段。'
                        .format(name, MAX_SHEET_ROWS, MAX_SHEET_COLS))
                labels = [item for item in cells
                          if logic.is_threshold_label(item[2])]
                if labels and truncated:
                    # Uniqueness of the item row cannot be proven from a
                    # partial read of a sheet that does carry the label.
                    blockers.append(
                        u'工作表「{}」讀取被截斷且含本工項，無法確認唯一工項。'
                        .format(name))
                # Every sheet is kept, not just labelled ones: the opening
                # index lives on a sheet that never mentions 門檻.
                result.append((name, cells, truncated, labels))
            finally:
                _release_com(ws)
    finally:
        _release_com(worksheets)
    return result, blockers, notes


def _worksheet(workbook, name):
    worksheets = workbook.Worksheets
    try:
        count = int(worksheets.Count)
        for index in range(1, count + 1):
            ws = worksheets.Item(index)
            if _text(ws.Name) == _text(name):
                return ws
            _release_com(ws)
    finally:
        _release_com(worksheets)
    raise Exception(u'Excel 找不到工作表「{}」。'.format(name))


def _has_formula(cell):
    try:
        return bool(cell.HasFormula)
    except Exception:
        return _text(cell.Formula).startswith(u'=')


def _formula(cell):
    return _text(cell.Formula) if _has_formula(cell) else u''


def _number(value):
    try:
        return float(value)
    except Exception:
        return None


def _formula_budget(path):
    """.xls holds far shorter formulas than .xlsx; see logic module comment."""
    if os.path.splitext(path)[1].lower() == '.xls':
        return logic.XLS_FORMULA_BUDGET
    return logic.XLSX_FORMULA_BUDGET


def _check_path(path):
    if not path or not os.path.isfile(path):
        raise Exception(u'Excel 路徑不存在。')
    if os.path.splitext(path)[1].lower() not in ('.xls', '.xlsx'):
        raise Exception(u'請選擇 .xls 或 .xlsx 檔案。')


def inspect_target(path):
    """Open the workbook read-only and locate the writable length cell."""
    _check_path(path)
    excel = workbook = None
    try:
        excel, workbook = _excel_open(path, True)
        return inspect_open_workbook(workbook)
    finally:
        _excel_close(excel, workbook)


def inspect_open_workbook(workbook):
    """Locate the single writable "不銹鋼門檻機房" length cell.

    Takes an already-open workbook so the update path can re-verify inside the
    session it is going to write in, instead of launching Excel again. Excel is
    only used to find where to write; the room list and threshold length come
    from Revit, so no source sheet or quantity*length chain formula is read.
    """
    sheets, scan_blockers, scan_notes = _threshold_sheets(workbook)
    target_cells = []
    sheet_cells = {}
    for sheet_name, cells, _truncated, labels in sheets:
        sheet_cells[sheet_name] = cells
        for row, col, value in labels:
            target_cells.append((sheet_name, row, col, value))
    try:
        (target_sheet, target_row, label_col,
         header_row, quantity_col, length_col) = (
            logic.find_unique_input_target(sheet_cells, target_cells))
    except ValueError as error:
        detail = _text(error)
        hints = scan_blockers + scan_notes
        if hints:
            detail = u'{}\n{}'.format(detail, u'\n'.join(hints))
        raise Exception(detail)
    ws = _worksheet(workbook, target_sheet)
    cells = length_cell = None
    try:
        cells = ws.Cells
        length_cell = cells.Item(target_row, length_col)
        try:
            old_value = length_cell.Value2
            old_formula = _formula(length_cell)
        finally:
            _release_com(length_cell)
    finally:
        _release_com(cells)
        _release_com(ws)
    # A truncated label search cannot prove the item row is unique, so it
    # blocks the write instead of only being reported.
    blockers = list(scan_blockers)
    if old_formula and not logic.is_safe_length_formula(old_formula):
        blockers.append(
            u'{}!{}{} 原公式含儲存格引用或非白名單邏輯，禁止覆寫：{}'.format(
                target_sheet, logic.column_letters(length_col), target_row,
                old_formula))
    indexes = _opening_indexes(sheets)
    return {
        'target_sheet': target_sheet,
        'target_row': target_row,
        'length_col': length_col,
        'target_address': u'{}!{}{}'.format(
            target_sheet, logic.column_letters(length_col), target_row),
        'old_value': old_value,
        'old_formula': old_formula,
        'blockers': blockers,
        'notes': list(scan_notes),
        'indexes': indexes,
        'suggested_index': _suggest_index(
            workbook, target_sheet, target_row, length_col, indexes),
    }


def _room_data(room):
    if room is None:
        return {'number': u'', 'name': u''}
    number = u''
    name = u''
    # Read via the built-in parameters first — Room.Name (Element.Name) returns
    # empty on this Revit/IronPython build even when the room is named, whereas
    # ROOM_NAME/ROOM_NUMBER are reliable (matches how the MCP reads rooms).
    try:
        parameter = room.get_Parameter(DB.BuiltInParameter.ROOM_NAME)
        if parameter is not None:
            name = _text(parameter.AsString())
    except Exception:
        pass
    if not name:
        try:
            name = _text(room.Name)
        except Exception:
            pass
    try:
        parameter = room.get_Parameter(DB.BuiltInParameter.ROOM_NUMBER)
        if parameter is not None:
            number = _text(parameter.AsString())
    except Exception:
        pass
    if not number:
        try:
            number = _text(room.Number)
        except Exception:
            pass
    return {'number': number, 'name': name}


class Choice(object):
    """One pickable item: a stable key plus the label the user reads."""

    def __init__(self, key, label):
        self.key = key
        self.label = label


def _element_name(element):
    """Same accessor order as the 門窗表 button: the static property first.

    ``element.Name`` is surfaced as an indexer on some IronPython builds, so
    ``DB.Element.Name.GetValue`` is the reliable read and the instance property
    is only the fallback.
    """
    try:
        return _text(DB.Element.Name.GetValue(element))
    except Exception:
        pass
    try:
        return _text(element.Name)
    except Exception:
        return u''


def _link_documents(doc, link_ids):
    """``[(link_id, label, link_doc), ...]``; unloaded links carry ``None``."""
    result = []
    for link_id in link_ids or []:
        link = None
        try:
            link = doc.GetElement(DB.ElementId(int(link_id)))
        except Exception:
            link = None
        if link is None:
            continue
        try:
            link_doc = link.GetLinkDocument()
        except Exception:
            link_doc = None
        result.append((int(link_id), _element_name(link), link_doc))
    return result


def _uniquify(choices):
    """Make labels unique; the picker maps the user's answer back by label.

    Two instances of the same linked file share a name, and identical labels
    would make one tick select both — the same class of silent identity
    collision this whole feature exists to remove.
    """
    seen = {}
    for choice in choices:
        seen[choice.label] = seen.get(choice.label, 0) + 1
    used = {}
    for choice in choices:
        if seen[choice.label] > 1:
            used[choice.label] = used.get(choice.label, 0) + 1
            choice.label = u'{} #{}'.format(choice.label, used[choice.label])
    return choices


def list_links(doc):
    """Every Revit link instance, loaded or not; unloaded ones are marked."""
    choices = []
    for link in (DB.FilteredElementCollector(doc)
                 .OfClass(DB.RevitLinkInstance)):
        link_id = _id_value(link.Id)
        try:
            loaded = link.GetLinkDocument() is not None
        except Exception:
            loaded = False
        choices.append(Choice(
            link_id, u'{}{}'.format(_element_name(link),
                                    u'' if loaded else u'（未載入）')))
    choices.sort(key=lambda item: item.label)
    return _uniquify(choices)


def _doc_levels(source_doc):
    levels = []
    for level in (DB.FilteredElementCollector(source_doc)
                  .OfClass(DB.Level)
                  .WhereElementIsNotElementType()):
        try:
            elevation = float(level.Elevation)
        except Exception:
            elevation = 0.0
        levels.append((_id_value(level.Id), _element_name(level), elevation))
    levels.sort(key=lambda item: item[2])
    return levels


def list_levels(doc, selected_link_ids):
    """Levels of the host plus every selected link, tagged by source model."""
    choices = []
    for level_id, name, _elevation in _doc_levels(doc):
        choices.append(Choice(logic.level_key(logic.HOST_SOURCE, level_id),
                              u'主模型｜{}'.format(name)))
    for link_id, label, link_doc in _link_documents(doc, selected_link_ids):
        if link_doc is None:
            continue
        source_key = logic.link_source_key(link_id)
        for level_id, name, _elevation in _doc_levels(link_doc):
            choices.append(Choice(logic.level_key(source_key, level_id),
                                  u'{}｜{}'.format(label, name)))
    return _uniquify(choices)


def _room_level_id(room):
    """The room's level, through whichever accessor this build exposes."""
    try:
        value = _id_value(room.LevelId)
        if value is not None and value >= 0:
            return value
    except Exception:
        pass
    try:
        level = room.Level
        if level is not None:
            value = _id_value(level.Id)
            if value is not None and value >= 0:
                return value
    except Exception:
        pass
    try:
        parameter = room.get_Parameter(DB.BuiltInParameter.ROOM_LEVEL_ID)
        if parameter is not None:
            value = _id_value(parameter.AsElementId())
            if value is not None and value >= 0:
                return value
    except Exception:
        pass
    return None


def _rooms_in_doc(source_doc, source_key, source_label, link_id,
                  level_filter, level_names):
    """Classify the placed rooms of one document, optionally by level.

    ``level_filter`` is a set of composite level keys or ``None`` for "every
    level of this model" — the per-source default, so choosing B1F of one link
    never silently drops the host.
    """
    rooms = []
    collector = (
        DB.FilteredElementCollector(source_doc)
        .OfCategory(DB.BuiltInCategory.OST_Rooms)
        .WhereElementIsNotElementType()
    )
    for room in collector:
        try:
            if float(room.Area) <= 0:
                continue
        except Exception:
            pass
        level_id = _room_level_id(room)
        if level_filter is not None:
            if level_id is None:
                continue
            if logic.level_key(source_key, level_id) not in level_filter:
                continue
        data = _room_data(room)
        if not data['name'] and not data['number']:
            continue
        element_id = _id_value(room.Id)
        rooms.append({
            'key': logic.room_uid(source_key, element_id),
            'element_id': element_id,
            'source_key': source_key,
            'source_label': source_label,
            'link_id': link_id,
            'level_id': level_id,
            'level_name': _level_name(source_doc, level_id, level_names),
            'number': data['number'],
            'name': data['name'],
            'classification': logic.classify_room(data['name']),
        })
    return rooms


def _level_name(source_doc, level_id, cache):
    if level_id is None:
        return u'(未知樓層)'
    cache_key = (id(source_doc), level_id)
    if cache_key not in cache:
        name = u'(未知樓層)'
        try:
            level = source_doc.GetElement(DB.ElementId(int(level_id)))
            if level is not None:
                name = _element_name(level) or name
        except Exception:
            pass
        cache[cache_key] = name
    return cache[cache_key]


def collect_rooms(doc, selected_link_ids=None, selected_level_keys=None):
    """``(rooms, scopes)`` for the host plus every selected link.

    The host is always collected: this workbook item is a project total, and a
    link is added to it rather than replacing it. ``scopes`` reports what each
    model actually contributed so the window can say so out loud — a room that
    was never listed cannot be noticed as missing on the checkbox list.
    """
    rooms = []
    scopes = []
    level_names = {}
    host_filter = logic.level_filter_for_source(
        logic.HOST_SOURCE, selected_level_keys)
    host_rooms = _rooms_in_doc(doc, logic.HOST_SOURCE, u'主模型', None,
                               host_filter, level_names)
    rooms.extend(host_rooms)
    scopes.append({
        'source_key': logic.HOST_SOURCE,
        'label': u'主模型',
        'levels': _scope_levels(doc, logic.HOST_SOURCE, host_filter,
                                level_names),
        'room_count': len(host_rooms),
        'loaded': True,
    })
    for link_id, label, link_doc in _link_documents(doc, selected_link_ids):
        source_key = logic.link_source_key(link_id)
        level_filter = logic.level_filter_for_source(
            source_key, selected_level_keys)
        if link_doc is None:
            scopes.append({
                'source_key': source_key,
                'label': label, 'levels': u'（未載入，已略過）',
                'room_count': 0, 'loaded': False,
            })
            continue
        link_rooms = _rooms_in_doc(link_doc, source_key, label, link_id,
                                   level_filter, level_names)
        rooms.extend(link_rooms)
        scopes.append({
            'source_key': source_key,
            'label': label,
            'levels': _scope_levels(link_doc, source_key, level_filter,
                                    level_names),
            'room_count': len(link_rooms),
            'loaded': True,
        })
    rooms.sort(key=lambda item: (
        0 if item['source_key'] == logic.HOST_SOURCE else 1,
        item['source_label'],
        room_order_logic.room_number_sort_key(item['number']),
        item['name']))
    return rooms, scopes


def collect_rooms_for_options(doc, options):
    """Collect rooms from the exact source/level scope chosen in preflight."""
    rooms = []
    scopes = []
    level_names = {}
    for (source_key, source_label, source_doc, allowed_level_ids,
         link_instance_id) in takeoff_entry.iter_sources(doc, options):
        model_label = u'主模型' if link_instance_id is None else source_label
        level_filter = None
        if allowed_level_ids is not None:
            level_filter = set(
                logic.level_key(source_key, value)
                for value in allowed_level_ids)
        source_rooms = _rooms_in_doc(
            source_doc, source_key, model_label, link_instance_id,
            level_filter, level_names)
        rooms.extend(source_rooms)
        scopes.append({
            'source_key': source_key,
            'link_id': link_instance_id,
            'label': model_label,
            'levels': _scope_levels(
                source_doc, source_key, level_filter, level_names),
            'room_count': len(source_rooms),
            'loaded': True,
        })
    rooms.sort(key=lambda item: (
        0 if item['source_key'] == logic.HOST_SOURCE else 1,
        item['source_label'],
        room_order_logic.room_number_sort_key(item['number']),
        item['name']))
    return rooms, scopes


def _scope_levels(source_doc, source_key, level_filter, level_names):
    if level_filter is None:
        return u'全部樓層'
    prefix = u'{}:'.format(source_key)
    names = []
    for key in sorted(level_filter):
        try:
            level_id = int(u'{}'.format(key)[len(prefix):])
        except ValueError:
            continue
        names.append(_level_name(source_doc, level_id, level_names))
    return u'、'.join(names) or u'全部樓層'


def describe_scopes(scopes):
    return u'　'.join(
        u'{}：{}（{} 間）'.format(item['label'], item['levels'],
                                 item['room_count'])
        for item in scopes or [])


def _document_phases(doc):
    phases = []
    try:
        for phase in doc.Phases:
            phases.append(phase)
    except Exception:
        pass
    return phases


def _door_phases(doc, door, phases):
    """The door's own creation phase first, then the rest as fallback.

    In a phased model the same opening can face different rooms per phase, so
    asking phases in document order and taking the first hit can report a room
    the door never actually touches in its own phase. ``PHASE_CREATED`` is the
    door's own answer, and it is only backed up by the other phases when it is
    missing or resolves to nothing.
    """
    created = None
    try:
        parameter = door.get_Parameter(DB.BuiltInParameter.PHASE_CREATED)
        if parameter is not None and parameter.HasValue:
            phase = doc.GetElement(parameter.AsElementId())
            if phase is not None:
                created = phase
    except Exception:
        created = None
    if created is None:
        return phases
    created_id = _id_value(created.Id)
    return [created] + [phase for phase in phases
                        if _id_value(phase.Id) != created_id]


def _door_room(door, side, phases):
    """Resolve a door's room via the phase-parameterized accessor.

    The parameterless ``door.FromRoom``/``ToRoom`` is surfaced by IronPython as
    an indexer object (not a Room), so it must not be used; ``get_FromRoom`` /
    ``get_ToRoom`` take a Phase and return the actual Room. ``phases`` is
    ordered by ``_door_phases`` so the door's own phase is answered first.
    """
    try:
        getter = getattr(door, 'get_{}'.format(side))
    except Exception:
        return None
    for phase in phases:
        try:
            room = getter(phase)
            if room is not None:
                return room
        except Exception:
            pass
    return None


def _width_parameter(door):
    sources = [door]
    try:
        if door.Symbol is not None:
            sources.append(door.Symbol)
    except Exception:
        pass
    for source in sources:
        try:
            parameter = source.get_Parameter(DB.BuiltInParameter.DOOR_WIDTH)
            if (parameter is not None and parameter.HasValue and
                    parameter.StorageType == DB.StorageType.Double and
                    parameter.AsDouble() > 0):
                return parameter
        except Exception:
            pass
        for name in (u'寬', u'Width'):
            try:
                parameter = source.LookupParameter(name)
                if (parameter is not None and parameter.HasValue and
                        parameter.StorageType == DB.StorageType.Double and
                        parameter.AsDouble() > 0):
                    return parameter
            except Exception:
                pass
    return None


def _width_m(door):
    parameter = _width_parameter(door)
    if parameter is None:
        return None
    feet = float(parameter.AsDouble())
    try:
        return float(DB.UnitUtils.ConvertFromInternalUnits(
            feet, DB.UnitTypeId.Meters))
    except Exception:
        try:
            return float(DB.UnitUtils.ConvertFromInternalUnits(
                feet, DB.DisplayUnitType.DUT_METERS))
        except Exception:
            return feet * 0.3048


def _doors_in_doc(source_doc, selected, source_key, source_label):
    """Doors of one document whose FromRoom or ToRoom is a selected room.

    Rooms and doors are only ever compared inside the same document: a linked
    door does not open onto a host room, and the ElementIds on both sides would
    happily collide across documents if they were compared anyway.
    """
    all_phases = _document_phases(source_doc)
    records = []
    collector = (
        DB.FilteredElementCollector(source_doc)
        .OfCategory(DB.BuiltInCategory.OST_Doors)
        .WhereElementIsNotElementType()
    )
    for door in collector:
        phases = _door_phases(source_doc, door, all_phases)
        from_room = _door_room(door, 'FromRoom', phases)
        to_room = _door_room(door, 'ToRoom', phases)
        from_id = _id_value(from_room.Id) if from_room is not None else None
        to_id = _id_value(to_room.Id) if to_room is not None else None
        if not ((from_id in selected) or (to_id in selected)):
            # Unrelated doors are dropped here rather than carried as
            # placeholder records: they can never contribute a width and must
            # never block the machine-room threshold update.
            continue
        # Room names and the width query only matter for included doors, so
        # this work is skipped for the (usually many) unrelated doors.
        from_data = _room_data(from_room)
        to_data = _room_data(to_room)
        element_id = _id_value(door.Id)
        records.append({
            'key': logic.room_uid(source_key, element_id),
            'element_id': element_id,
            'source_key': source_key,
            'source_label': source_label,
            'from_number': from_data['number'],
            'from_name': from_data['name'],
            'to_number': to_data['number'],
            'to_name': to_data['name'],
            'included': True,
            'width_m': _width_m(door),
        })
    return records


def collect_doors(doc, selected_rooms):
    """Sum widths of the doors touching the selected rooms, per document."""
    by_source = {}
    for room in selected_rooms or []:
        source_key = room.get('source_key') or logic.HOST_SOURCE
        entry = by_source.setdefault(source_key, {
            'label': room.get('source_label') or u'主模型',
            'link_id': room.get('link_id'),
            'ids': set(),
        })
        entry['ids'].add(int(room['element_id']))
    records = []
    missing = []
    for source_key in sorted(by_source):
        entry = by_source[source_key]
        if entry['link_id'] is None:
            source_doc = doc
        else:
            documents = _link_documents(doc, [entry['link_id']])
            source_doc = documents[0][2] if documents else None
        if source_doc is None:
            # The link went away between loading the room list and previewing.
            # Silently contributing 0 m here is exactly the invisible shortfall
            # this feature exists to prevent, so it blocks the write instead.
            missing.append(
                u'連結模型「{}」已卸載或移除，{} 間已勾選房間無法取得門寬。'.format(
                    entry['label'], len(entry['ids'])))
            continue
        records.extend(_doors_in_doc(source_doc, entry['ids'], source_key,
                                     entry['label']))
    summary = logic.summarize_doors(records)
    summary['warnings'] = list(summary.get('warnings') or []) + missing
    summary['blockers'] = list(summary.get('blockers') or []) + missing
    return summary


def _backup_path(path):
    stem, extension = os.path.splitext(path)
    return u'{}_backup_{}{}'.format(
        stem, datetime.now().strftime('%Y%m%d-%H%M%S'), extension)


def _read_cell_value(workbook, sheet_name, row, col):
    ws = _worksheet(workbook, sheet_name)
    cells = cell = None
    try:
        cells = ws.Cells
        cell = cells.Item(row, col)
        return cell.Value2
    finally:
        _release_com(cell)
        _release_com(cells)
        _release_com(ws)


def _restore_backup(path, backup):
    """Put the pre-write copy back; the backup itself is always kept."""
    try:
        if not os.path.isfile(backup):
            return False
        shutil.copy2(backup, path)
        return True
    except Exception:
        return False


def _inspection_identity(inspection):
    keys = (
        'target_sheet', 'target_row', 'length_col', 'old_value', 'old_formula',
    )
    return tuple(inspection.get(key) for key in keys)


def update_workbook(path, inspection, door_summary, backup, plan):
    """Re-verify, write and read back inside ONE Excel session.

    Every phase used to open its own Excel instance (re-inspect, write, verify
    = 3 more launches after the preview). Inside a long-lived host like Revit
    that is both slow and fragile: creating a new ``Excel.Application`` while
    the previous one is still shutting down surfaces as a bare
    ``COMException 0x800A03EC`` with no usable IronPython traceback. One
    session removes that failure mode, and ``step`` names the phase so any
    remaining COM error says where it happened.
    """
    blockers = list(inspection.get('blockers') or [])
    blockers.extend(door_summary.get('blockers') or [])
    if blockers:
        raise Exception(u'仍有阻擋項，未寫入：\n{}'.format(u'\n'.join(blockers)))
    _check_path(path)
    # What gets written is exactly what the preview showed, not a recomputation
    # that could drift from it.
    formula = plan.get('formula')
    if not formula:
        raise Exception(plan.get('error') or u'沒有可寫入的公式。')
    total = float(plan['total_m'])
    if not os.access(path, os.W_OK):
        raise Exception(u'Excel 檔案是唯讀，禁止更新。')
    shutil.copy2(path, backup)
    excel = workbook = None
    step = u'開啟 Excel'
    written = False
    try:
        excel, workbook = _excel_open(path, False)
        if bool(workbook.ReadOnly):
            raise Exception(u'Excel 檔目前被鎖定，未寫入。')
        # Re-locate inside this session: the file may have changed between the
        # preview and now, and re-opening Excel just to check is what used to
        # break here.
        step = u'重新定位工項'
        current = inspect_open_workbook(workbook)
        if _inspection_identity(current) != _inspection_identity(inspection):
            raise Exception(u'Excel 自預覽後已改變，未寫入。')
        step = u'寫入公式'
        ws = _worksheet(workbook, inspection['target_sheet'])
        cells = cell = None
        try:
            row = inspection['target_row']
            col = inspection['length_col']
            cells = ws.Cells
            cell = cells.Item(row, col)
            try:
                if _formula(cell) != inspection['old_formula']:
                    raise Exception(u'目標長度公式自預覽後已改變，未寫入。')
                cell.Formula = formula
            finally:
                _release_com(cell)
        finally:
            _release_com(cells)
            _release_com(ws)
        step = u'重算'
        try:
            excel.Calculation = XL_CALCULATION_AUTOMATIC
        except Exception:
            pass
        excel.Calculate()
        step = u'存檔'
        workbook.Save()
        written = True
        # Read the saved result back from the same open workbook.
        step = u'回讀驗證'
        actual = _number(_read_cell_value(
            workbook, inspection['target_sheet'], inspection['target_row'],
            inspection['length_col']))
    except Exception as error:
        # Close first so the file handle is gone, then undo. The pre-write copy
        # is byte-identical when the failure happened before Save.
        _excel_close(excel, workbook)
        restored = _restore_backup(path, backup)
        raise Exception(u'「{}」階段失敗：{}\n{}'.format(
            step, error,
            u'已自動由備份還原。' if restored else
            u'自動還原失敗，備份在：{}'.format(backup)))
    else:
        _excel_close(excel, workbook)
    if actual is None or abs(actual - total) > 0.000001:
        # The write is unverified, so the file is put back to its pre-write
        # state automatically instead of leaving the user to restore by hand.
        restored = _restore_backup(path, backup)
        raise Exception(
            u'Excel {}但長度驗證失敗（預期 {}，實際 {}）；{}'.format(
                u'已存檔' if written else u'未存檔', total, actual,
                u'已自動由備份還原。' if restored else
                u'自動還原失敗，請手動由備份還原：{}'.format(backup)))


DIRECT_WIDTHS = u'（不使用索引：直接寫 Revit 門寬）'


def _find_index(inspection, sheet_name):
    for item in inspection.get('indexes') or []:
        if item['sheet'] == sheet_name:
            return item
    return None


def build_write_plan(path, inspection, index_sheet, selected_rooms, summary):
    """Decide what will be written, and how it reconciles with the model.

    When an opening index is chosen the formula points at that sheet's width
    column, so the number keeps a visible basis inside the workbook. The Revit
    door total then acts as a cross-check rather than as the value itself: a
    mismatch is reported, not silently written over.
    """
    budget = _formula_budget(path)
    revit_total = float(summary['total_m'])
    plan = {
        'index_sheet': index_sheet,
        'revit_total_m': revit_total,
        'index_total_m': None,
        'rows': [],
        'warnings': [],
        'error': None,
        'formula': None,
        'total_m': revit_total,
    }
    index = _find_index(inspection, index_sheet) if index_sheet else None
    if index is None:
        widths = [door['width_m'] for door in summary['doors']]
        try:
            plan['formula'] = logic.build_length_formula(widths, budget)
        except ValueError as error:
            plan['error'] = _text(error)
        return plan

    rows, index_total, matched = logic.select_opening_rows(
        index['openings'], selected_rooms)
    plan['rows'] = rows
    plan['index_total_m'] = index_total
    plan['total_m'] = index_total
    if not rows:
        plan['error'] = u'「{}」索引中找不到任何勾選房間的開口列。'.format(
            index['sheet'])
        return plan
    missing = logic.unmatched_rooms(selected_rooms, matched)
    if missing:
        plan['warnings'].append(
            u'{} 間勾選房間在「{}」索引中沒有開口列：{}'.format(
                len(missing), index['sheet'],
                u'、'.join(logic.room_source_display(room)
                           for room in missing[:12])))
    if abs(index_total - revit_total) > 0.0005:
        plan['warnings'].append(
            u'索引合計 {:.4f} m 與 Revit 門寬合計 {:.4f} m 相差 {:+.4f} m；'
            u'公式仍依索引寫入，請確認兩邊是否需要對齊。'.format(
                index_total, revit_total, index_total - revit_total))
    try:
        plan['formula'] = logic.build_reference_formula(
            index['sheet'], index['width_letter'], rows, budget)
    except ValueError as error:
        plan['error'] = _text(error)
    return plan


def _status_label(value):
    return {
        logic.INCLUDE: u'納入',
        logic.REVIEW: u'待確認',
        logic.EXCLUDE: u'排除',
    }.get(value, u'排除')


def _preview_text(path, inspection, rooms, selected_keys, summary, plan=None,
                  scopes=None):
    selected = set(selected_keys)
    counts = logic.classification_counts(rooms)
    lines = [
        u'Excel：{}'.format(path),
        u'目標儲存格：{}（不銹鋼門檻機房 長度）'.format(
            inspection['target_address']),
        u'舊值/公式：{} / {}'.format(
            inspection['old_value'], inspection['old_formula'] or u'(數值/空白)'),
        u'',
        # The read scope is stated before the counts: a total is only
        # meaningful once it says which models and levels it came from.
        u'讀取範圍：{}'.format(describe_scopes(scopes) or u'主模型：全部樓層'),
        u'Revit 房間：共 {} 間（納入 {}／待確認 {}／排除 {}），本次勾選 {} 間'.format(
            len(rooms), counts[logic.INCLUDE], counts[logic.REVIEW],
            counts[logic.EXCLUDE], len(selected)),
    ]
    # Only the rooms that actually drive this number are listed; dumping every
    # room in the model buried the door table in a large project.
    for room in rooms:
        if room['key'] not in selected:
            continue
        lines.append(u'  [{}] {}'.format(
            _status_label(room['classification']),
            logic.room_source_display(room)))
    if not selected:
        lines.append(u'  （未勾選任何房間）')
    lines.extend([u'', u'納入機房的門（依 Revit 門寬）：'])
    for door in summary['doors']:
        lines.append(u'{} | {:.4f} m'.format(
            logic.describe_door(door), float(door['width_m'])))
    lines.append(u'門數：{}　總長：{:.4f} m'.format(
        len(summary['doors']), float(summary['total_m'])))
    if plan is not None:
        lines.extend([u'', u'寫入依據：{}'.format(
            u'「{}」開口寬度欄 {} 列'.format(
                plan['index_sheet'], len(plan['rows']))
            if plan['index_sheet'] else DIRECT_WIDTHS)])
        if plan['index_total_m'] is not None:
            lines.append(u'索引合計：{:.4f} m　Revit 合計：{:.4f} m　差異：{:+.4f} m'
                         .format(plan['index_total_m'], plan['revit_total_m'],
                                 plan['index_total_m'] - plan['revit_total_m']))
        lines.append(u'將寫入：{}'.format(
            plan['formula'] or u'(無法產生) {}'.format(plan['error'])))
    warnings = list(inspection.get('blockers') or [])
    warnings.extend(inspection.get('notes') or [])
    warnings.extend(summary.get('warnings') or [])
    if plan is not None:
        warnings.extend(plan.get('warnings') or [])
    if warnings:
        lines.extend([u'', u'Warnings / Blockers：'])
        lines.extend(u'- {}'.format(item) for item in warnings)
    else:
        lines.extend([u'', u'Warnings / Blockers：無'])
    return u'\n'.join(lines)


class MachineRoomThresholdWindow(forms.WPFWindow):
    def __init__(self, doc, entry_options):
        xaml = os.path.join(
            os.path.dirname(__file__), '..', 'MCP_Macros.tab',
            'Takeoff.panel', 'MachineRoomThresholdExcel.pushbutton',
            'MachineRoomThresholdExcel.xaml')
        forms.WPFWindow.__init__(self, os.path.abspath(xaml))
        self.doc = doc
        self.entry_options = dict(entry_options or {})
        self.standalone_mode = (
            takeoff_standalone.entry_mode(self.entry_options)
            == takeoff_standalone.MODE_STANDALONE)
        self.inspection = None
        self.rooms = []
        self.scopes = []
        self.room_checks = []
        self.result = None
        self._suspend_invalidate = False
        self.links = list_links(doc)
        self.selected_link_ids = list(
            self.entry_options.get('selected_link_ids') or [])
        self.selected_level_keys = list(
            self.entry_options.get('selected_level_keys') or [])
        self.levels = list_levels(doc, self.selected_link_ids)
        self.browseButton.Click += self.browse_clicked
        self.loadButton.Click += self.load_clicked
        self.previewButton.Click += self.preview_clicked
        self.updateButton.Click += self.update_clicked
        self.cancelButton.Click += self.cancel_clicked
        self.pathBox.TextChanged += self.invalidate_preview
        self.filterBox.TextChanged += self.filter_changed
        self.indexBox.SelectionChanged += self.invalidate_preview
        self.selectAllButton.Click += self.select_all_clicked
        self.clearAllButton.Click += self.clear_all_clicked
        self.selectDefaultButton.Click += self.select_default_clicked
        self.selectLinksButton.Click += self.select_links_clicked
        self.selectLevelsButton.Click += self.select_levels_clicked
        self.pathBox.Text = (
            self.entry_options.get('workbook_path')
            or u'（未選主要 Excel，將另存新的 .xlsx）')
        self.pathBox.IsReadOnly = True
        self.browseButton.IsEnabled = False
        self.loadButton.IsEnabled = False
        self.selectLinksButton.IsEnabled = False
        self.selectLevelsButton.IsEnabled = False
        if self.standalone_mode:
            self.targetText.Text = u'Standalone 公式摘要'
            self.indexBox.IsEnabled = False
            self.updateButton.Content = u'匯出 Excel'
        # Rooms come from Revit and are independent of the Excel selection.
        self._load_rooms()
        if not self.standalone_mode:
            self._load_workbook()

    def _load_rooms(self):
        try:
            self.rooms, self.scopes = collect_rooms_for_options(
                self.doc, self.entry_options)
            self._render_rooms(self.rooms)
            self._sync_summaries()
            self.statusText.Text = (
                u'已載入 {} 個房間（預設勾選 {} 間）；請產生預覽。'.format(
                    len(self.rooms), len(self._selected_rooms())))
        except Exception as error:
            forms.alert(u'讀取 Revit 房間失敗：\n\n{}'.format(error), title=TITLE)

    def _sync_summaries(self):
        if self.selected_link_ids:
            chosen = set(self.selected_link_ids)
            names = [item.label for item in self.links if item.key in chosen]
            self.linkSummaryText.Text = u'已選 {} 個：{}'.format(
                len(names), u'、'.join(names))
        else:
            self.linkSummaryText.Text = (
                u'未選取（只讀主模型房間）' if self.links
                else u'此專案沒有連結模型')
        if self.selected_level_keys:
            chosen = set(self.selected_level_keys)
            names = [item.label for item in self.levels if item.key in chosen]
            self.levelSummaryText.Text = u'已選 {} 個：{}'.format(
                len(names), u'、'.join(names))
        else:
            self.levelSummaryText.Text = u'未篩選（每個模型都抓全部樓層）'
        self.scopeText.Text = describe_scopes(self.scopes)

    def _render_rooms(self, rooms):
        # Re-collecting after a link or level change must not silently discard
        # what the user already curated, so previously seen rooms keep their
        # state and only genuinely new rooms fall back to the rule default.
        previous = dict((room['key'], bool(checkbox.IsChecked))
                        for checkbox, room in self.room_checks)
        self.roomPanel.Children.Clear()
        self.room_checks = []
        # Building the list pre-checks machine rooms, which would otherwise
        # fire one invalidate per room before the window is even usable.
        self._suspend_invalidate = True
        for room in rooms:
            checkbox = CheckBox()
            checkbox.Margin = Thickness(2)
            checkbox.Content = u'[{}] {}'.format(
                _status_label(room['classification']),
                logic.room_source_display(room))
            # Pre-select machine rooms: high-confidence INCLUDE and the
            # generic "機房" REVIEW class; user can add or remove any.
            checkbox.IsChecked = previous.get(
                room['key'],
                room['classification'] in (logic.INCLUDE, logic.REVIEW))
            checkbox.Checked += self.invalidate_preview
            checkbox.Unchecked += self.invalidate_preview
            self.roomPanel.Children.Add(checkbox)
            self.room_checks.append((checkbox, room))
        self._suspend_invalidate = False
        self._apply_filter()

    def _apply_filter(self):
        """Hide non-matching rooms; visibility never changes what is checked.

        Filtering must not silently drop a checked room from the total, so the
        checkbox stays in the list and only its visibility moves.
        """
        query = _text(self.filterBox.Text)
        visible = 0
        for checkbox, room in self.room_checks:
            match = logic.room_matches_query(room, query)
            checkbox.Visibility = Visibility.Visible if match \
                else Visibility.Collapsed
            if match:
                visible += 1
        self._update_room_count(visible)

    def _update_room_count(self, visible=None):
        if visible is None:
            visible = sum(1 for checkbox, _ in self.room_checks
                          if checkbox.Visibility == Visibility.Visible)
        self.roomCountText.Text = u'顯示 {} / {} 間，已勾選 {} 間'.format(
            visible, len(self.room_checks), len(self._selected_rooms()))

    def _visible_checks(self):
        return [(checkbox, room) for checkbox, room in self.room_checks
                if checkbox.Visibility == Visibility.Visible]

    def _set_checked(self, pairs, value_of):
        # One invalidate for the whole batch instead of one per checkbox.
        self._suspend_invalidate = True
        try:
            for checkbox, room in pairs:
                checkbox.IsChecked = value_of(room)
        finally:
            self._suspend_invalidate = False
        self.invalidate_preview()

    def filter_changed(self, sender=None, args=None):
        self._apply_filter()

    def select_all_clicked(self, sender, args):
        self._set_checked(self._visible_checks(), lambda room: True)

    def clear_all_clicked(self, sender, args):
        self._set_checked(self._visible_checks(), lambda room: False)

    def select_default_clicked(self, sender, args):
        """Reset to the rule-based machine-room selection across all rooms."""
        self._set_checked(
            self.room_checks,
            lambda room: room['classification'] in (logic.INCLUDE, logic.REVIEW))

    def _selected_rooms(self):
        return [room for checkbox, room in self.room_checks
                if bool(checkbox.IsChecked)]

    # --- link / level pickers -------------------------------------------
    def _pick(self, choices, selected_keys, title, button):
        chosen = set(selected_keys)
        options = [forms.TemplateListItem(choice.label,
                                          checked=choice.key in chosen)
                   for choice in choices]
        picked = forms.SelectFromList.show(
            options, title=title, button_name=button,
            multiselect=True, width=760, height=620)
        if picked is None:
            return None
        labels = set(u'{}'.format(getattr(item, 'item', item))
                     for item in picked)
        return [choice.key for choice in choices if choice.label in labels]

    def select_links_clicked(self, sender, args):
        if not self.links:
            forms.alert(u'此專案沒有 Revit 連結模型。', title=TITLE)
            return
        picked = self._pick(self.links, self.selected_link_ids,
                            u'選擇要一併讀取房間的連結模型（不勾選＝只讀主模型）',
                            u'使用選取的連結模型')
        if picked is None:
            return
        self.selected_link_ids = picked
        self._refresh_levels()
        self._load_rooms()
        self.invalidate_preview()

    def _refresh_levels(self):
        """Rebuild the level list; a dropped link must drop its levels too.

        Level keys carry their source model, so a key left behind by a link
        that is no longer selected would filter nothing and quietly stay in the
        summary as if it still applied.
        """
        self.levels = list_levels(self.doc, self.selected_link_ids)
        available = set(choice.key for choice in self.levels)
        self.selected_level_keys = [key for key in self.selected_level_keys
                                    if key in available]

    def select_levels_clicked(self, sender, args):
        self._refresh_levels()
        if not self.levels:
            forms.alert(u'找不到任何樓層。', title=TITLE)
            return
        picked = self._pick(
            self.levels, self.selected_level_keys,
            u'選擇要讀取的樓層（同一個模型不勾選＝該模型全部樓層）',
            u'使用選取的樓層')
        if picked is None:
            return
        self.selected_level_keys = picked
        self._load_rooms()
        self.invalidate_preview()

    def invalidate_preview(self, sender=None, args=None):
        if self._suspend_invalidate:
            return
        self.result = None
        self.updateButton.IsEnabled = False
        self.statusText.Text = u'輸入已變更，請重新產生預覽。'
        self._update_room_count()

    def browse_clicked(self, sender, args):
        return

    def load_clicked(self, sender, args):
        return

    def _load_workbook(self):
        try:
            self.inspection = inspect_target(_text(self.pathBox.Text))
            self.targetText.Text = u'{}（不銹鋼門檻機房）'.format(
                self.inspection['target_address'])
            self._render_indexes()
            self.invalidate_preview()
        except Exception as error:
            self.inspection = None
            self.targetText.Text = u'—'
            self.indexBox.Items.Clear()
            forms.alert(u'讀取 Excel 失敗：\n\n{}'.format(error), title=TITLE)

    def _render_indexes(self):
        """List the discovered opening indexes; default to the suggested one.

        The sheet and column are never hardcoded, so a workbook that keeps its
        opening widths somewhere else still works — the user picks.
        """
        self._suspend_invalidate = True
        try:
            self.indexBox.Items.Clear()
            self.index_choices = [None]
            self.indexBox.Items.Add(DIRECT_WIDTHS)
            suggested = self.inspection.get('suggested_index')
            selected = 0
            for item in self.inspection.get('indexes') or []:
                label = u'{}！{} 欄（{} 列開口，合計 {:.2f} m）{}'.format(
                    item['sheet'], item['width_letter'], item['row_count'],
                    item['total_m'],
                    u'　← 本表既有慣例' if item['sheet'] == suggested else u'')
                self.indexBox.Items.Add(label)
                self.index_choices.append(item['sheet'])
                if item['sheet'] == suggested:
                    selected = len(self.index_choices) - 1
            self.indexBox.SelectedIndex = selected
        finally:
            self._suspend_invalidate = False

    def _selected_index_sheet(self):
        position = int(self.indexBox.SelectedIndex)
        choices = getattr(self, 'index_choices', [None])
        if 0 <= position < len(choices):
            return choices[position]
        return None

    def preview_clicked(self, sender, args):
        if self.standalone_mode:
            try:
                selected_rooms = self._selected_rooms()
                summary = collect_doors(self.doc, selected_rooms)
                tables = logic.standalone_tables(
                    selected_rooms, summary, self.scopes)
                self.previewBox.Text = u'\n'.join([
                    u'輸出模式：建立新的 standalone .xlsx',
                    u'讀取範圍：{}'.format(describe_scopes(self.scopes)),
                    u'勾選機房：{} 間'.format(len(selected_rooms)),
                    u'納入門：{} 樘'.format(len(summary['doors'])),
                    u'門檻總長：{:.4f} m'.format(summary['total_m']),
                    u'分頁：數量明細／公式摘要／稽核',
                ] + [
                    u'阻擋：{}'.format(item)
                    for item in summary.get('blockers') or []
                ])
                self.result = {
                    'mode': takeoff_standalone.MODE_STANDALONE,
                    'summary': summary,
                    'tables': tables,
                    'selected_rooms': selected_rooms,
                }
                blocked = bool(summary.get('blockers'))
                self.updateButton.IsEnabled = True
                self.statusText.Text = (
                    u'有門缺有效寬度；可匯出並於稽核分頁查看 BLOCK。'
                    if blocked else
                    u'預覽通過，可另存新的 Excel。')
            except Exception as error:
                self.result = None
                self.updateButton.IsEnabled = False
                forms.alert(u'產生預覽失敗：\n\n{}'.format(error), title=TITLE)
            return
        if self.inspection is None:
            self._load_workbook()
            if self.inspection is None:
                return
        try:
            # Reuse the inspection captured at load time; the Excel file is not
            # re-read here (update_workbook re-reads and re-checks before write).
            inspection = self.inspection
            path = _text(self.pathBox.Text)
            selected_rooms = self._selected_rooms()
            summary = collect_doors(self.doc, selected_rooms)
            plan = build_write_plan(
                path, inspection, self._selected_index_sheet(),
                selected_rooms, summary)
            self.previewBox.Text = _preview_text(
                path, inspection, self.rooms,
                [room['key'] for room in selected_rooms], summary, plan,
                self.scopes)
            self.result = {
                'mode': takeoff_standalone.MODE_UPDATE,
                'path': path,
                'inspection': inspection,
                'summary': summary,
                'plan': plan,
            }
            blocked = (logic.write_is_blocked(inspection['blockers'], summary)
                       or not plan['formula'])
            self.updateButton.IsEnabled = not blocked
            self.statusText.Text = (
                u'有阻擋項，禁止更新。' if blocked else
                u'預覽與驗證通過，可更新。')
        except Exception as error:
            self.result = None
            self.updateButton.IsEnabled = False
            forms.alert(u'產生預覽失敗：\n\n{}'.format(error), title=TITLE)

    def update_clicked(self, sender, args):
        if self.result is not None and self.updateButton.IsEnabled:
            self.Close()

    def cancel_clicked(self, sender, args):
        self.result = None
        self.Close()


def _default_name(doc):
    title = u'{}'.format(getattr(doc, 'Title', u'機房門檻')).strip()
    for value in u'\\/:*?"<>|':
        title = title.replace(value, u'_')
    return (title or u'機房門檻') + u'_機房門檻.xlsx'


def run(doc, entry_options):
    window = MachineRoomThresholdWindow(doc, entry_options)
    window.ShowDialog()
    result = window.result
    if result is None:
        return
    if result.get('mode') == takeoff_standalone.MODE_STANDALONE:
        path = forms.save_file(
            file_ext='xlsx',
            default_name=_default_name(doc),
            title=u'匯出機房門檻 Excel')
        if not path:
            return
        if not path.lower().endswith('.xlsx'):
            path += '.xlsx'
        tables = result['tables']
        try:
            takeoff_standalone.write_standard_workbook(
                path,
                tables['detail_rows'], tables['detail_headers'],
                tables['formula_rows'], tables['formula_headers'],
                tables['audit_rows'], tables['audit_headers'],
                TITLE)
            forms.alert(
                u'匯出完成。\n機房門 {} 樘，門檻總長 {:.4f} m\nExcel：{}'
                .format(
                    len(result['summary']['doors']),
                    result['summary']['total_m'], path),
                title=TITLE)
        except Exception as error:
            forms.alert(u'匯出失敗：\n\n{}'.format(error), title=TITLE)
        return
    backup = _backup_path(result['path'])
    plan = result['plan']
    confirmed = forms.alert(
        u'將只更新 {}。\n依據：{}\n門數 {}，寫入值 {:.4f} m。\n公式：{}\n備份：{}'
        u'\n\n確定更新嗎？'.format(
            result['inspection']['target_address'],
            u'「{}」開口寬度欄 {} 列'.format(
                plan['index_sheet'], len(plan['rows']))
            if plan['index_sheet'] else DIRECT_WIDTHS,
            len(result['summary']['doors']), float(plan['total_m']),
            plan['formula'], backup),
        title=TITLE, yes=True, no=True)
    if not confirmed:
        return
    try:
        update_workbook(
            result['path'], result['inspection'], result['summary'], backup,
            plan)
        forms.alert(
            u'更新完成。\nExcel：{}\n備份：{}'.format(result['path'], backup),
            title=TITLE)
    except Exception as error:
        forms.alert(u'更新失敗：\n\n{}'.format(error), title=TITLE)
