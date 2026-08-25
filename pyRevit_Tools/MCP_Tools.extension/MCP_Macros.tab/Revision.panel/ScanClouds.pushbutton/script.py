# -*- coding: utf-8 -*-
__title__ = u'掃描\n釋疑'
import mcp_bridge as mcp


def _summary(data):
    if not isinstance(data, dict):
        return mcp.brief(data)
    clouds = data.get('Clouds') or []
    lines = [u'共 {} 朵修訂雲形'.format(data.get('Count', len(clouds)))]
    for c in clouds[:14]:
        mark = c.get('Mark') or u'(未編號)'
        view = c.get('ViewName') or u'?'
        sheet = c.get('SheetNumber')
        loc = u'{} [{}]'.format(view, sheet) if sheet else view
        lines.append(u'  {}  {}'.format(mark, loc))
    if len(clouds) > 14:
        lines.append(u'  …其餘 {} 朵'.format(len(clouds) - 14))
    lines.append(u'')
    lines.append(u'套用＝把釋疑編號寫入 Mark、定位寫入 Comments（已編號者保留不動）')
    return u'\n'.join(lines)


try:
    mcp.dry_run_then_apply('scan_revision_clouds',
                           {'writeBack': False}, {'writeBack': True},
                           u'掃描釋疑', _summary)
except mcp.MCPBridgeError as e:
    mcp.show_error(e, u'掃描釋疑')
