# -*- coding: utf-8 -*-
__title__ = u'高隔間\n分析'
from pyrevit import forms, script
import json
import mcp_bridge as mcp

try:
    data = mcp.run('analyze_tall_partition_rooms',
                   {'autoDetectLevels': True, 'includeDetails': True})
    out = script.get_output()
    out.print_md('# 高隔間房間分析')
    out.print_md('```\n{}\n```'.format(
        json.dumps(data, ensure_ascii=False, indent=2)[:8000]))
    forms.alert(mcp.brief(data), title=u'高隔間分析（詳情見輸出視窗）')
except mcp.MCPBridgeError as e:
    mcp.show_error(e, u'高隔間分析')
