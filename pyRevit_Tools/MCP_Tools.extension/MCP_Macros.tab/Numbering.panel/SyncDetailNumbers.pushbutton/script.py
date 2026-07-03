# -*- coding: utf-8 -*-
__title__ = u'詳圖編號\n同步'
from pyrevit import forms
import mcp_bridge as mcp

try:
    if forms.alert(u'將同步詳圖元件編號與圖紙號碼，繼續？',
                   title=u'詳圖編號同步', yes=True, no=True):
        data = mcp.run('sync_detail_component_numbers')
        forms.alert(mcp.brief(data), title=u'詳圖編號同步')
except mcp.MCPBridgeError as e:
    mcp.show_error(e, u'詳圖編號同步')
