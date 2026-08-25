# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from pyrevit import forms, revit, script

import agile_bim_governance as governance
import agile_bim_rule_ui as rule_ui


__title__ = u'門規格\n提案'
_TITLE = u'門規格提案'


def _save_report(report):
    if not forms.alert(u'要另存 JSON 門規格報告嗎？', title=_TITLE, yes=True, no=True):
        return
    path = forms.save_file(file_ext='json', default_name='door-specification-report.json')
    if path:
        governance.write_json(path, report)
        forms.alert(u'已輸出：\n{0}'.format(path), title=_TITLE)


def _print_report(report, title):
    output = script.get_output()
    summary = report['Summary']
    output.print_md(u'## {0}'.format(title))
    output.print_md(u'**{0}**'.format(report['Message']))
    output.print_md(u'規則來源：{0}'.format(report.get('RuleSource', u'')))
    output.print_table([
        [u'門數', summary['Total']],
        [u'目標', summary['Targets']],
        [u'提案', summary['Proposed']],
        [u'未命中', summary['Unmatched']],
        [u'衝突', summary['Conflicts']],
        [u'阻擋', summary['Blocked']],
        [u'已寫入', summary.get('AppliedChanges', 0)],
        [u'保留既有值', summary.get('SkippedExisting', 0)],
    ], [u'項目', u'數值'], title=u'摘要')
    rows = []
    for plan in report['Doors']:
        rows.append([
            plan['Level'], plan['Family'], plan['Type'], plan['InstanceCount'],
            plan['SourceValue'], plan['CurrentValue'], plan['ProposedValue'],
            plan['Status'], plan['Reason'],
        ])
    output.print_table(rows, [u'樓層', u'族群', u'類型', u'樘數', u'來源值',
                              u'既有值', u'建議值', u'狀態', u'說明'],
                       title=u'門規格提案')


if revit.doc is None:
    forms.alert(u'請先開啟 Revit 專案檔，再執行門規格提案。',
                title=_TITLE, exitscript=True)

try:
    preset = {
        'targetParameter': u'Door Specification',
        'targetScope': u'type',
        'matchField': u'type',
        'mode': u'fill_blank',
        'includeCurtain': False,
        'caseInsensitive': True,
        'collapseWhitespace': True,
        'rules': [
            {'id': u'interior-door', 'match': u'內門', 'value': u'DOOR-INTERIOR'},
            {'id': u'exterior-door', 'match': u'外門', 'value': u'DOOR-EXTERIOR'},
        ],
    }
    config = rule_ui.configure(
        _TITLE,
        preset,
        [
            (u'類型名稱（推薦）', u'type'),
            (u'族群名稱', u'family'),
            (u'門註記 Mark', u'mark'),
            (u'From Room 名稱', u'from_room_name'),
            (u'To Room 名稱', u'to_room_name'),
            (u'兩側房間名稱', u'room_name'),
            (u'宿主牆類型', u'host_wall_type'),
            (u'自訂來源參數', u'parameter'),
        ],
        [
            (u'類型參數（同類型共用一個值，推薦）', u'type'),
            (u'實例參數（每樘門各自寫入）', u'instance'),
        ],
        extra_option_label=u'包含帷幕牆門')
    if config:
        mode = governance._text(config.get('mode')).lower() or u'fill_blank'
        if mode not in (u'fill_blank', u'overwrite'):
            raise ValueError(u'mode 必須是 fill_blank 或 overwrite。')
        records = governance.collect_agile_openings(
            revit.doc, categories=('doors',),
            level_filter=config.get('level', u''),
            element_ids=config.get('doorIds'),
            include_curtain=bool(config.get('includeCurtain', False)))
        plans = governance.build_door_spec_preview(records, config)
        public_plans = [governance._plan_public(plan, 'door') for plan in plans]
        report = {
            'Success': True,
            'Applied': False,
            'Mode': mode,
            'TargetParameter': governance._text(config.get('targetParameter')),
            'RuleFile': config.get('_rule_file', u''),
            'RuleSource': config.get('_rule_source', u''),
            'Summary': governance._classification_summary(
                plans, len(records)),
            'Doors': public_plans,
            'Message': u'門規格 preview 完成；目前沒有修改模型。',
        }
        _print_report(report, _TITLE + u'｜Preview')
        _save_report(report)

        if forms.alert(
                u'Preview 已完成。要依 {0} 寫入門規格嗎？\n\n'
                u'是：執行單一 Transaction；否：只保留報告。'.format(mode),
                title=_TITLE, yes=True, no=True):
            applied, skipped = governance.apply_door_spec_plans(
                revit.doc, plans, config.get('targetParameter'), mode)
            applied_report = {
                'Success': True,
                'Applied': True,
                'Mode': mode,
                'TargetParameter': governance._text(config.get('targetParameter')),
                'RuleFile': config.get('_rule_file', u''),
                'RuleSource': config.get('_rule_source', u''),
                'Summary': governance._classification_summary(
                    plans, len(records), applied, skipped),
                'Doors': [governance._plan_public(plan, 'door') for plan in plans],
                'Message': u'門規格已寫入；請重新查詢模型驗證實際值。',
            }
            _print_report(applied_report, _TITLE + u'｜Apply')
            _save_report(applied_report)
except Exception as ex:
    forms.alert(u'門規格失敗：\n{0}'.format(ex),
                title=_TITLE, exitscript=True)
