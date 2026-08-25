# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""專有共用、面積類型分類 — JAC 04.05.

Method and citations: ``domain/exclusive-shared-area-classification.md``.

Two jobs that look alike and are not:

**專有／共用** is a legal status under 公寓大廈管理條例 §3, and Revit has no
parameter for it — it goes into a project parameter whose name every office
picks differently, so the name and the accepted values are asked at run time
(domain/user-specified-runtime-parameters.md).

**面積類型 (Area Type)** is a Revit built-in that exists **only on the built-in
總建築面積 scheme**. ``AreaScheme.IsGrossBuildingArea`` is how to tell. Looking
for it on a custom scheme finds nothing — that is not missing data, it is a
scheme without the concept, and the button says so rather than reporting a read
failure.

What it will not do:

* **約定專用／約定共用 are never suggested.** Both definitions in §3 contain
  「經約定」; agreement lives in the 規約, not the model.
* **A name that matches nothing becomes 待確認, not 共用.** §3 does make 共用 the
  complement of 專有, but a keyword miss is not evidence — filling it in would
  dress a miss as a finding.
* **Existing values are kept by default.** Someone already decided those, and a
  human's decision outranks a keyword match.
"""

__title__ = u'專有共用\n面積類型'
__author__ = 'RevitMCP'

from Autodesk.Revit import DB
from pyrevit import forms, revit, script

import area_ownership_logic as logic
import area_scheme_sources as sources
import mcp_window as ui
import mcp_window_logic as uilogic


TITLE = u'專有共用、面積類型分類'

OVERWRITE_CHOICES = (
    (u'只填空白，保留已有的值（建議）', False),
    (u'覆寫已有的值', True),
)

SKIP_SCOPE = u'（不寫大公／小公）'


def _parameter_options(doc, schemes, levels):
    """可寫入的文字參數。面積的參數集不隨面積計畫而異，所以取任何一個已放置
    的面積來問即可；一個都沒有時回空清單，由呼叫端擋下。"""
    for scheme in schemes:
        areas = sources.collect_areas(
            doc, scheme_id=sources.id_value(scheme.Id), levels=levels)
        for area in areas:
            element = doc.GetElement(area['element_id'])
            if element is not None:
                return [(label, name) for label, name
                        in sources.readable_parameters(element)]
    return []


def _build_spec(doc, schemes, parameters):
    scheme_options = [(sources.scheme_label(scheme), scheme)
                      for scheme in schemes]
    fields = [
        uilogic.section(u'範圍'),
        uilogic.choice('scheme', u'面積計畫', scheme_options),

        uilogic.section(u'寫入哪些參數',
                        u'專有／共用不是 Revit 內建概念，必須先有一個專案參數。'
                        u'若下拉是空的，請先用「新增 Area 基本參數」建立。'),
        uilogic.choice('parameter', u'專有／共用寫入', parameters),
        uilogic.choice('scope_parameter', u'大公／小公寫入（可略過）',
                       [(SKIP_SCOPE, u'')] + list(parameters),
                       default=u''),

        uilogic.section(u'既有值'),
        uilogic.choice('overwrite', u'已有值的面積怎麼處理', OVERWRITE_CHOICES,
                       default=False,
                       help=u'已經填好的值通常是人做的決定，預設不動它。'),

        uilogic.note(
            u'分類只是**建議**：關鍵字沒命中時會標「待判定」而不是猜成共用。'
            u'「約定專用」「約定共用」永遠不會被自動寫入——那需要住戶規約，'
            u'模型裡沒有這個資訊。', tone='warning'),
    ]
    return uilogic.spec(
        TITLE, fields,
        subtitle=u'依公寓大廈管理條例 §3 的定義分類面積的權屬',
        badge=uilogic.BADGE_WRITE,
        run_label=u'預覽',
        footnote=u'寫入前一定會先預覽並由你確認；失敗時整批回復。',
        width=960, height=740)


def _is_gross_building(scheme):
    try:
        return bool(scheme.IsGrossBuildingArea)
    except Exception:
        return False


def _area_type_text(area):
    parameter = sources.built_in_parameter(area, 'AREA_TYPE_TEXT')
    text = sources.parameter_text(parameter)
    if text:
        return text
    return sources.parameter_text(
        sources.built_in_parameter(area, 'AREA_TYPE'))


def _records(doc, areas, parameter_name):
    records = []
    for row in areas:
        element = doc.GetElement(row['element_id'])
        records.append({
            'id': row['id'],
            'element_id': row['element_id'],
            'number': row.get('number') or u'',
            'name': row.get('name') or u'',
            'level': row.get('level') or u'',
            'current': sources.read_named_parameter(element, parameter_name),
            'area_type': _area_type_text(element),
        })
    return records


def _write(doc, plan, parameter_name, scope_parameter):
    """Single Transaction, all or nothing. Returns ``(count, error)``."""
    transaction = DB.Transaction(doc, TITLE)
    try:
        transaction.Start()
        done = 0
        for item in plan['write']:
            element = doc.GetElement(item['element_id'])
            if element is None:
                raise Exception(u'面積 {} 已不存在。'.format(
                    item.get('number') or item.get('id')))
            parameter = element.LookupParameter(parameter_name)
            if parameter is None or parameter.IsReadOnly:
                raise Exception(u'參數「{}」在面積 {} 上無法寫入。'.format(
                    parameter_name, item.get('number') or item.get('id')))
            parameter.Set(item['suggested'])
            if scope_parameter and item.get('suggested_scope'):
                scope = element.LookupParameter(scope_parameter)
                if scope is not None and not scope.IsReadOnly:
                    scope.Set(item['suggested_scope'])
            done += 1
        transaction.Commit()
        return done, u''
    except Exception as error:
        try:
            if transaction.HasStarted():
                transaction.RollBack()
        except Exception:
            pass
        return 0, u'{}'.format(error)


def _print_plan(plan, scheme_label, parameter_name, gross):
    output = script.get_output()
    output.print_md(u'## {}'.format(TITLE))
    output.print_md(u'面積計畫：**{}**　寫入參數：**{}**'.format(
        scheme_label, parameter_name))
    if not gross:
        output.print_md(
            u'> 這個面積計畫不是內建的「總建築面積」，**沒有 Area Type 這個概念**'
            u'——不是讀不到，是該計畫本來就沒有。本次只處理專有／共用分類。')

    if plan['write']:
        output.print_md(u'### 將寫入（{} 個）'.format(plan['count']))
        output.print_table(
            table_data=[[output.linkify(item['element_id']),
                         item['number'] or u'(無編號)',
                         item['name'] or u'(無名稱)', item['level'],
                         item['current'] or u'(空白)',
                         item['suggested'],
                         item['suggested_scope'] or u'',
                         item['area_type'] or u'',
                         item['reason']]
                        for item in plan['write']],
            columns=[u'Element ID', u'編號', u'名稱', u'樓層', u'原值',
                     u'建議', u'大公/小公', u'Area Type', u'判定理由'])

    if plan['undecided']:
        output.print_md(u'### 需人工判定（{} 個）'.format(
            len(plan['undecided'])))
        output.print_table(
            table_data=[[output.linkify(item['element_id']),
                         item['number'] or u'', item['name'] or u'',
                         item['reason']]
                        for item in plan['undecided']],
            columns=[u'Element ID', u'編號', u'名稱', u'原因'])

    if plan['kept']:
        output.print_md(u'### 保留原值（{} 個）'.format(len(plan['kept'])))
        output.print_table(
            table_data=[[output.linkify(item['element_id']),
                         item['number'] or u'', item['name'] or u'',
                         item['current'], item['suggested']]
                        for item in plan['kept']],
            columns=[u'Element ID', u'編號', u'名稱', u'現值', u'建議值'])

    output.print_md(u'> {}'.format(logic.DISCLAIMER))
    output.print_md(u'依據：`domain/exclusive-shared-area-classification.md`'
                    u'（公寓大廈管理條例 §3）')


def main():
    doc = revit.doc
    if doc is None:
        forms.alert(u'請先開啟 Revit 專案文件，再執行分類。',
                    title=TITLE, exitscript=True)

    schemes = sources.area_schemes(doc)
    if not schemes:
        forms.alert(u'這個專案沒有面積計畫（Area Scheme）。', title=TITLE)
        return
    levels = sources.level_index(doc)
    parameters = _parameter_options(doc, schemes, levels)
    if not parameters:
        forms.alert(u'讀不到任何可寫入的文字參數。\n\n'
                    u'專有／共用不是 Revit 內建概念，需要先建立一個專案參數。',
                    title=TITLE)
        return

    values = ui.ask(_build_spec(doc, schemes, parameters))
    if values is None:
        return

    scheme = values['scheme']
    scheme_label = sources.scheme_label(scheme)
    gross = _is_gross_building(scheme)
    parameter_name = values['parameter']
    scope_parameter = values['scope_parameter']

    areas = sources.collect_areas(doc,
                                  scheme_id=sources.id_value(scheme.Id),
                                  levels=levels)
    if not areas:
        forms.alert(u'「{}」裡沒有已放置的面積。'.format(scheme_label),
                    title=TITLE)
        return

    overwrite = values['overwrite']

    records = _records(doc, areas, parameter_name)
    plan = logic.build_plan(records, overwrite=overwrite)
    _print_plan(plan, scheme_label, parameter_name, gross)
    summary = logic.plan_lines(plan, parameter_name, scope_parameter)

    if not logic.has_work(plan):
        forms.alert(u'【預覽】沒有要寫入的面積，模型未變更。\n\n{}\n\n'
                    u'明細已列在 pyRevit 輸出視窗。'.format(summary),
                    title=TITLE)
        return

    if not forms.alert(
            u'【dry-run 預覽】模型目前未變更。\n\n{}\n\n確定要寫入嗎？'
            .format(summary), title=TITLE, yes=True, no=True):
        return

    done, error = _write(doc, plan, parameter_name, scope_parameter)
    if error:
        forms.alert(u'寫入失敗，交易已完整回復，參數都沒有變更。\n\n{}'.format(
            error), title=TITLE)
        return
    forms.alert(u'已寫入 {} 個面積的「{}」。\n\n{}'.format(
        done, parameter_name, logic.DISCLAIMER), title=TITLE)


try:
    main()
except Exception as error:
    forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
