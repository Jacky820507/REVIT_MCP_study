# -*- coding: utf-8 -*-
from __future__ import unicode_literals

__title__ = u'門窗表\nExcel'

from pyrevit import forms, revit


if revit.doc is None:
    forms.alert(u'請先開啟 Revit 專案檔，再執行門窗表 Excel。',
                title=u'門窗表 Excel', exitscript=True)

import door_window_window
import takeoff_entry

try:
    reload(door_window_window)
    reload(takeoff_entry)
except Exception:
    pass

options = takeoff_entry.choose_options(
    revit.doc, u'門窗表 Excel｜選擇模型、樓層與主要 Excel',
    allow_host=True, host_required=False)
if options is not None:
    door_window_window.run(revit.doc, options)
