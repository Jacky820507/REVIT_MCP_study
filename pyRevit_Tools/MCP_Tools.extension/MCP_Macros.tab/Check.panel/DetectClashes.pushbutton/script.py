# -*- coding: utf-8 -*-
__title__ = u'碰撞偵測'
from pyrevit import forms
import mcp_bridge as mcp

try:
    data = mcp.run('detect_clashes', {})
    forms.alert(mcp.brief(data), title=u'碰撞偵測結果')
    if forms.alert(u'要將碰撞結果上色嗎？', title=u'碰撞偵測',
                   yes=True, no=True):
        mcp.run('colorize_clashes', {})
    if forms.alert(u'要匯出 CSV 報告嗎？', title=u'碰撞偵測',
                   yes=True, no=True):
        path = forms.save_file(file_ext='csv')
        if path:
            r = mcp.run('export_clash_report',
                        {'outputPath': path, 'format': 'csv'})
            forms.alert(mcp.brief(r), title=u'碰撞報告')
except mcp.MCPBridgeError as e:
    mcp.show_error(e, u'碰撞偵測')
