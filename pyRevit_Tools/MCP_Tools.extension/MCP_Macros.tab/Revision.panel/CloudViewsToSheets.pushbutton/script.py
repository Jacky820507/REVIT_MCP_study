# -*- coding: utf-8 -*-
__title__ = u'釋疑視圖\n上圖紙'
import mcp_bridge as mcp


def _summary(data):
    if not isinstance(data, dict):
        return mcp.brief(data)
    lines = []
    tb = data.get('TitleBlockUsed')
    if isinstance(tb, dict):
        lines.append(u'圖框：{} ({})'.format(
            tb.get('Name') or u'?', tb.get('FamilyName') or u''))
    elif tb:
        lines.append(u'圖框：{}'.format(tb))
    created = data.get('Created') or []
    skipped = data.get('Skipped') or []
    lines.append(u'將建立 {} 張圖紙：'.format(len(created)))
    for c in created[:10]:
        if isinstance(c, dict):
            lines.append(u'  {}  {}'.format(
                c.get('SheetNumber') or u'?',
                c.get('SheetName') or c.get('ViewName') or u''))
        else:
            lines.append(u'  {}'.format(c))
    if len(created) > 10:
        lines.append(u'  …其餘 {} 張'.format(len(created) - 10))
    if skipped:
        lines.append(u'跳過 {} 個視圖：'.format(len(skipped)))
        for s in skipped[:6]:
            if isinstance(s, dict):
                lines.append(u'  {}（{}）'.format(
                    s.get('ViewName') or u'?', s.get('Reason') or u''))
            else:
                lines.append(u'  {}'.format(s))
    if not lines:
        return mcp.brief(data)
    return u'\n'.join(lines)


try:
    mcp.dry_run_then_apply('add_cloud_views_to_sheets',
                           {'dryRun': True}, {},
                           u'釋疑視圖上圖紙', _summary)
except mcp.MCPBridgeError as e:
    mcp.show_error(e, u'釋疑視圖上圖紙')
