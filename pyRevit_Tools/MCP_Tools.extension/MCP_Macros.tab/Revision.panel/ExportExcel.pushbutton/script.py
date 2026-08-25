# -*- coding: utf-8 -*-
__title__ = u'釋疑\nExcel'
import os
from pyrevit import forms
import mcp_bridge as mcp

try:
    result = mcp.run('export_revision_excel', {})
    path = result.get('FilePath') if isinstance(result, dict) else None
    if path:
        count = result.get('Count')
        msg = u'已匯出釋疑清單'
        if count is not None:
            msg += u'（{} 筆）'.format(count)
        msg += u'：\n\n{}'.format(path)
        forms.alert(msg, title=u'釋疑Excel')
        if os.path.exists(path):
            os.startfile(path)
    else:
        forms.alert(u'匯出完成：\n\n{}'.format(mcp.brief(result)),
                    title=u'釋疑Excel')
except mcp.MCPBridgeError as e:
    mcp.show_error(e, u'釋疑Excel')
