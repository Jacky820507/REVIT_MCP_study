# -*- coding: utf-8 -*-
__title__ = u'清除上色'
from pyrevit import forms, revit
import mcp_bridge as mcp

def _id_value(eid):
    # Revit 2025+ 用 .Value；2020-2024 用 .IntegerValue
    return getattr(eid, 'Value', None) or eid.IntegerValue

try:
    ids = [_id_value(e.Id) for e in revit.get_selection().elements]
    if not ids:
        forms.alert(u'請先選取要清除覆寫的元素（可框選整區）。',
                    title=u'清除上色')
    else:
        data = mcp.run('clear_element_override', {'elementIds': ids})
        forms.alert(mcp.brief(data), title=u'清除上色')
except mcp.MCPBridgeError as e:
    mcp.show_error(e, u'清除上色')
