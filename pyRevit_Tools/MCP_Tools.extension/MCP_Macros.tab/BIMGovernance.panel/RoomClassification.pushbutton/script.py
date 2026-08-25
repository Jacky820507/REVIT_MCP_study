# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from pyrevit import forms, revit, script

import agile_bim_governance as governance
import agile_bim_rule_ui as rule_ui


__title__ = u'房間分類\n規則'
_TITLE = u'房間分類規則'


def _print_report(report, title):
    output = script.get_output()
    output.print_md(u'## {0}'.format(title))
    output.print_md(u'**{0}**'.format(report.get('Message', u'')))
    output.print_md(u'規則來源：{0}'.format(report.get('RuleSource', u'')))
    summary = report['Summary']
    output.print_table([
        [u'房間總數', summary['TotalRooms']],
        [u'提案', summary['Proposed']],
        [u'未命中', summary['Unmatched']],
        [u'衝突', summary['Conflicts']],
        [u'阻擋', summary['Blocked']],
        [u'已寫入', summary.get('AppliedChanges', 0)],
        [u'保留既有值', summary.get('SkippedExisting', 0)],
    ], [u'項目', u'數值'], title=u'摘要')
    rows = []
    for plan in report['Rooms']:
        rows.append([
            plan['Level'], plan['Number'], plan['Name'],
            plan['SourceValue'], plan['CurrentValue'], plan['ProposedValue'],
            plan['Status'], plan['Reason'],
        ])
    output.print_table(rows,
                       [u'樓層', u'編號', u'名稱', u'來源值', u'既有值', u'建議值', u'狀態', u'說明'],
                       title=u'房間分類提案')


def _save_report(report):
    if not forms.alert(u'要另存 JSON 分類報告嗎？', title=_TITLE, yes=True, no=True):
        return
    path = forms.save_file(file_ext='json', default_name='room-classification-report.json')
    if path:
        governance.write_json(path, report)
        forms.alert(u'已輸出：\n{0}'.format(path), title=_TITLE)


if revit.doc is None:
    forms.alert(u'請先開啟 Revit 專案檔，再執行房間分類規則。',
                title=_TITLE, exitscript=True)

try:
    preset = {
        'targetParameter': u'Room Classification',
        'matchField': u'name',
        'mode': u'fill_blank',
        'includeUnplaced': False,
        'caseInsensitive': True,
        'collapseWhitespace': True,
        'rules': [
            {'id': u'office', 'match': u'辦公', 'value': u'OFFICE'},
            {'id': u'corridor', 'match': u'走廊', 'value': u'CIRCULATION'},
        ],
    }
    config = rule_ui.configure(
        _TITLE,
        preset,
        [
            (u'房間名稱（推薦）', u'name'),
            (u'房間編號', u'number'),
            (u'房間部門', u'department'),
            (u'自訂來源參數', u'parameter'),
        ],
        extra_option_label=u'包含尚未放置的房間')
    if config:
        mode = governance._text(config.get('mode')).lower() or u'fill_blank'
        if mode not in (u'fill_blank', u'overwrite'):
            raise ValueError(u'mode 必須是 fill_blank 或 overwrite。')
        rooms = governance.collect_rooms(
            revit.doc, include_unplaced=bool(config.get('includeUnplaced', False)))
        plans = governance.build_preview(rooms, config, revit.doc)
        report = {
            'Success': True,
            'Applied': False,
            'Mode': mode,
            'TargetParameter': governance._text(config.get('targetParameter')),
            'RuleFile': config.get('_rule_file', u''),
            'RuleSource': config.get('_rule_source', u''),
            'Summary': governance.public_summary(plans, total_rooms=len(rooms)),
            'Rooms': plans,
            'Message': u'房間分類 preview 完成；目前沒有修改模型。',
        }
        _print_report(report, _TITLE + u'｜Preview')
        _save_report(report)

        if forms.alert(
                u'Preview 已完成。要依 {0} 寫入分類嗎？\n\n'
                u'是：執行單一 Transaction；否：只保留報告。'.format(mode),
                title=_TITLE, yes=True, no=True):
            applied, skipped = governance.apply_plans(
                revit.doc, rooms, plans,
                config.get('targetParameter'), mode)
            applied_report = {
                'Success': True,
                'Applied': True,
                'Mode': mode,
                'TargetParameter': governance._text(config.get('targetParameter')),
                'RuleFile': config.get('_rule_file', u''),
                'RuleSource': config.get('_rule_source', u''),
                'Summary': governance.public_summary(
                    plans, total_rooms=len(rooms), applied=applied, skipped=skipped),
                'Rooms': plans,
                'Message': u'房間分類已寫入；請重新查詢模型驗證實際值。',
            }
            _print_report(applied_report, _TITLE + u'｜Apply')
            _save_report(applied_report)
except Exception as ex:
    forms.alert(u'房間分類失敗：\n{0}'.format(ex),
                title=_TITLE, exitscript=True)
