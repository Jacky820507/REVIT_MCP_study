# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""門窗表 Excel — count doors/windows (host + links) into 小計 金屬門窗工程.

Excel is only used to find the item rows and write the 數量 column; the type
identity comes from Revit. Follows the same write contract as the other
workbook updaters: one Excel session, backup first, read back after saving,
and restore automatically if anything goes wrong.
"""

import os
import shutil
from datetime import datetime

from pyrevit import DB, forms
from System import Activator, GC, Type
from System.Runtime.InteropServices import Marshal

import door_window_excel_logic as logic
import takeoff_entry

try:
    reload(logic)
except Exception:
    pass


TITLE = u'門窗表 Excel'
SUBTOTAL_SHEET = u'小計'
QUANTITY_COL = 6          # F 欄：數量
LABEL_COL = 3             # C 欄：工項名稱
UNIT_COL = 5              # E 欄：單位
MAX_SHEET_ROWS = 3000
MAX_SHEET_COLS = 80
XL_CALCULATION_AUTOMATIC = -4105

SOURCE_MODE_AUTO = 'auto'
SOURCE_MODE_SCHEDULES = 'schedules'

CATEGORIES = (
    (DB.BuiltInCategory.OST_Doors, u'門'),
    (DB.BuiltInCategory.OST_Windows, u'窗'),
)


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value).strip()
    except Exception:
        return str(value).strip()


def _id_value(element_id):
    for name in ('Value', 'IntegerValue'):
        try:
            return int(getattr(element_id, name))
        except Exception:
            pass
    try:
        return int(element_id)
    except Exception:
        return None


def _element_name(element):
    try:
        return _text(DB.Element.Name.GetValue(element))
    except Exception:
        pass
    try:
        return _text(element.Name)
    except Exception:
        return u''


def _type_name(instance, source_doc):
    """Type name is the identity used for matching, not TypeMark.

    TypeMark is unreliable in this model — SD10 carries TypeMark 140 and the
    opening family carries 110 — while the type name keeps the
    ``<編號>-<寬>x<高> cm`` shape the cost sheet is written in.
    """
    try:
        symbol = instance.Symbol
        if symbol is not None:
            return _element_name(symbol)
    except Exception:
        pass
    try:
        type_id = instance.GetTypeId()
        symbol = source_doc.GetElement(type_id)
        if symbol is not None:
            return _element_name(symbol)
    except Exception:
        pass
    return u''


# --- Revit collection ------------------------------------------------------

class Choice(object):
    def __init__(self, element_id, label):
        self.element_id = element_id
        self.label = label


def list_links(doc):
    choices = []
    for link in (DB.FilteredElementCollector(doc)
                 .OfClass(DB.RevitLinkInstance)):
        try:
            link_doc = link.GetLinkDocument()
        except Exception:
            link_doc = None
        name = _element_name(link) or _text(link.Name)
        status = u'' if link_doc is not None else u'（未載入）'
        choices.append(Choice(_id_value(link.Id),
                              u'{}{}'.format(name, status)))
    choices.sort(key=lambda item: item.label)
    return choices


def list_schedules(doc):
    choices = []
    for schedule in (DB.FilteredElementCollector(doc)
                     .OfClass(DB.ViewSchedule)):
        try:
            if schedule.IsTemplate:
                continue
            definition = schedule.Definition
            if definition is not None and definition.IsKeySchedule:
                continue
        except Exception:
            pass
        name = _element_name(schedule)
        if not name:
            continue
        choices.append(Choice(_id_value(schedule.Id), name))
    choices.sort(key=lambda item: item.label)
    return choices


HOST_SOURCE = logic.HOST_SOURCE


def _level_id(element):
    """Level of a door/window, with the fallbacks Revit actually needs.

    A door hosted in a wall often leaves ``LevelId`` invalid, so the built-in
    level parameters are tried next; the same chain the parking button uses.
    """
    try:
        value = _id_value(element.LevelId)
        if value is not None and value >= 0:
            return value
    except Exception:
        pass
    for name in ('FAMILY_LEVEL_PARAM', 'INSTANCE_REFERENCE_LEVEL_PARAM',
                 'SCHEDULE_LEVEL_PARAM'):
        try:
            parameter = element.get_Parameter(
                getattr(DB.BuiltInParameter, name))
            value = _id_value(parameter.AsElementId()) if parameter else None
            if value is not None and value >= 0:
                return value
        except Exception:
            pass
    try:
        host = element.Host
        if host is not None:
            value = _id_value(host.LevelId)
            if value is not None and value >= 0:
                return value
    except Exception:
        pass
    return None


level_key = logic.level_key


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
        choices.append(Choice(level_key(HOST_SOURCE, level_id),
                              u'主模型｜{}'.format(name)))
    for link_id in selected_link_ids or []:
        link = doc.GetElement(DB.ElementId(int(link_id)))
        if link is None:
            continue
        try:
            link_doc = link.GetLinkDocument()
        except Exception:
            link_doc = None
        if link_doc is None:
            continue
        label = _element_name(link)
        source_key = logic.link_source_key(link_id)
        for level_id, name, _elevation in _doc_levels(link_doc):
            choices.append(Choice(level_key(source_key, level_id),
                                  u'{}｜{}'.format(label, name)))
    return choices


def _level_label(source_doc, level_id, cache):
    """Level name for the audit ledger; cached per document."""
    if level_id is None:
        return u'(未知樓層)'
    cache_key = (id(source_doc), level_id)
    if cache_key in cache:
        return cache[cache_key]
    name = u'(未知樓層)'
    try:
        level = source_doc.GetElement(DB.ElementId(int(level_id)))
        if level is not None:
            name = _element_name(level) or name
    except Exception:
        pass
    cache[cache_key] = name
    return name


def _run_scope(model_label, source_key, level_filter, doc, link_doc=None):
    """``(model, level)`` scopes this run replaces in the ledger.

    Without a level filter the run owns the whole model, which must clear any
    earlier per-level rows for it.
    """
    if level_filter is None:
        return {(model_label, logic.ALL_LEVELS)}
    prefix = u'{}:'.format(source_key)
    scopes = set()
    cache = {}
    target = link_doc if link_doc is not None else doc
    for key in level_filter:
        if not u'{}'.format(key).startswith(prefix):
            continue
        try:
            level_id = int(u'{}'.format(key)[len(prefix):])
        except ValueError:
            continue
        scopes.add((model_label, _level_label(target, level_id, cache)))
    return scopes


def _instances_in_doc(source_doc, origin, source_key=HOST_SOURCE,
                      allowed_levels=None):
    """Yield doors/windows, optionally restricted to selected levels.

    ``allowed_levels`` is a set of composite keys; ``None`` means every level,
    which is the default so an unfiltered run still counts the whole model.
    """
    for category, kind in CATEGORIES:
        try:
            collector = (DB.FilteredElementCollector(source_doc)
                         .OfCategory(category)
                         .WhereElementIsNotElementType())
        except Exception:
            continue
        for instance in collector:
            if allowed_levels is not None:
                level_id = _level_id(instance)
                if level_id is None:
                    continue
                if level_key(source_key, level_id) not in allowed_levels:
                    continue
            yield instance, source_doc, origin, kind


def _schedule_instances(doc, schedule_ids):
    """Elements actually listed by the selected schedules, deduplicated."""
    seen = set()
    for schedule_id in schedule_ids or []:
        schedule = doc.GetElement(DB.ElementId(int(schedule_id)))
        if schedule is None:
            continue
        name = _element_name(schedule)
        try:
            collector = (DB.FilteredElementCollector(doc, schedule.Id)
                         .WhereElementIsNotElementType())
        except Exception:
            continue
        for element in collector:
            key = _id_value(element.Id)
            if key in seen:
                continue
            seen.add(key)
            yield element, doc, u'明細表：{}'.format(name), u''


def collect_counts(doc, source_mode, selected_schedule_ids,
                   selected_link_ids, selected_levels=None):
    """``(counts, total, sources)`` keyed by type key.

    Host and links are counted the same way; a linked instance is still one
    樘. Each key keeps the type names behind it so the preview can show what
    a key actually matched.

    ``selected_levels`` is a set of composite level keys. Empty or ``None``
    means no level filtering at all — the documented default is "抓全部".
    """
    counts = {}
    total = 0
    sources = []
    allowed = set(selected_levels or ())
    level_filter = allowed if allowed else None
    level_names = {}
    run_scopes = set()

    # Per (model, level) tallies feed the audit ledger so a filtered run can
    # be merged with earlier runs instead of replacing the project total.
    per_scope = {}

    def add(instance, source_doc, origin, kind):
        name = _type_name(instance, source_doc)
        key = logic.type_key(name)
        if not key:
            return 0
        entry = counts.setdefault(key, {'count': 0, 'names': set(),
                                        'origins': set()})
        entry['count'] += 1
        entry['names'].add(name)
        entry['origins'].add(origin)
        level_label = _level_label(source_doc, _level_id(instance),
                                   level_names)
        scope = (origin, level_label)
        bucket = per_scope.setdefault(scope, {})
        row = bucket.setdefault(key, {'count': 0, 'name': name})
        row['count'] += 1
        return 1

    def host_allows(source_key):
        return logic.source_has_selection(source_key, level_filter)

    if source_mode == SOURCE_MODE_SCHEDULES and not host_allows(HOST_SOURCE):
        # Same wording as the auto branch: a bare "0 樘" reads like the model
        # genuinely has no doors, when in fact no host level was selected.
        sources.append(u'主模型明細表：未選取主模型樓層，略過')
    elif source_mode == SOURCE_MODE_SCHEDULES:
        found = 0
        for item in _schedule_instances(doc, selected_schedule_ids):
            instance = item[0]
            if level_filter is not None:
                level_id = _level_id(instance)
                if (level_id is None or level_key(HOST_SOURCE, level_id)
                        not in level_filter):
                    continue
            found += add(*item)
        total += found
        run_scopes |= _run_scope(u'主模型', HOST_SOURCE, level_filter, doc)
        sources.append(u'主模型明細表：{} 樘'.format(found))
    elif not host_allows(HOST_SOURCE):
        # Levels were chosen but none of them belong to the host model, so the
        # host is deliberately out of scope rather than silently contributing.
        sources.append(u'主模型：未選取樓層，略過')
    else:
        found = 0
        for item in _instances_in_doc(doc, u'主模型', HOST_SOURCE,
                                      level_filter):
            found += add(*item)
        total += found
        run_scopes |= _run_scope(u'主模型', HOST_SOURCE, level_filter, doc)
        sources.append(u'主模型：{} 樘'.format(found))

    for link_id in selected_link_ids or []:
        link = doc.GetElement(DB.ElementId(int(link_id)))
        if link is None:
            continue
        try:
            link_doc = link.GetLinkDocument()
        except Exception:
            link_doc = None
        label = _element_name(link)
        if link_doc is None:
            sources.append(u'{}：未載入，已略過'.format(label))
            continue
        source_key = logic.link_source_key(link_id)
        if not host_allows(source_key):
            sources.append(u'{}：未選取樓層，略過'.format(label))
            continue
        found = 0
        for item in _instances_in_doc(link_doc, label, source_key,
                                      level_filter):
            found += add(*item)
        total += found
        run_scopes |= _run_scope(label, source_key, level_filter, doc,
                                 link_doc)
        sources.append(u'{}：{} 樘'.format(label, found))

    for entry in counts.values():
        entry['names'] = sorted(entry['names'])
        entry['origins'] = sorted(entry['origins'])

    stamp = datetime.now().strftime('%Y-%m-%d %H:%M')
    audit_rows = []
    for (model_label, level_label), bucket in per_scope.items():
        for key, row in bucket.items():
            audit_rows.append({
                'model': model_label, 'level': level_label, 'key': key,
                'name': row['name'], 'count': row['count'], 'updated': stamp})
    return {
        'counts': counts,
        'total': total,
        'sources': sources,
        'audit_rows': audit_rows,
        'run_scopes': run_scopes,
    }


def collect_counts_for_options(doc, options, source_mode=SOURCE_MODE_AUTO,
                               selected_schedule_ids=None):
    """Collect with the shared entry UI's per-source level contract.

    ``takeoff_entry.iter_sources`` is the single authority for selected link
    instances and level ids.  A source with no selected level receives
    ``allowed_level_ids=None`` and therefore contributes all of its levels.
    """
    counts = {}
    total = 0
    sources = []
    per_scope = {}
    run_scopes = set()
    level_names = {}

    def add(instance, source_doc, source_key, source_label, kind):
        name = _type_name(instance, source_doc)
        key = logic.type_key(name)
        if not key:
            return 0
        entry = counts.setdefault(key, {
            'count': 0, 'names': set(), 'origins': set()})
        entry['count'] += 1
        entry['names'].add(name)
        entry['origins'].add(source_label)
        level_label = _level_label(
            source_doc, _level_id(instance), level_names)
        scope = (source_key, source_label, level_label)
        bucket = per_scope.setdefault(scope, {})
        row = bucket.setdefault(key, {'count': 0, 'name': name})
        row['count'] += 1
        return 1

    source_records = list(takeoff_entry.iter_sources(doc, options))
    host_in_scope = any(record[4] is None for record in source_records)
    if (source_mode == SOURCE_MODE_SCHEDULES and host_in_scope
            and not selected_schedule_ids):
        raise Exception(u'明細表模式需要先選取至少一張明細表。')

    for (source_key, source_label, source_doc, allowed_level_ids,
         link_instance_id) in source_records:
        model_label = u'主模型' if link_instance_id is None else source_label
        composite_levels = None
        if allowed_level_ids is not None:
            composite_levels = set(
                level_key(source_key, value)
                for value in allowed_level_ids)
        found = 0
        if (link_instance_id is None
                and source_mode == SOURCE_MODE_SCHEDULES):
            for item in _schedule_instances(
                    doc, selected_schedule_ids or []):
                instance = item[0]
                if composite_levels is not None:
                    instance_level = _level_id(instance)
                    if (instance_level is None
                            or level_key(source_key, instance_level)
                            not in composite_levels):
                        continue
                found += add(
                    instance, source_doc, source_key, model_label, item[3])
            sources.append(u'主模型明細表：{} 樘'.format(found))
        else:
            for item in _instances_in_doc(
                    source_doc, model_label, source_key, composite_levels):
                found += add(
                    item[0], source_doc, source_key, model_label, item[3])
            sources.append(u'{}：{} 樘'.format(model_label, found))
        total += found
        run_scopes |= _run_scope(
            model_label, source_key, composite_levels, doc,
            source_doc if link_instance_id is not None else None)

    for entry in counts.values():
        entry['names'] = sorted(entry['names'])
        entry['origins'] = sorted(entry['origins'])

    stamp = datetime.now().strftime('%Y-%m-%d %H:%M')
    audit_rows = []
    for (source_key, model_label, level_label), bucket in per_scope.items():
        for key, row in bucket.items():
            audit_rows.append({
                'source_key': source_key,
                'model': model_label,
                'level': level_label,
                'key': key,
                'name': row['name'],
                'count': row['count'],
                'updated': stamp,
            })
    return {
        'counts': counts,
        'total': total,
        'sources': sources,
        'audit_rows': audit_rows,
        'run_scopes': run_scopes,
    }


# --- Excel ----------------------------------------------------------------

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


def _worksheet(workbook, name):
    worksheets = workbook.Worksheets
    try:
        count = int(worksheets.Count)
        for index in range(1, count + 1):
            sheet = worksheets.Item(index)
            if _text(sheet.Name) == _text(name):
                return sheet
            _release_com(sheet)
    finally:
        _release_com(worksheets)
    raise Exception(u'Excel 找不到工作表「{}」。'.format(name))


def _sheet_cells(sheet):
    used = rows = columns = cells = start = end = data = None
    try:
        used = sheet.UsedRange
        first_row = max(1, int(used.Row))
        first_col = max(1, int(used.Column))
        rows = used.Rows
        columns = used.Columns
        row_count = max(1, min(MAX_SHEET_ROWS, int(rows.Count)))
        col_count = max(1, min(MAX_SHEET_COLS, int(columns.Count)))
        cells = sheet.Cells
        start = cells.Item(first_row, first_col)
        end = cells.Item(first_row + row_count - 1, first_col + col_count - 1)
        data = sheet.Range(start, end)
        values = data.Value2
    finally:
        for item in (data, end, start, cells, columns, rows, used):
            _release_com(item)
    result = []
    for row_offset in range(1, row_count + 1):
        for col_offset in range(1, col_count + 1):
            value = _matrix_value(values, row_offset, col_offset,
                                  row_count, col_count)
            if _text(value):
                result.append((first_row + row_offset - 1,
                               first_col + col_offset - 1, value))
    return result


def _cell_formula(sheet, row, col):
    cells = cell = None
    try:
        cells = sheet.Cells
        cell = cells.Item(row, col)
        try:
            if bool(cell.HasFormula):
                return _text(cell.Formula)
        except Exception:
            pass
        return u''
    finally:
        _release_com(cell)
        _release_com(cells)


def _find_sheet(workbook, name):
    try:
        return _worksheet(workbook, name)
    except Exception:
        return None


def read_audit_rows(workbook):
    """Previous runs' ledger; empty when the audit sheet does not exist yet."""
    sheet = _find_sheet(workbook, logic.AUDIT_SHEET)
    if sheet is None:
        return []
    try:
        return logic.parse_audit_rows(_sheet_cells(sheet))
    finally:
        _release_com(sheet)


def _write_audit_sheet(workbook, rows):
    """Rewrite the ledger sheet from scratch; it is ours, not the user's."""
    sheet = _find_sheet(workbook, logic.AUDIT_SHEET)
    created = False
    if sheet is None:
        worksheets = workbook.Worksheets
        try:
            sheet = worksheets.Add()
            sheet.Name = logic.AUDIT_SHEET
            created = True
        finally:
            _release_com(worksheets)
    values = logic.audit_values(rows)
    cells = None
    try:
        try:
            sheet.Cells.Clear()
        except Exception:
            pass
        cells = sheet.Cells
        for row_index, row in enumerate(values, start=1):
            for col_index, value in enumerate(row, start=1):
                if value is None or value == u'':
                    continue
                cell = cells.Item(row_index, col_index)
                try:
                    cell.Value2 = value
                finally:
                    _release_com(cell)
    finally:
        _release_com(cells)
        _release_com(sheet)
    return created


def inspect_workbook(workbook):
    """Item rows of 金屬門窗工程 plus any row that must not be written."""
    sheet = _worksheet(workbook, SUBTOTAL_SHEET)
    try:
        cells = _sheet_cells(sheet)
        try:
            first_row, last_row = logic.find_section_rows(
                cells, label_col=LABEL_COL, unit_col=UNIT_COL)
        except ValueError as error:
            raise Exception(_text(error))
        items = logic.parse_items(cells, first_row, last_row,
                                  label_col=LABEL_COL,
                                  quantity_col=QUANTITY_COL,
                                  unit_col=UNIT_COL)
        protected = []
        for item in items:
            formula = _cell_formula(sheet, item['row'], QUANTITY_COL)
            if not logic.is_safe_quantity_cell(formula):
                protected.append({
                    'row': item['row'], 'name': item['name'],
                    'reason': u'數量欄是公式，禁止覆寫：{}'.format(formula)})
        return {
            'first_row': first_row,
            'last_row': last_row,
            'items': items,
            'protected': protected,
        }
    finally:
        _release_com(sheet)


def _backup_path(path):
    stem, extension = os.path.splitext(path)
    return u'{}_backup_{}{}'.format(
        stem, datetime.now().strftime('%Y%m%d-%H%M%S'), extension)


def _restore_backup(path, backup):
    try:
        if not os.path.isfile(backup):
            return False
        shutil.copy2(backup, path)
        return True
    except Exception:
        return False


def update_workbook(path, plan, backup):
    """Write only the 小計 quantity cells, in one Excel session."""
    updates = plan['updates']
    if not updates:
        raise Exception(u'沒有需要更新的列。')
    if not os.access(path, os.W_OK):
        raise Exception(u'Excel 檔案是唯讀，禁止更新。')
    shutil.copy2(path, backup)

    excel = workbook = None
    step = u'開啟 Excel'
    try:
        excel, workbook = _excel_open(path, False)
        if bool(workbook.ReadOnly):
            raise Exception(u'Excel 檔目前被鎖定，未寫入。')
        step = u'重新定位工項'
        current = inspect_workbook(workbook)
        try:
            updates = logic.relocate_safe_updates(
                updates, current['items'], current['protected'])
        except ValueError as error:
            raise Exception(_text(error))
        step = u'寫入數量'
        sheet = _worksheet(workbook, SUBTOTAL_SHEET)
        cells = None
        try:
            cells = sheet.Cells
            for update in updates:
                cell = cells.Item(update['row'], QUANTITY_COL)
                try:
                    cell.Value2 = float(update['new'])
                finally:
                    _release_com(cell)
        finally:
            _release_com(cells)
            _release_com(sheet)
        step = u'重算'
        try:
            excel.Calculation = XL_CALCULATION_AUTOMATIC
        except Exception:
            pass
        excel.Calculate()
        step = u'存檔'
        workbook.Save()
        step = u'回讀驗證'
        verified = inspect_workbook(workbook)
        actual = dict((item['row'], item['quantity'])
                      for item in verified['items'])
    except Exception as error:
        _excel_close(excel, workbook)
        restored = _restore_backup(path, backup)
        raise Exception(u'「{}」階段失敗：{}\n{}'.format(
            step, error,
            u'已自動由備份還原。' if restored else
            u'自動還原失敗，備份在：{}'.format(backup)))
    else:
        _excel_close(excel, workbook)

    mismatches = []
    for update in updates:
        value = actual.get(update['row'])
        if value is None or abs(float(value) - float(update['new'])) > 0.0001:
            mismatches.append(u'r{} 預期 {} 實際 {}'.format(
                update['row'], update['new'], value))
    if mismatches:
        restored = _restore_backup(path, backup)
        raise Exception(u'已存檔但回讀驗證失敗：{}；{}'.format(
            u'、'.join(mismatches[:6]),
            u'已自動由備份還原。' if restored else u'自動還原失敗。'))
