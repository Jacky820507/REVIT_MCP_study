# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""明細表參數表.

複選明細表 → 把明細表裡的元素（列）× 明細表欄位（欄）攤成可編輯表格，
跟「房間參數表」共用同一個表格視窗（``param_grid_window``）：Ctrl+C/V、
Ctrl+D、Delete、匯出/匯入 Excel → 關閉表格後 dry-run 預覽 → 單一
Transaction 寫入，任一格失敗整批回復並帶著修改重開表格。

只收「實例」與「類型」參數欄；計算值、百分比、組合參數、Count、房間/
材料等關聯欄位不是元素自己的參數，不列入。類型欄寫到元素的類型上，同一
類型在不同列被改成不同值時擋下來（``schedule_fields_logic.group_writes``）。
"""

__title__ = u'明細表\n參數表'
__author__ = 'RevitMCP'

import os

from Autodesk.Revit import DB
from pyrevit import forms, revit, script

import mcp_window as ui
import mcp_window_logic as spec_logic
import param_grid_window as grid
import room_param_grid_logic as table_logic
import schedule_fields_logic as logic


TITLE = u'明細表參數表'
XAML = os.path.join(os.path.dirname(__file__), 'ScheduleParameterTable.xaml')
LABELS = {'unit': u'個元素', 'unit_short': u'個',
          'export_name': u'明細表參數', 'title': TITLE}

KEY_ID = grid.KEY_ID
KEY_SCHEDULE = 'k_schedule'
KEY_ELEMENT = 'k_element'


# ── Revit 讀取 ──────────────────────────────────────────────────────

def _is_fixed(field):
    for attr in ('IsCalculatedField', 'IsCombinedParameterField'):
        try:
            if getattr(field, attr):
                return True
        except Exception:
            pass
    return False


def _schedules(doc):
    result = []
    for view in DB.FilteredElementCollector(doc).OfClass(DB.ViewSchedule):
        try:
            if view.IsTemplate or view.IsTitleblockRevisionSchedule:
                continue
            view.Definition
        except Exception:
            continue
        result.append(view)
    result.sort(key=lambda v: v.Name.lower())
    return result


def _param_columns(view):
    """明細表上可對應到元素參數的欄位：``[(key, header, is_type, param_id)]``。"""
    columns = []
    definition = view.Definition
    for field_id in definition.GetFieldOrder():
        field = definition.GetField(field_id)
        if _is_fixed(field):
            continue
        if field.FieldType == DB.ScheduleFieldType.Instance:
            is_type = False
        elif field.FieldType == DB.ScheduleFieldType.ElementType:
            is_type = True
        else:
            continue
        param_id = grid.id_value(field.ParameterId)
        if param_id == -1:
            continue
        header = field.ColumnHeading or field.GetName()
        columns.append((logic.field_key(int(field.FieldType), param_id),
                        header, is_type, param_id))
    return columns


class ParamCache(object):
    """每個元素的 ``{ParameterId 整數: Parameter}``，內建參數是負數 id。"""

    def __init__(self):
        self.by_element = {}

    def get(self, element, param_id):
        if element is None:
            return None
        element_key = grid.id_value(element.Id)
        params = self.by_element.get(element_key)
        if params is None:
            params = {}
            for param in element.Parameters:
                try:
                    params.setdefault(grid.id_value(param.Id), param)
                except Exception:
                    pass
            self.by_element[element_key] = params
        return params.get(param_id)


def _target(doc, element, is_type):
    if not is_type:
        return element
    try:
        return doc.GetElement(element.GetTypeId())
    except Exception:
        return None


def _element_label(element):
    category = u''
    try:
        category = element.Category.Name
    except Exception:
        pass
    try:
        name = element.Name
    except Exception:
        name = u''
    return u'：'.join(part for part in (category, name) if part) or u'-'


# ── 流程 ────────────────────────────────────────────────────────────

def _ask(views):
    active = None
    try:
        active = grid.id_value(revit.active_view.Id)
    except Exception:
        pass
    options = [(v.Name, grid.id_value(v.Id)) for v in views]
    spec = spec_logic.spec(
        TITLE,
        [spec_logic.multichoice(
            'schedules', u'明細表', options,
            default=[active] if active in [o[1] for o in options] else [],
            required=True, filter=True,
            help=u'可輸入名稱關鍵字篩選；Shift+點擊可連選。'
                 u'目前開啟的明細表已預先勾選。選多張時欄位取聯集。'),
         spec_logic.note(
             u'下一步開啟表格：列＝明細表裡的元素，欄＝明細表欄位。可直接編輯、'
             u'複製貼上、向下填滿、匯出匯入 Excel；寫入模型前會先預覽。')],
        badge=spec_logic.BADGE_WRITE, run_label=u'開啟表格',
        width=680, height=720)
    values = ui.ask(spec)
    return (values or {}).get('schedules') or []


def _collect(doc, views, cache):
    """回傳 ``(columns, infos, records)``。"""
    infos = []          # 依出現順序的欄位：{'key','header','is_type','pid'}
    info_by_key = {}
    records = []
    record_by_id = {}
    for view in views:
        for key, header, is_type, pid in _param_columns(view):
            if key not in info_by_key:
                info = {'key': key, 'header': header + (u'（類型）'
                                                       if is_type else u''),
                        'is_type': is_type, 'pid': pid}
                info_by_key[key] = info
                infos.append(info)
        elements = DB.FilteredElementCollector(doc, view.Id) \
            .WhereElementIsNotElementType().ToElements()
        for element in elements:
            element_id = grid.id_value(element.Id)
            record = record_by_id.get(element_id)
            if record is None:
                record = {'id': element_id, 'element': element,
                          'label': _element_label(element), 'schedules': []}
                record_by_id[element_id] = record
                records.append(record)
            if view.Name not in record['schedules']:
                record['schedules'].append(view.Name)

    headers = logic.unique_headers([info['header'] for info in infos])
    columns = [
        {'key': KEY_ID, 'header': table_logic.ID_HEADER, 'editable': False},
        {'key': KEY_SCHEDULE, 'header': u'明細表', 'editable': False},
        {'key': KEY_ELEMENT, 'header': u'元素', 'editable': False}]
    for index, info in enumerate(infos):
        info['col_key'] = 'p{}'.format(index)
        info['header'] = headers[index]
        info['kind'] = grid.KIND_OTHER
        info['editable'] = False
        for record in records:
            param = cache.get(_target(doc, record['element'], info['is_type']),
                              info['pid'])
            if param is None:
                continue
            kind = grid.param_kind(param)
            if kind != grid.KIND_OTHER and not param.IsReadOnly:
                info['kind'] = kind
                info['editable'] = True
                break
            if info['kind'] == grid.KIND_OTHER:
                info['kind'] = kind
        columns.append({'key': info['col_key'], 'header': info['header'],
                        'editable': info['editable']})
    return columns, infos, records


def _print_preview(change_list, record_by_id):
    output = script.get_output()
    output.print_md(u'## {} — 寫入預覽'.format(TITLE))
    output.print_md(u'共 **{}** 格、**{}** 個元素。'.format(
        len(change_list), len(table_logic.changed_count_by_room(change_list))))
    output.print_table(
        table_data=[[output.linkify(record_by_id[c['id']]['element'].Id),
                     record_by_id[c['id']]['label'], c['header'],
                     c['old'], c['new']] for c in change_list],
        columns=[u'元素', u'名稱', u'參數', u'原值', u'新值'])


def _plan_writes(doc, change_list, record_by_id, info_by_col):
    items = []
    for change in change_list:
        info = info_by_col[change['key']]
        target = _target(doc, record_by_id[change['id']]['element'],
                         info['is_type'])
        target_id = grid.id_value(target.Id) if target is not None else -1
        items.append((target_id, change['key'], change['new'], change))
    return logic.group_writes(items)


def _conflict_text(conflicts, record_by_id, info_by_col):
    lines = []
    for target_id, col_key, values, changes in conflicts[:20]:
        names = u'、'.join(record_by_id[c['id']]['label'] for c in changes[:5])
        lines.append(u'{}：同一類型被改成 {}（{}）'.format(
            info_by_col[col_key]['header'],
            u' / '.join(u'「{}」'.format(v) for v in values), names))
    return u'\n'.join(lines)


def _commit(doc, writes, record_by_id, info_by_col, cache):
    failures = []
    transaction = DB.Transaction(doc, TITLE)
    transaction.Start()
    try:
        for target_id, col_key, value, changes in writes:
            info = info_by_col[col_key]
            change = changes[0]
            record = record_by_id[change['id']]
            target = _target(doc, record['element'], info['is_type'])
            try:
                if target is None:
                    raise Exception(u'找不到元素的類型')
                grid.write(cache.get(target, info['pid']), info['kind'], value)
            except Exception as error:
                failures.append(u'{} ／ {} = 「{}」：{}'.format(
                    record['label'], change['header'], value, error))
        if failures:
            transaction.RollBack()
        else:
            transaction.Commit()
    except Exception as error:
        if transaction.HasStarted() and not transaction.HasEnded():
            transaction.RollBack()
        failures.append(u'{}'.format(error))
    return failures


def main():
    doc = revit.doc
    views = _schedules(doc)
    if not views:
        forms.alert(u'這個專案沒有明細表。', title=TITLE)
        return
    chosen_ids = set(_ask(views))
    if not chosen_ids:
        return
    chosen = [v for v in views if grid.id_value(v.Id) in chosen_ids]

    cache = ParamCache()
    columns, infos, records = _collect(doc, chosen, cache)
    if not records:
        forms.alert(u'選取的明細表裡沒有元素。', title=TITLE)
        return
    if not infos:
        forms.alert(u'選取的明細表沒有可對應到元素參數的欄位'
                    u'（只有計算值、Count 之類的欄位）。', title=TITLE)
        return
    record_by_id = dict((r['id'], r) for r in records)
    info_by_col = dict((info['col_key'], info) for info in infos)

    original = {}
    for record in records:
        row = {KEY_SCHEDULE: u'、'.join(record['schedules']),
               KEY_ELEMENT: record['label']}
        for info in infos:
            target = _target(doc, record['element'], info['is_type'])
            param = cache.get(target, info['pid'])
            row[info['col_key']] = grid.read(param, grid.param_kind(param)) \
                if param is not None else u''
        original[record['id']] = row

    values = dict((rid, dict(row)) for rid, row in original.items())
    while True:
        window = grid.ParamGridWindow(XAML, columns, records, original,
                                      values, LABELS)
        window.ShowDialog()
        if window.result != 'apply':
            return
        values = window.values()
        change_list = table_logic.changes(values, original, columns)
        if not change_list:
            return
        writes, conflicts = _plan_writes(doc, change_list, record_by_id,
                                         info_by_col)
        if conflicts:
            forms.alert(
                u'類型參數有衝突：同一個類型在不同列被改成不同的值，'
                u'無法決定要寫哪一個。表格會重新開啟，請把同類型的值改成'
                u'一致。\n\n{}'.format(_conflict_text(conflicts, record_by_id,
                                                      info_by_col)),
                title=TITLE)
            continue
        _print_preview(change_list, record_by_id)
        answer = forms.alert(
            u'【dry-run 預覽】模型目前未變更。\n\n將寫入 {} 格（{} 個元素；'
            u'類型參數同類型只寫一次，實際寫入 {} 次），明細在輸出視窗。\n\n'
            u'確定寫入嗎？選「否」回到表格繼續編輯。'.format(
                len(change_list),
                len(table_logic.changed_count_by_room(change_list)),
                len(writes)),
            title=TITLE, yes=True, no=True)
        if not answer:
            continue
        failures = _commit(doc, writes, record_by_id, info_by_col, cache)
        if failures:
            forms.alert(
                u'有 {} 格寫不進去，交易已完整回復，模型未變更。\n'
                u'表格會重新開啟（你的修改都還在），請修正後再寫入。\n\n{}'
                .format(len(failures), u'\n'.join(failures[:25])), title=TITLE)
            continue
        forms.alert(u'已寫入 {} 格。'.format(len(change_list)), title=TITLE)
        return


try:
    main()
except Exception as error:
    forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
