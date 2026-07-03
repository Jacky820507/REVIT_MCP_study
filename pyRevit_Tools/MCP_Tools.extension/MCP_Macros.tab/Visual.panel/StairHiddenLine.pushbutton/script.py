# -*- coding: utf-8 -*-
__title__ = u'樓梯\n隱藏線'
from pyrevit import forms
import mcp_bridge as mcp

def _lines_of(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ('HiddenLines', 'Lines', 'hiddenLines', 'lines'):
            if data.get(key):
                return data[key]
    return []

try:
    view = mcp.run('get_active_view')
    if 'section' not in (view.get('ViewType') or '').lower():
        forms.alert(u'請先切到剖面視圖再執行。', title=u'樓梯隱藏線',
                    exitscript=True)
    traced = mcp.run('trace_stair_geometry', {})
    lines = _lines_of(traced)
    if not lines:
        forms.alert(u'此剖面沒有偵測到組合式樓梯的隱藏梯級。',
                    title=u'樓梯隱藏線')
    else:
        styles_data = mcp.run('get_line_styles')
        if isinstance(styles_data, list):
            styles = styles_data
        else:
            styles = (styles_data.get('LineStyles')
                      or styles_data.get('Styles') or [])
        dashed = [s for s in styles if u'虛線' in (s.get('Name') or '')]
        pool = dashed or styles
        names = [u'{} (ID: {})'.format(s.get('Name'), s.get('Id'))
                 for s in pool]
        picked = forms.SelectFromList.show(
            names, title=u'選擇虛線線型', multiselect=False)
        if picked:
            style = pool[names.index(picked)]
            r = mcp.run('create_detail_lines', {
                'viewId': view.get('Id'),
                'styleId': style.get('Id'),
                'lines': lines})
            forms.alert(mcp.brief(r), title=u'樓梯隱藏線')
except mcp.MCPBridgeError as e:
    mcp.show_error(e, u'樓梯隱藏線')
