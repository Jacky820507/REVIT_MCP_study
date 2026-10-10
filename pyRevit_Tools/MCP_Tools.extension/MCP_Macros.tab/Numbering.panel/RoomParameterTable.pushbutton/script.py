# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""房間參數表.

複選房間 → 複選參數 → 表格顯示（唯讀參數灰底只顯示）→ 表格內 Ctrl+C/V、
Ctrl+D 向下填滿、匯出/匯入 Excel → 關閉表格後 dry-run 預覽 → 單一
Transaction 寫入。表格操作與 Excel 對應規則在 ``room_param_grid_logic``
（有 CPython 測試）。

表格是 modal 視窗，只收集修改；寫入在視窗關掉之後才做。寫入有任何一格
失敗就整批回復，並帶著原本的修改重新開表格讓使用者修正，不會丟掉編輯。
"""

__title__ = u'房間\n參數表'
__author__ = 'RevitMCP'

import os

from Autodesk.Revit import DB
from pyrevit import forms, revit, script

import mcp_window as ui
import mcp_window_logic as spec_logic
import param_grid_window as grid
import room_param_grid_logic as logic


TITLE = u'房間參數表'
XAML = os.path.join(os.path.dirname(__file__), 'RoomParameterTable.xaml')

KEY_ID = grid.KEY_ID
KEY_LEVEL = 'k_level'


# ── Revit 讀取 ──────────────────────────────────────────────────────

def _builtin_text(element, bip):
    try:
        param = element.get_Parameter(bip)
        return (param.AsString() or u'') if param is not None else u''
    except Exception:
        return u''


def _builtin_name(element, bip):
    try:
        param = element.get_Parameter(bip)
        return param.Definition.Name if param is not None else u''
    except Exception:
        return u''


def _rooms(doc):
    rooms = DB.FilteredElementCollector(doc) \
        .OfCategory(DB.BuiltInCategory.OST_Rooms) \
        .WhereElementIsNotElementType() \
        .ToElements()
    records = []
    for room in rooms:
        level = None
        try:
            level = room.Level
        except Exception:
            pass
        records.append({
            'id': grid.id_value(room.Id),
            'element': room,
            'number': _builtin_text(room, DB.BuiltInParameter.ROOM_NUMBER),
            'name': _builtin_text(room, DB.BuiltInParameter.ROOM_NAME),
            'level': level.Name if level is not None else u'',
            'elevation': level.Elevation if level is not None else 0.0,
            'placed': room.Location is not None,
        })
    records.sort(key=lambda r: (r['elevation'], r['level'], r['number'],
                                r['name'], r['id']))
    return records


def _param_infos(records):
    """全部房間的實例參數聯集 ``{name: info}``。

    同名參數只要有一間可寫就算可寫——個別房間寫不進去時，寫入階段會
    逐格回報並整批回復，不會悄悄略過。
    """
    infos = {}
    for record in records:
        for param in record['element'].Parameters:
            try:
                name = param.Definition.Name
            except Exception:
                continue
            if not name:
                continue
            kind = grid.param_kind(param)
            editable = (not param.IsReadOnly) and kind != grid.KIND_OTHER
            info = infos.get(name)
            if info is None:
                infos[name] = {'name': name, 'kind': kind,
                               'editable': editable}
            elif editable and not info['editable']:
                info['editable'] = True
                info['kind'] = kind
    return infos


# ── 流程 ────────────────────────────────────────────────────────────

def _ask(records, infos, preferred):
    selected_ids = set()
    try:
        for element_id in revit.uidoc.Selection.GetElementIds():
            selected_ids.add(grid.id_value(element_id))
    except Exception:
        pass
    room_options = [(logic.room_label(record), record['id'])
                    for record in records]
    ordered = logic.sort_params(list(infos.values()), preferred)
    param_options = [(logic.param_label(info), info['name'])
                     for info in ordered]
    spec = spec_logic.spec(
        TITLE,
        [
            spec_logic.multichoice(
                'rooms', u'房間', room_options,
                default=[r['id'] for r in records if r['id'] in selected_ids],
                required=True, filter=True,
                help=u'可輸入編號、名稱或樓層篩選；Shift+點擊可連選。'
                     u'目前在模型中選取的房間已預先勾選。'),
            spec_logic.multichoice(
                'params', u'要顯示的參數', param_options,
                default=[name for name in preferred if name in infos],
                required=True, filter=True,
                help=u'標「（唯讀）」的參數（面積、周長…）只顯示、不能改。'),
            spec_logic.note(
                u'下一步會開啟表格：可直接編輯、複製貼上、向下填滿、匯出匯入 '
                u'Excel；寫入模型前會先預覽。'),
        ],
        badge=spec_logic.BADGE_WRITE, run_label=u'開啟表格',
        width=720, height=760)
    values = ui.ask(spec)
    if not values:
        return None, None
    return values.get('rooms') or [], values.get('params') or []


def _print_preview(change_list, record_by_id):
    output = script.get_output()
    output.print_md(u'## {} — 寫入預覽'.format(TITLE))
    output.print_md(u'共 **{}** 格、**{}** 間房間。'.format(
        len(change_list), len(logic.changed_count_by_room(change_list))))
    output.print_table(
        table_data=[[output.linkify(record_by_id[c['id']]['element'].Id),
                     logic.room_label(record_by_id[c['id']]), c['header'],
                     c['old'], c['new']] for c in change_list],
        columns=[u'房間', u'編號名稱', u'參數', u'原值', u'新值'])


def _commit(doc, change_list, record_by_id, kind_by_key, name_by_key):
    """單一 Transaction。回傳失敗清單；有失敗就整批回復。"""
    failures = []
    transaction = DB.Transaction(doc, TITLE)
    transaction.Start()
    try:
        for change in change_list:
            record = record_by_id[change['id']]
            param = record['element'].LookupParameter(name_by_key[change['key']])
            try:
                grid.write(param, kind_by_key[change['key']], change['new'])
            except Exception as error:
                failures.append((record, change, u'{}'.format(error)))
        if failures:
            transaction.RollBack()
        else:
            transaction.Commit()
    except Exception as error:
        if transaction.HasStarted() and not transaction.HasEnded():
            transaction.RollBack()
        failures.append((None, None, u'{}'.format(error)))
    return failures


def _failure_text(failures):
    lines = []
    for record, change, reason in failures[:25]:
        if record is None:
            lines.append(reason)
        else:
            lines.append(u'{} ／ {} = 「{}」：{}'.format(
                logic.room_label(record), change['header'], change['new'],
                reason))
    if len(failures) > 25:
        lines.append(u'…另有 {} 格'.format(len(failures) - 25))
    return u'\n'.join(lines)


def main():
    doc = revit.doc
    records = _rooms(doc)
    if not records:
        forms.alert(u'這個專案沒有房間。', title=TITLE)
        return
    infos = _param_infos(records)
    first = records[0]['element']
    preferred = [name for name in (
        _builtin_name(first, DB.BuiltInParameter.ROOM_NUMBER),
        _builtin_name(first, DB.BuiltInParameter.ROOM_NAME)) if name]

    room_ids, param_names = _ask(records, infos, preferred)
    if not room_ids or not param_names:
        return
    wanted = set(room_ids)
    chosen = [record for record in records if record['id'] in wanted]
    record_by_id = dict((record['id'], record) for record in chosen)

    ordered = [info for info in logic.sort_params(list(infos.values()),
                                                  preferred)
               if info['name'] in set(param_names)]
    columns = [{'key': KEY_ID, 'header': logic.ID_HEADER, 'editable': False},
               {'key': KEY_LEVEL, 'header': logic.LEVEL_HEADER,
                'editable': False}]
    kind_by_key = {}
    name_by_key = {}
    for index, info in enumerate(ordered):
        key = 'p{}'.format(index)
        columns.append({'key': key, 'header': info['name'],
                        'editable': info['editable']})
        kind_by_key[key] = info['kind']
        name_by_key[key] = info['name']

    original = {}
    for record in chosen:
        row = {KEY_LEVEL: record['level']}
        for key, name in name_by_key.items():
            row[key] = grid.read(record['element'].LookupParameter(name),
                             kind_by_key[key])
        original[record['id']] = row

    values = dict((room_id, dict(row)) for room_id, row in original.items())
    while True:
        window = grid.ParamGridWindow(XAML, columns, chosen, original,
                                      values, grid.ROOM_LABELS)
        window.ShowDialog()
        if window.result != 'apply':
            return
        values = window.values()
        change_list = logic.changes(values, original, columns)
        if not change_list:
            return
        _print_preview(change_list, record_by_id)
        answer = forms.alert(
            u'【dry-run 預覽】模型目前未變更。\n\n將寫入 {} 格（{} 間房間），'
            u'明細在輸出視窗。\n\n確定寫入嗎？選「否」回到表格繼續編輯。'.format(
                len(change_list),
                len(logic.changed_count_by_room(change_list))),
            title=TITLE, yes=True, no=True)
        if not answer:
            continue
        failures = _commit(doc, change_list, record_by_id, kind_by_key,
                           name_by_key)
        if failures:
            forms.alert(
                u'有 {} 格寫不進去，交易已完整回復，模型未變更。\n'
                u'表格會重新開啟（你的修改都還在），請修正後再寫入。\n\n{}'
                .format(len(failures), _failure_text(failures)), title=TITLE)
            continue
        forms.alert(u'已寫入 {} 格（{} 間房間）。'.format(
            len(change_list), len(logic.changed_count_by_room(change_list))),
            title=TITLE)
        return


try:
    main()
except Exception as error:
    forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
