# -*- coding: utf-8 -*-
__title__ = u'防火上色'
from pyrevit import forms, revit, DB
import mcp_bridge as mcp

COLORS = {
    'green':  {'r': 0,   'g': 190, 'b': 0,   't': 20},
    'yellow': {'r': 240, 'g': 200, 'b': 0,   't': 20},
    'blue':   {'r': 0,   'g': 120, 'b': 255, 't': 40},
    'purple': {'r': 170, 'g': 0,   'b': 255, 't': 40},
}

def classify(value):
    if not value:
        return 'purple'
    if '2' in value:
        return 'green'
    if '1' in value:
        return 'yellow'
    return 'blue'

try:
    view = mcp.run('get_active_view')
    # get_active_view 回傳欄位是 ElementId（不是 Id）；viewId 傳 null 會讓 C# 端炸掉
    view_id = view.get('ElementId') or view.get('Id')
    if view_id is None:
        raise mcp.MCPBridgeError(u'get_active_view 未回傳視圖 ID：{}'.format(view))
    walls = mcp.run('query_elements',
                    {'category': 'Walls', 'viewId': view_id})
    elements = walls.get('Elements') or []
    if not elements:
        forms.alert(u'目前視圖沒有牆。', title=u'防火上色')
    else:
        pname = forms.ask_for_string(
            default=u'防火等級',
            prompt=u'防火時效參數名稱（實例或類型參數皆可，'
                   u'預設讀牆類型內建「防火等級」；也可改用「備註」等自訂欄位）',
            title=u'防火上色')
        if pname:
            doc = revit.doc
            groups = {}
            dist = {}
            for e in elements:
                eid = e.get('ElementId') or e.get('Id')
                elem = doc.GetElement(DB.ElementId(int(eid)))
                val = u''
                if elem is not None:
                    # 先找實例參數；找不到或空值時改找牆類型上的同名參數
                    p = elem.LookupParameter(pname)
                    if not (p and p.AsString()):
                        wtype = doc.GetElement(elem.GetTypeId())
                        if wtype is not None:
                            p = wtype.LookupParameter(pname) or p
                    if p and p.AsString():
                        val = p.AsString().strip()
                key = classify(val)
                groups.setdefault(key, []).append(int(eid))
                label = val or u'(空值)'
                dist[label] = dist.get(label, 0) + 1
            total = 0
            for key, ids in groups.items():
                c = COLORS[key]
                mcp.run('override_element_graphics', {
                    'elementIds': ids, 'viewId': view_id,
                    'surfaceFillColor': {'r': c['r'], 'g': c['g'],
                                         'b': c['b']},
                    'transparency': c['t']})
                total += len(ids)
            lines = [u'已上色 {} 面牆'.format(total), u'', u'分布：']
            for k in sorted(dist, key=lambda x: -dist[x]):
                lines.append(u'  {}: {}'.format(k, dist[k]))
            lines += [u'', u'圖例：綠=2HR 黃=1HR 藍=其他 紫=空值']
            forms.alert(u'\n'.join(lines), title=u'防火上色')
except mcp.MCPBridgeError as e:
    mcp.show_error(e, u'防火上色')
