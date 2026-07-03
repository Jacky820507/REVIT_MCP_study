# -*- coding: utf-8 -*-
__title__ = u'室內\n施工架'
from pyrevit import forms, script
import json
import mcp_bridge as mcp

try:
    data = mcp.run('calculate_room_scaffold_perimeters', {})
    out = script.get_output()
    out.print_md('# 室內施工架（房間周長）')
    out.print_md('```\n{}\n```'.format(
        json.dumps(data, ensure_ascii=False, indent=2)[:8000]))
    forms.alert(mcp.brief(data), title=u'室內施工架（詳情見輸出視窗）')
except mcp.MCPBridgeError as e:
    mcp.show_error(e, u'室內施工架')
