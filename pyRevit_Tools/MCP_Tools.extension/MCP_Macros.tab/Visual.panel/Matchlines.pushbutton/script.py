# -*- coding: utf-8 -*-
from __future__ import unicode_literals

__title__ = u'銜接線\n標註'

from pyrevit import forms, revit


if revit.doc is None:
    forms.alert(u'請先開啟 Revit 專案檔，再執行銜接線標註。',
                title=u'銜接線標註', exitscript=True)

if revit.active_view is None:
    forms.alert(u'找不到目前視圖，請先開啟母視圖。',
                title=u'銜接線標註', exitscript=True)

import matchline_button

try:
    reload(matchline_button)
except Exception:
    pass

matchline_button.run(revit.doc, revit.active_view)
