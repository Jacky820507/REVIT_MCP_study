# -*- coding: utf-8 -*-
__title__ = u'IFC結構\n同步'
from pyrevit import forms
import mcp_bridge as mcp

try:
    data = mcp.run('get_linked_models')
    if isinstance(data, list):
        links = data
    else:
        links = (data.get('LinkedModels') or data.get('Links')
                 or data.get('Models') or [])
    if not links:
        forms.alert(u'專案中沒有連結模型。', title=u'IFC 結構同步')
    else:
        names = [u'{} (ID: {})'.format(
            l.get('Name') or l.get('name'),
            l.get('Id') or l.get('ElementId')) for l in links]
        picked = forms.SelectFromList.show(
            names, title=u'選擇 IFC 連結模型', multiselect=False)
        if picked:
            link = links[names.index(picked)]
            link_id = link.get('Id') or link.get('ElementId')
            replace = forms.alert(
                u'是否重建既有同步結果（replaceExisting）？',
                title=u'IFC 結構同步', yes=True, no=True)
            mcp.dry_run_then_apply(
                'sync_ifc_structural_to_native',
                {'linkInstanceId': link_id},
                {'linkInstanceId': link_id, 'apply': True,
                 'replaceExisting': bool(replace)},
                u'IFC 結構同步')
except mcp.MCPBridgeError as e:
    mcp.show_error(e, u'IFC 結構同步')
