# -*- coding: utf-8 -*-
__title__ = u'降樑貼齊'
from pyrevit import forms
import mcp_bridge as mcp

try:
    mcp.dry_run_then_apply(
        'align_beams_top_to_floor_bottom',
        {},                    # 預設 dry-run
        {'apply': True},
        u'降樑貼齊樓板底')
except mcp.MCPBridgeError as e:
    mcp.show_error(e, u'降樑貼齊')
