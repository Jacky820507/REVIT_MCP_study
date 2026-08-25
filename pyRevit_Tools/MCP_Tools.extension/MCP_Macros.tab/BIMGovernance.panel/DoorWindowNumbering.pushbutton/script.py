# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from pyrevit import forms, revit, script

import agile_bim_governance as governance


__title__ = u'門窗\n編號'
_TITLE = u'門窗編號'


def _pick(options, prompt):
    labels = [label for label, unused in options]
    selected = forms.SelectFromList.show(
        labels, title=prompt, multiselect=False)
    if not selected:
        return None
    for label, value in options:
        if label == selected:
            return value
    return None


def _print_report(report, title):
    output = script.get_output()
    summary = report['Summary']
    output.print_md(u'## {0}'.format(title))
    output.print_md(u'**{0}**'.format(report['Message']))
    output.print_table([
        [u'選取門窗', summary['Total']],
        [u'目標', summary['Targets']],
        [u'提案', summary['Proposed']],
        [u'不變', summary['Unchanged']],
        [u'阻擋', summary['Blocked']],
        [u'衝突', summary['Collisions']],
        [u'已寫入', summary.get('AppliedChanges', 0)],
    ], [u'項目', u'數值'], title=u'摘要')
    rows = []
    for plan in report['Openings']:
        rows.append([
            plan['Category'], plan['Level'], plan['Family'], plan['Type'],
            plan['InstanceCount'], plan['CurrentValue'], plan['ProposedValue'],
            plan['Status'], plan['Reason'],
        ])
    output.print_table(rows, [u'類別', u'樓層', u'族群', u'類型', u'樘數',
                              u'既有編號', u'建議編號', u'狀態', u'說明'],
                       title=u'門窗編號提案')


def _save_report(report):
    if not forms.alert(u'要另存 JSON 門窗編號報告嗎？', title=_TITLE, yes=True, no=True):
        return
    path = forms.save_file(file_ext='json', default_name='door-window-numbering-report.json')
    if path:
        governance.write_json(path, report)
        forms.alert(u'已輸出：\n{0}'.format(path), title=_TITLE)


if revit.doc is None:
    forms.alert(u'請先開啟 Revit 專案檔，再執行門窗編號。',
                title=_TITLE, exitscript=True)

try:
    target_parameter = forms.ask_for_string(
        default=u'門窗編號',
        prompt=u'寫入哪個實際 String 參數？（可填 Mark／Type Mark 或專案參數）',
        title=_TITLE)
    if target_parameter:
        target_parameter = target_parameter.strip()
        target_scope = _pick([
            (u'實例參數（每樘各自編號）', u'instance'),
            (u'類型參數（同類型共用編號）', u'type'),
        ], u'選擇寫入範圍')
        source = _pick([
            (u'產生流水號', u'sequence'),
            (u'由類型註記帶入', u'type_mark'),
            (u'由類型名稱帶入', u'type_name'),
            (u'由其他參數帶入', u'parameter'),
            (u'填入固定文字', u'constant'),
        ], u'選擇編號來源')
        if target_scope and source:
            config = {
                'targetParameter': target_parameter,
                'targetScope': target_scope,
                'source': source,
                'sequenceScope': _pick([
                    (u'依類別分開（門、窗各自從 1 開始）', u'category'),
                    (u'全模型共用一組流水號', u'global'),
                    (u'依樓層分開', u'level'),
                    (u'依樓層與類別分開', u'level_category'),
                ], u'選擇流水號範圍') if source == u'sequence' else u'category',
                'prefix': u'',
                'start': 1,
                'pad': 0,
                'includeCurtain': False,
            }
            if source == u'sequence':
                config['prefix'] = forms.ask_for_string(
                    default=u'', prompt=u'預設前綴（可留白；門/窗可再分別設定）',
                    title=_TITLE) or u''
                config['doorPrefix'] = forms.ask_for_string(
                    default=config['prefix'], prompt=u'門前綴', title=_TITLE)
                config['windowPrefix'] = forms.ask_for_string(
                    default=config['prefix'], prompt=u'窗前綴', title=_TITLE)
                start = forms.ask_for_string(
                    default=u'1', prompt=u'起始流水號', title=_TITLE)
                pad = forms.ask_for_string(
                    default=u'0', prompt=u'補零位數（0–12）', title=_TITLE)
                config['start'] = int(start or 1)
                config['pad'] = int(pad or 0)
            elif source == u'parameter':
                config['sourceParameter'] = forms.ask_for_string(
                    default=u'', prompt=u'來源參數名稱', title=_TITLE) or u''
            elif source == u'constant':
                config['constant'] = forms.ask_for_string(
                    default=u'', prompt=u'固定文字', title=_TITLE) or u''

            categories = forms.SelectFromList.show(
                [u'門', u'窗'], title=u'選擇類別（可複選）', multiselect=True)
            if categories:
                config['categories'] = [u'doors' if value == u'門' else u'windows'
                                        for value in categories]
                mode = _pick([
                    (u'只填空白（保留既有編號）', u'fill_blank'),
                    (u'覆寫符合計畫的編號', u'overwrite'),
                ], u'選擇寫入模式')
                if mode:
                    records = governance.collect_agile_openings(
                        revit.doc, categories=config['categories'],
                        include_curtain=False)
                    plans = governance.build_door_window_numbering_preview(
                        records, config, mode)
                    public_plans = [governance._plan_public(plan, 'numbering')
                                    for plan in plans]
                    report = {
                        'Success': True,
                        'Applied': False,
                        'Mode': mode,
                        'TargetParameter': target_parameter,
                        'Summary': governance._classification_summary(
                            plans, len(records)),
                        'Openings': public_plans,
                        'Message': u'門窗編號 preview 完成；目前沒有修改模型。',
                    }
                    _print_report(report, _TITLE + u'｜Preview')
                    _save_report(report)
                    if forms.alert(
                            u'Preview 已完成。要依 {0} 寫入門窗編號嗎？\n\n'
                            u'是：執行單一 Transaction；否：只保留報告。'.format(mode),
                            title=_TITLE, yes=True, no=True):
                        applied = governance.apply_door_window_numbering_plans(
                            revit.doc, plans, target_parameter)
                        applied_report = {
                            'Success': True,
                            'Applied': True,
                            'Mode': mode,
                            'TargetParameter': target_parameter,
                            'Summary': governance._classification_summary(
                                plans, len(records), applied, 0),
                            'Openings': [governance._plan_public(plan, 'numbering')
                                         for plan in plans],
                            'Message': u'門窗編號已寫入；請重新查詢模型驗證實際值。',
                        }
                        _print_report(applied_report, _TITLE + u'｜Apply')
                        _save_report(applied_report)
except Exception as ex:
    forms.alert(u'門窗編號失敗：\n{0}'.format(ex),
                title=_TITLE, exitscript=True)
