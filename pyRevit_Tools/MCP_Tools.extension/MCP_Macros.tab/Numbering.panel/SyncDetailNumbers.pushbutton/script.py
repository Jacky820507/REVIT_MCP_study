# -*- coding: utf-8 -*-
__title__ = u'詳圖編號\n同步'
from pyrevit import forms, script
import mcp_bridge as mcp

ACTION_LABEL = {
    'ok': u'一致',
    'update': u'需修正',
    'updated': u'已修正',
    'empty_key': u'主鍵空值',
    'not_matched': u'查無圖紙',
    'ambiguous': u'圖紙名稱重複',
    'target_unwritable': u'參數不可寫入',
}

RENAME_LABEL = {
    'name_ok': u'一致',
    'rename': u'需改名',
    'renamed': u'已改名',
    'rename_conflict': u'改名衝突',
    'no_detail_name': u'無詳圖名稱',
    'rename_disabled': u'—',
}


def _pick(items, title, labeler):
    """SelectFromList 單選；回傳被選中的原始項目，取消回傳 None。"""
    labels = [labeler(i) for i in items]
    picked = forms.SelectFromList.show(labels, title=title, multiselect=False)
    if not picked:
        return None
    return items[labels.index(picked)]


def _summary(data):
    lines = [data.get('Message') or u'']
    items = data.get('Items') or []
    changed = [i for i in items if i.get('Action') in ('update', 'updated')]
    if changed:
        lines.append(u'')
        lines.append(u'參數修正（{} 筆）：'.format(len(changed)))
        for i in changed[:12]:
            lines.append(u'  {}  {} → {}'.format(
                i.get('TypeName'),
                i.get('CurrentValue') or u'(空)',
                i.get('ExpectedValue')))
        if len(changed) > 12:
            lines.append(u'  …其餘見輸出視窗')
    renames = [i for i in items
               if i.get('RenameAction') in ('rename', 'renamed')]
    if renames:
        lines.append(u'')
        lines.append(u'類型改名（{} 筆）：'.format(len(renames)))
        for i in renames[:10]:
            lines.append(u'  {}\n    → {}'.format(
                i.get('TypeName'), i.get('ExpectedTypeName')))
        if len(renames) > 10:
            lines.append(u'  …其餘見輸出視窗')
    return u'\n'.join(lines)


def _print_detail(data):
    items = data.get('Items') or []
    if not items:
        return
    out = script.get_output()
    out.print_md(u'### 詳圖標頭圖紙欄位檢核明細（{}）'.format(
        u'以圖紙號碼為主' if data.get('MatchBy') == 'sheetNumber'
        else u'以圖紙名稱為主'))
    out.print_md(u'主鍵參數：`{}`　修正參數：`{}`'.format(
        data.get('KeyParameter'), data.get('TargetParameter')))
    out.print_md(u'| 標頭類型 | 主鍵值 | 現值 | 期望值 | 參數狀態 | 類型名稱檢核 |')
    out.print_md(u'|---|---|---|---|---|---|')
    for i in items:
        action = i.get('Action') or ''
        label = ACTION_LABEL.get(action, action)
        if action in ('update', 'updated'):
            label = u'**{}**'.format(label)
        if action == 'ambiguous':
            cands = u'; '.join(u'{}({})'.format(
                c.get('SheetNumber'), c.get('SheetName'))
                for c in (i.get('Candidates') or []))
            label = u'{}：{}'.format(label, cands)
        raction = i.get('RenameAction') or 'rename_disabled'
        rlabel = RENAME_LABEL.get(raction, raction)
        if raction in ('rename', 'renamed'):
            rlabel = u'**{}** → {}'.format(rlabel, i.get('ExpectedTypeName'))
        elif raction == 'rename_conflict':
            rlabel = u'{}（{} 已存在）'.format(rlabel, i.get('ExpectedTypeName'))
        out.print_md(u'| {} | {} | {} | {} | {} | {} |'.format(
            i.get('TypeName'),
            i.get('KeyValue') or u'(空)',
            i.get('CurrentValue') or u'(空)',
            i.get('ExpectedValue') or u'—',
            label,
            rlabel))


try:
    # 1. 選詳圖標頭家族（動態偵測，不綁死 AE-圖號）
    fam_data = mcp.run('get_detail_component_families')
    families = fam_data.get('Families') or []
    if not families:
        forms.alert(u'專案中沒有詳圖元件/通用註解家族。',
                    title=u'詳圖編號同步', exitscript=True)
    family = _pick(families, u'選擇詳圖標頭家族',
                   lambda f: u'{}（{} 類型）'.format(
                       f.get('Name'), f.get('TypeCount')))
    if family:
        params = family.get('ParameterNames') or []
        writable = [p for p in params if not p.get('IsReadOnly')]
        if len(writable) < 2:
            forms.alert(u'此家族可寫入的文字類型參數不足兩個，無法檢核。',
                        title=u'詳圖編號同步', exitscript=True)

        # 2. 選模式：哪個欄位當主鍵（可信），修正另一個
        modes = [
            {'key': 'sheetNumber',
             'label': u'以圖紙號碼為主（檢核並修正圖紙名稱）'},
            {'key': 'sheetName',
             'label': u'以圖紙名稱為主（檢核並修正圖紙號碼）'},
        ]
        mode = _pick(modes, u'選擇比對主鍵', lambda m: m['label'])
        if mode:
            def _plabel(p):
                sample = p.get('Sample') or u''
                if sample:
                    return u'{}（範例: {}）'.format(p.get('Name'), sample)
                return p.get('Name')

            def _sorted(preferred):
                return sorted(writable,
                              key=lambda p: (p.get('Name') != preferred,
                                             p.get('Name')))

            # 3. 選「圖紙號碼」參數（常用名排最前）
            num_param = _pick(_sorted(u'詳圖圖號'),
                              u'選擇存放「圖紙號碼」的參數', _plabel)
            if num_param:
                # 4. 選「圖紙名稱」參數（排除步驟 3 已選）
                rest = [p for p in writable
                        if p.get('Name') != num_param.get('Name')]
                rest.sort(key=lambda p: (p.get('Name') != u'圖說名稱',
                                         p.get('Name')))
                name_param = _pick(rest,
                                   u'選擇存放「圖紙名稱」的參數', _plabel)
                if name_param:
                    # 5. 選「詳圖名稱」參數：只偵測使用者 key in 的值、不寫入，
                    #    選定後類型改名為「圖紙號碼-圖紙名稱-詳圖名稱」
                    used = (num_param.get('Name'), name_param.get('Name'))
                    d_rest = [p for p in params
                              if p.get('Name') not in used]
                    d_rest.sort(key=lambda p: (p.get('Name') != u'詳圖名稱',
                                               p.get('Name')))
                    detail_param = _pick(
                        d_rest,
                        u'選擇存放「詳圖名稱」的參數（只偵測，選定後類型改名為：圖號-圖紙名-詳圖名）',
                        _plabel)
                    if not detail_param:
                        script.exit()
                    base = {
                        'familyName': family.get('Name'),
                        'matchBy': mode['key'],
                        'sheetNumberParameter': num_param.get('Name'),
                        'sheetNameParameter': name_param.get('Name'),
                        'renameTypes': True,
                        'detailNameParameter': detail_param.get('Name'),
                    }
                    preview = dict(base)
                    preview['dryRun'] = True
                    apply_p = dict(base)
                    apply_p['dryRun'] = False

                    # 5. dry-run → 確認 → 套用；完整明細寫輸出視窗
                    dry = mcp.run('sync_detail_component_sheet_fields',
                                  preview)
                    _print_detail(dry)
                    if dry.get('UpdatedCount') or dry.get('RenamedCount'):
                        if forms.alert(
                                u'【dry-run 預覽】\n\n{}\n\n確定要套用嗎？'
                                .format(_summary(dry)),
                                title=u'詳圖編號同步', yes=True, no=True):
                            result = mcp.run(
                                'sync_detail_component_sheet_fields',
                                apply_p)
                            _print_detail(result)
                            forms.alert(u'【已套用】\n\n{}'.format(
                                _summary(result)), title=u'詳圖編號同步')
                    else:
                        forms.alert(
                            u'{}\n\n沒有需要修正的項目。'.format(
                                _summary(dry)),
                            title=u'詳圖編號同步')
except mcp.MCPBridgeError as e:
    mcp.show_error(e, u'詳圖編號同步')
