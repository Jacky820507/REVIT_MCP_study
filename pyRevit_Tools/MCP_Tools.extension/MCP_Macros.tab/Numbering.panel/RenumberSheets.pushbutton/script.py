# -*- coding: utf-8 -*-
__title__ = u'圖紙\n重編號'
from pyrevit import forms
import mcp_bridge as mcp

def _summary(data):
    lines = [data.get('Message') or u'']
    for m in (data.get('PlannedMoves') or [])[:15]:
        lines.append(u'  {} → {}  ({})'.format(
            m.get('OldNumber'), m.get('NewNumber'), m.get('SheetName')))
    return u'\n'.join(lines)

try:
    mcp.dry_run_then_apply('auto_renumber_sheets',
                           {'dryRun': True}, {},
                           u'圖紙重編號', _summary)
except mcp.MCPBridgeError as e:
    mcp.show_error(e, u'圖紙重編號')
