# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from pyrevit import forms, revit, script

import agile_bim_governance as governance


__title__ = u'房間參數\n字典'
_TITLE = u'房間參數字典'


def _save_report(report):
    if not forms.alert(u'要另存 JSON 參數字典嗎？', title=_TITLE, yes=True, no=True):
        return
    path = forms.save_file(file_ext='json', default_name='room-parameter-dictionary.json')
    if path:
        governance.write_json(path, report)
        forms.alert(u'已輸出：\n{0}'.format(path), title=_TITLE)


if revit.doc is None:
    forms.alert(u'請先開啟 Revit 專案檔，再執行房間參數字典。',
                title=_TITLE, exitscript=True)

try:
    rooms = governance.collect_rooms(revit.doc, include_unplaced=True)
    parameters = governance.parameter_dictionary(
        rooms, include_values=True, max_samples=5)
    report = {
        'Success': True,
        'Scope': {
            'IncludeUnplaced': True,
            'RoomCount': len(rooms),
        },
        'Summary': {
            'TotalRooms': len(rooms),
            'Parameters': len(parameters),
        },
        'Parameters': parameters,
        'Message': u'唯讀盤點完成；本按鈕沒有修改模型。',
    }
    output = script.get_output()
    output.print_md(u'## {0}'.format(_TITLE))
    output.print_md(u'**{0}**'.format(report['Message']))
    output.print_table([
        [u'房間數', len(rooms)],
        [u'參數數', len(parameters)],
    ], [u'項目', u'數值'], title=u'摘要')
    rows = []
    for item in parameters:
        rows.append([
            item['Name'],
            u', '.join(item['StorageTypes']),
            item['WritableSampleCount'],
            item['ReadOnlySampleCount'],
            item['SampleCount'],
        ])
    output.print_table(rows,
                       [u'參數名稱', u'StorageType', u'可寫樣本', u'唯讀樣本', u'樣本數'],
                       title=u'Room 實際參數')
    _save_report(report)
except Exception as ex:
    forms.alert(u'參數字典失敗：\n{0}'.format(ex),
                title=_TITLE, exitscript=True)
