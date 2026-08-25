# -*- coding: utf-8 -*-
from __future__ import unicode_literals

__title__ = u'停車位\nExcel'
__author__ = 'Codex'

from pyrevit import forms, revit


if revit.doc is None:
    forms.alert(
        u'請先開啟 Revit 專案檔，再執行停車位 Excel。',
        title=u'停車位 Excel',
        exitscript=True,
    )

import parking_excel
import takeoff_entry

try:
    reload(parking_excel)
    reload(takeoff_entry)
except Exception:
    pass

options = takeoff_entry.choose_options(
    revit.doc, u'停車位 Excel｜選擇模型、樓層與主要 Excel',
    allow_host=True, host_required=False)
if options is not None:
    parking_excel.run(revit.doc, options)
