# -*- coding: utf-8 -*-
from __future__ import unicode_literals

__title__ = u'高隔間分析\nExcel'

from pyrevit import forms, revit


if revit.doc is None:
    forms.alert(
        u'請先開啟 Revit 專案檔，再執行高隔間分析 Excel。',
        title=u'高隔間分析 Excel',
        exitscript=True,
    )

import tall_partition_excel

try:
    reload(tall_partition_excel)
except Exception:
    pass

tall_partition_excel.run(revit.doc)
