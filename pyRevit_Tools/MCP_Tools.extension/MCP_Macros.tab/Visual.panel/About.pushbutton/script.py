# -*- coding: utf-8 -*-
__title__ = u'關於 \U0001F99E'
from pyrevit import forms

forms.alert(
    u'MCP 巨集 — pyRevit 按鈕系統\n\n'
    u'這些按鈕透過 DLL 橋接直呼 RevitMCP add-in 的\n'
    u'C# 演算法（與 AI 對話用的是同一套後端）。\n\n'
    u'\U0001F99E 一隻被討論好的龍蝦，如約送達。\n\n'
    u'需求：RevitMCP add-in 已安裝。\n'
    u'文件：pyRevit_Tools/README.md',
    title=u'MCP 巨集')
