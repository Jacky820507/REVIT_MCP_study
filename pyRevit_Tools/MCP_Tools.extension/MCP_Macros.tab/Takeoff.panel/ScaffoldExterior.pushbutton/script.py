# -*- coding: utf-8 -*-
__title__ = u'室外\n施工架'
from pyrevit import forms, script
import json
import mcp_bridge as mcp

try:
    data = mcp.run('calculate_exterior_wall_scaffold_perimeter', {})
    out = script.get_output()
    out.print_md('# 室外施工架（外牆周長）')
    out.print_md('```\n{}\n```'.format(
        json.dumps(data, ensure_ascii=False, indent=2)[:8000]))
    forms.alert(mcp.brief(data), title=u'室外施工架（詳情見輸出視窗）')
except mcp.MCPBridgeError as e:
    mcp.show_error(e, u'室外施工架')
