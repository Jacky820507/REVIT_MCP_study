# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from pyrevit import forms, revit, script

import agile_bim_governance as governance
import agile_bim_rule_ui as rule_ui


__title__ = u'牆性能\n分類'
_TITLE = u'牆性能分類'


def _save_report(report):
    if not forms.alert(u'要另存 JSON 牆性能分類報告嗎？', title=_TITLE, yes=True, no=True):
        return
    path = forms.save_file(file_ext='json', default_name='wall-performance-classification-report.json')
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
        [u'牆數', summary['Total']],
        [u'目標', summary['Targets']],
        [u'提案', summary['Proposed']],
        [u'未命中', summary['Unmatched']],
        [u'衝突', summary['Conflicts']],
        [u'阻擋', summary['Blocked']],
        [u'已寫入', summary.get('AppliedChanges', 0)],
        [u'保留既有值', summary.get('SkippedExisting', 0)],
    ], [u'項目', u'數值'], title=u'摘要')
    rows = []
    for plan in report['Walls']:
        rows.append([
            plan['Level'], plan['Type'], plan['Function'], plan['Kind'],
            plan['RoomNames'], plan['InstanceCount'], plan['SourceValue'],
            plan['CurrentValue'], plan['ProposedValue'], plan['Status'],
            plan['Reason'],
        ])
    output.print_table(rows, [u'樓層', u'牆型', u'功能', u'種類', u'邊界房間',
                              u'數量', u'來源值', u'既有值', u'建議值',
                              u'狀態', u'說明'], title=u'牆性能分類提案')


if revit.doc is None:
    forms.alert(u'請先開啟 Revit 專案檔，再執行牆性能分類。',
                title=_TITLE, exitscript=True)

try:
    preset = {
        'targetParameter': u'Wall Performance',
        'targetScope': u'instance',
        'matchField': u'function',
        'mode': u'fill_blank',
        'includeCurtain': False,
        'caseInsensitive': True,
        'collapseWhitespace': True,
        'rules': [
            {'id': u'exterior-wall', 'match': u'Exterior',
             'value': u'WALL-EXT-REVIEW'},
            {'id': u'interior-wall', 'match': u'Interior',
             'value': u'WALL-INT-REVIEW'},
        ],
    }
    config = rule_ui.configure(
        _TITLE,
        preset,
        [
            (u'牆類型名稱（推薦）', u'type'),
            (u'牆功能 Wall Function', u'function'),
            (u'牆種類 Wall Kind', u'kind'),
            (u'邊界房間名稱', u'room_name'),
            (u'邊界房間編號', u'room_number'),
            (u'自訂來源參數', u'parameter'),
        ],
        [
            (u'實例參數（每段牆獨立寫入，推薦）', u'instance'),
            (u'類型參數（同類型共用一個值）', u'type'),
        ],
        extra_option_label=u'包含帷幕牆')
    if config:
        mode = governance._text(config.get('mode')).lower() or u'fill_blank'
        if mode not in (u'fill_blank', u'overwrite'):
            raise ValueError(u'mode 必須是 fill_blank 或 overwrite。')
        records = governance.collect_agile_walls(
            revit.doc,
            level_filter=config.get('level', u''),
            wall_ids=config.get('wallIds'),
            include_curtain=bool(config.get('includeCurtain', False)),
            include_room_relations=config.get('matchField', u'type')
                in (u'room_name', u'room_number'))
        plans = governance.build_wall_performance_preview(records, config)
        report = {
            'Success': True,
            'Applied': False,
            'Mode': mode,
            'TargetParameter': governance._text(config.get('targetParameter')),
            'RuleFile': config.get('_rule_file', u''),
            'RuleSource': config.get('_rule_source', u''),
            'Summary': governance._classification_summary(
                plans, len(records)),
            'Walls': [governance._plan_public(plan, 'wall') for plan in plans],
            'Message': u'牆性能分類 preview 完成；目前沒有修改模型。',
        }
        _print_report(report, _TITLE + u'｜Preview')
        _save_report(report)

        if forms.alert(
                u'Preview 已完成。要依 {0} 寫入牆性能分類嗎？\n\n'
                u'是：執行單一 Transaction；否：只保留報告。'.format(mode),
                title=_TITLE, yes=True, no=True):
            applied, skipped = governance.apply_wall_performance_plans(
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
                'Walls': [governance._plan_public(plan, 'wall') for plan in plans],
                'Message': u'牆性能分類已寫入；請重新查詢模型驗證實際值。',
            }
            _print_report(applied_report, _TITLE + u'｜Apply')
            _save_report(applied_report)
except Exception as ex:
    forms.alert(u'牆性能分類失敗：\n{0}'.format(ex),
                title=_TITLE, exitscript=True)
