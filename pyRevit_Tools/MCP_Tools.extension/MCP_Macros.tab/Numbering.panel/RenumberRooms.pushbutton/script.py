# -*- coding: utf-8 -*-
__title__ = u'房間編號'
from pyrevit import forms
import mcp_bridge as mcp

def _summary(data):
    lines = [u'樓層: {}'.format(data.get('Level')),
             u'房間數: {}'.format(data.get('Count')),
             u'起訖: {} → {}'.format(data.get('StartNumber'),
                                     data.get('EndNumber'))]
    rooms = data.get('Rooms') or []
    for r in rooms[:10]:
        lines.append(u'  {}  {} → {}'.format(
            r.get('Name'), r.get('OldNumber'), r.get('NewNumber')))
    if len(rooms) > 10:
        lines.append(u'  …共 {} 間'.format(len(rooms)))
    return u'\n'.join(lines)

try:
    data = mcp.run('get_all_levels')
    if isinstance(data, list):
        levels = data
    else:
        levels = data.get('Levels') or data.get('levels') or []
    names = [l.get('Name') or l.get('name') for l in levels]
    level = forms.SelectFromList.show(names, title=u'選擇樓層',
                                      multiselect=False)
    if level:
        start = forms.ask_for_string(
            default='101',
            prompt=u'起始編號（例如 B134，尾碼位數會保留）',
            title=u'房間編號')
        if start:
            base = {'level': level, 'startNumber': start}
            preview = dict(base)
            preview['dryRun'] = True
            apply_p = dict(base)
            apply_p['dryRun'] = False
            mcp.dry_run_then_apply('renumber_rooms_by_level',
                                   preview, apply_p, u'房間編號', _summary)
except mcp.MCPBridgeError as e:
    mcp.show_error(e, u'房間編號')
