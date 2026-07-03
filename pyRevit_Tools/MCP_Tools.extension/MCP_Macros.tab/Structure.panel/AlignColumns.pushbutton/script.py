# -*- coding: utf-8 -*-
__title__ = u'柱頂貼齊'
from pyrevit import forms
import mcp_bridge as mcp

try:
    mcp.dry_run_then_apply(
        'align_columns_top_to_floor_bottom',
        {},
        {'apply': True},
        u'柱頂貼齊樓板底')
except mcp.MCPBridgeError as e:
    mcp.show_error(e, u'柱頂貼齊')
