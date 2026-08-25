# -*- coding: utf-8 -*-
from __future__ import unicode_literals

__title__ = u'室內施工架\nExcel'
__author__ = 'Codex'

import os

from pyrevit import forms, revit, script

import scaffold_excel
import takeoff_entry

reload(scaffold_excel)

if revit.doc is None:
    forms.alert(
        u'請先開啟 Revit 專案文件。',
        title=u'室內施工架 Excel',
    )
    script.exit()

entry_options = takeoff_entry.choose_options(
    revit.doc,
    u'室內施工架 Excel',
    allow_host=True,
    host_required=False,
)
if not entry_options:
    script.exit()

if not entry_options.get('workbook_path'):
    scaffold_excel.run('general', options=entry_options)
    script.exit()

space_update_script = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    'SpaceTableUpdate.pushbutton',
    'script.py',
)
space_update_result = {}
space_update_globals = {
    '__file__': space_update_script,
    '__name__': '__mcp_embedded_space_table_update__',
    '_MCP_EMBEDDED_RESULT': space_update_result,
    '_TAKEOFF_OPTIONS': entry_options,
}

execfile(space_update_script, space_update_globals)

if space_update_result.get('handled_error'):
    script.exit()

if space_update_result.get('error'):
    forms.alert(
        u'空間表更新失敗，因此未執行施工架計算。\n\n{}'.format(
            space_update_result['error']),
        title=u'室內施工架 Excel',
    )
    script.exit()

if not space_update_result.get('path') or not space_update_result.get('sheet'):
    forms.alert(
        u'空間表更新未完成，因此未執行施工架計算。',
        title=u'室內施工架 Excel',
    )
    script.exit()

scaffold_excel.run(
    'general',
    excel_path=space_update_result['path'],
    space_sheet_name=space_update_result['sheet'],
    existing_backup=space_update_result.get('backup'),
    options=entry_options,
)
