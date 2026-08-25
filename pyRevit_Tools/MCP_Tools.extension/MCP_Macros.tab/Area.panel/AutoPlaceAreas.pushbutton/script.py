# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""面積工具（JAC 01.02）— 健檢與自動放置。

Three modes, ordered by how much they can break:

``健檢``
    Read-only. Classifies every Area as 正常 / 未放置 / 未封閉 / 多餘, using the
    failure definitions Revit itself raises rather than guessing from geometry.

``自動放置``
    Creates Areas (and optionally tags) seeded from existing Rooms. Whether a
    seed actually encloses is answered by placing the areas inside a
    Transaction that always rolls back, so the preview shows Revit's real
    result while the model stays untouched. The commit that follows is
    all-or-nothing.

``API 探測``
    A read-only report. Which API members exist was settled by reflecting over
    ``RevitAPI.dll`` (identical in 2020 and 2024), so this no longer dumps
    ``dir()`` — what is left is the part metadata cannot answer: what the model
    contains and which failure definitions this build actually raises.
"""

__title__ = u'自動放置\n面積'
__author__ = 'RevitMCP'

from Autodesk.Revit import DB
from pyrevit import forms, revit, script
from System.Collections.Generic import List

import area_placement_logic as logic
import area_scheme_sources as sources
import mcp_window as ui
import mcp_window_logic as uilogic


TITLE = u'面積工具'
SQ_FT_TO_SQ_M = 0.09290304

MODE_AUDIT = 'audit'
MODE_PLACE = 'place'
MODE_PROBE = 'probe'

MODES = (
    (u'健檢：檢查既有面積（唯讀，不改模型）', MODE_AUDIT),
    (u'自動放置：依既有房間建立面積與標籤', MODE_PLACE),
    (u'API 探測報告（唯讀，給開發用）', MODE_PROBE),
)

NUMBER_SOURCES = (
    (u'沿用房間編號', logic.NUMBER_FROM_ROOM),
    (u'產生流水號…', logic.NUMBER_SEQUENCE),
    (u'不設定（交給 Revit 自動編號）', logic.NUMBER_NONE),
)

NAME_SOURCES = (
    (u'沿用房間名稱', logic.NAME_FROM_ROOM),
    (u'填入固定文字…', logic.NAME_CONSTANT),
    (u'不設定', logic.NAME_NONE),
)

TAG_CHOICES = (
    (u'同時放置面積標籤', True),
    (u'只建立面積、不放標籤', False),
)


def _build_spec(doc, levels, tag_types):
    """整份規格。回 ``(spec, problem)``。

    原本是 4 個下拉加最多 4 個字串輸入，而且流水號的前綴／起始／補零彼此相關，
    改中間任何一個都得從第一題重來。現在全部同頁，不相干的欄位跟著模式變灰。
    """
    schemes = sources.area_schemes(doc)
    if not schemes:
        return None, u'這個專案沒有面積計畫（Area Scheme）。'
    views = sources.area_plan_views(doc)
    if not views:
        return None, (u'這個專案沒有面積平面圖（Area Plan）。\n\n'
                      u'本按鈕不會代為建立視圖。')

    view_rows = []
    for view in views:
        level_id = sources.view_level_id(view)
        elevation = levels.get(level_id, (u'', 0.0))[1]
        view_rows.append(
            (elevation, sources.view_label(doc, view, levels), view))
    view_rows.sort(key=lambda item: (item[0], item[1]))

    tag_help = (u'' if tag_types
                else u'專案裡沒有載入面積標籤族群，所以這裡是空的。')

    fields = [
        uilogic.section(u'模式'),
        uilogic.choice('mode', u'要做什麼', MODES, default=MODE_AUDIT),
        uilogic.choice('scheme', u'面積計畫',
                       [(sources.scheme_label(scheme), scheme)
                        for scheme in schemes],
                       enabled_when=('mode', (MODE_AUDIT, MODE_PLACE))),
        uilogic.choice('view', u'面積平面圖',
                       [(label, view) for unused, label, view in view_rows],
                       enabled_when=('mode', MODE_PLACE),
                       help=u'必須屬於上面選定的面積計畫；面積平面圖只屬於'
                            u'一個樓層，種子也只取那一層的房間。'),

        uilogic.section(u'編號', u'只有「自動放置」模式會用到。'),
        uilogic.choice('number_source', u'面積編號要填什麼', NUMBER_SOURCES,
                       default=logic.NUMBER_FROM_ROOM,
                       enabled_when=('mode', MODE_PLACE)),
        uilogic.text('prefix', u'流水號前綴（可留空）', default=u'A',
                     enabled_when=('number_source', logic.NUMBER_SEQUENCE)),
        uilogic.number('start', u'起始號碼', default=1, integer=True,
                       enabled_when=('number_source', logic.NUMBER_SEQUENCE)),
        uilogic.number('pad', u'補零位數', default=0, minimum=0, integer=True,
                       enabled_when=('number_source', logic.NUMBER_SEQUENCE),
                       help=u'0 表示不補零；3 會產生 001。'),

        uilogic.section(u'名稱'),
        uilogic.choice('name_source', u'面積名稱要填什麼', NAME_SOURCES,
                       default=logic.NAME_FROM_ROOM,
                       enabled_when=('mode', MODE_PLACE)),
        uilogic.text('constant', u'要填入的固定名稱', default=u'',
                     required=True,
                     enabled_when=('name_source', logic.NAME_CONSTANT)),

        uilogic.section(u'標籤'),
        uilogic.choice('with_tags', u'要放面積標籤嗎', TAG_CHOICES,
                       default=False, enabled_when=('mode', MODE_PLACE)),
        uilogic.choice('tag_type', u'面積標籤類型', list(tag_types),
                       required=False, enabled_when=('with_tags', True),
                       help=tag_help),

        uilogic.note(
            u'放置前會做一次**保證回復的試放**：真的把面積放下去、讓 Revit'
            u'算出面積與邊界，再整批回復，所以預覽數字來自 Revit 本身而不是'
            u'用邏輯猜的。正式放置是全有全無——任何一筆失敗就整批回復，'
            u'模型不會留下半成品面積。', tone='info'),
    ]
    return uilogic.spec(
        TITLE, fields,
        subtitle=u'由既有房間帶入種子點，自動放置面積與標籤',
        badge=uilogic.BADGE_WRITE,
        run_label=u'執行',
        footnote=u'「唯讀健檢」與「API 探測」不會動到模型。',
        width=1000, height=840), u''


def _print_audit(report, scheme_label):
    output = script.get_output()
    output.print_md(u'## {} — 健檢：{}'.format(TITLE, scheme_label))
    if not report['rows']:
        output.print_md(u'這個面積計畫底下沒有面積。')
        return
    rows = []
    for row in report['rows']:
        warnings = u'；'.join(
            entry.get('label', u'') for entry in row.get('warnings') or [])
        rows.append([
            output.linkify(row['element_id']),
            row['status'],
            row['level'],
            row['number'],
            row['name'],
            u'{:.2f}'.format(row['area_sqft'] * SQ_FT_TO_SQ_M),
            warnings,
        ])
    output.print_table(
        table_data=rows,
        columns=[u'Element ID', u'狀態', u'樓層', u'編號', u'名稱',
                 u'面積(m²)', u'Revit 警告'])


def run_audit(doc, scheme, levels):
    scheme_id = sources.id_value(scheme.Id)
    areas = sources.collect_areas(doc, scheme_id=scheme_id, levels=levels)
    if not areas:
        forms.alert(u'這個面積計畫底下沒有面積。', title=TITLE)
        return
    warnings = sources.warning_flags(
        doc, area_ids=set(item['id'] for item in areas))
    report = logic.build_audit(areas, warnings)
    _print_audit(report, sources.scheme_label(scheme))
    summary = logic.audit_lines(report)
    if not report['flagged_ids']:
        forms.alert(u'{}\n\n明細已列在 pyRevit 輸出視窗。'.format(summary),
                    title=TITLE)
        return
    if forms.alert(
            u'{}\n\n明細已列在 pyRevit 輸出視窗。\n'
            u'要把有問題的面積選取起來嗎？'.format(summary),
            title=TITLE, yes=True, no=True):
        ids = List[DB.ElementId]()
        for value in report['flagged_ids']:
            ids.Add(DB.ElementId(int(value)))
        revit.uidoc.Selection.SetElementIds(ids)


# --- placement -------------------------------------------------------------

def _print_plan(plan, scheme_label, view_label):
    output = script.get_output()
    output.print_md(u'## {} — 自動放置：{}'.format(TITLE, scheme_label))
    output.print_md(u'面積平面：**{}**'.format(view_label))
    rows = plan.get('writes') if plan.get('trialled') else plan.get('creates')
    if rows:
        output.print_table(
            table_data=[[
                output.linkify(row['element_id']),
                row.get('room_number', u''),
                row.get('room_name', u''),
                row.get('number', u'') or u'(自動)',
                row.get('name', u''),
                u'{:.2f}'.format(
                    float(row.get('area_sqft') or 0.0) * SQ_FT_TO_SQ_M),
                row.get('note', u''),
            ] for row in rows],
            columns=[u'來源房間 ID', u'房號', u'房名', u'面積編號',
                     u'面積名稱', u'試放面積(m²)', u'備註'])
    else:
        output.print_md(u'沒有要建立的面積。')
    if plan.get('blocked'):
        output.print_md(u'### 阻擋不建（{} 筆）'.format(len(plan['blocked'])))
        output.print_table(
            table_data=[[
                output.linkify(row['record']['element_id']),
                row['record'].get('room_number', u''),
                row['record'].get('room_name', u''),
                row['reason'],
            ] for row in plan['blocked']],
            columns=[u'來源房間 ID', u'房號', u'房名', u'原因'])


def run_place(doc, scheme, view, levels, values):
    scheme_id = sources.id_value(scheme.Id)
    view_level = sources.view_level_id(view)

    # An area plan belongs to one level, so seeding from any other level would
    # place areas the view cannot show.
    rooms = sources.rooms_for_level(doc, level_id=view_level, levels=levels)
    if not rooms:
        forms.alert(
            u'這個面積平面圖對應的樓層底下沒有房間。\n\n'
            u'目前的種子來源是「既有房間」，所以該樓層必須先有房間。',
            title=TITLE)
        return

    number_source = values['number_source']
    options = {}
    if number_source == logic.NUMBER_SEQUENCE:
        options = {'prefix': (values['prefix'] or u'').strip(),
                   'start': values['start'],
                   'pad': max(0, values['pad'])}

    name_source = values['name_source']
    if name_source == logic.NAME_CONSTANT:
        options['constant'] = (values['constant'] or u'').strip()

    tag_type_id = None
    if values['with_tags']:
        tag_type_id = values.get('tag_type')
        if tag_type_id is None:
            forms.alert(
                u'專案裡沒有載入任何面積標籤族群，無法放置標籤。\n\n'
                u'請先載入面積標籤族群，或改選「只建立面積、不放標籤」。',
                title=TITLE)
            return

    existing = sources.collect_areas(doc, scheme_id=scheme_id, levels=levels)
    plan = logic.build_plan(rooms, existing, number_source=number_source,
                            name_source=name_source, options=options)
    scheme_label = sources.scheme_label(scheme)
    label = sources.view_label(doc, view, levels)

    if not plan['creates']:
        _print_plan(plan, scheme_label, label)
        forms.alert(
            u'【預覽】沒有要建立的面積，模型未變更。\n\n{}\n\n'
            u'明細已列在 pyRevit 輸出視窗。'.format(
                logic.plan_lines(plan, scheme_label, label)),
            title=TITLE)
        return

    # Ask Revit whether these seeds actually enclose, then undo the experiment.
    trial = sources.trial_place(doc, view, plan['creates'])
    plan = logic.apply_trial_result(plan, trial)
    _print_plan(plan, scheme_label, label)
    summary = logic.plan_lines(plan, scheme_label, label)

    if not plan['writes']:
        forms.alert(
            u'【dry-run 預覽】沒有可建立的面積，模型未變更。\n\n{}\n\n'
            u'明細已列在 pyRevit 輸出視窗。'.format(summary), title=TITLE)
        return

    if logic.sequence_is_gapped(plan):
        forms.alert(
            u'【dry-run 預覽】\n\n{}\n\n'
            u'流水號模式有被阻擋的項目，寫下去會跳號。\n'
            u'本次不提供套用；請先處理輸出視窗列出的原因。'.format(summary),
            title=TITLE)
        return

    if not forms.alert(
            u'【dry-run 預覽】試放已完成並回復，模型目前未變更。\n\n{}\n\n'
            u'明細已列在 pyRevit 輸出視窗。\n'
            u'確定要正式建立這些面積嗎？'.format(summary),
            title=TITLE, yes=True, no=True):
        return

    created, tagged, error = sources.place_areas(
        doc, view, plan['writes'], tag_type_id)
    if error:
        forms.alert(
            u'建立失敗，交易已完整回復，模型沒有留下半成品面積。\n\n{}'
            .format(error), title=TITLE)
        return
    tail = u'，並放置 {} 個標籤'.format(tagged) if tag_type_id else u''
    forms.alert(u'已建立 {} 個面積{}。'.format(created, tail), title=TITLE)


# --- probe -----------------------------------------------------------------

def _probe_value(getter, missing=u'(取不到)'):
    try:
        return getter()
    except Exception as error:
        return u'{}：{}'.format(missing, error)


def run_probe(doc):
    output = script.get_output()
    output.print_md(u'# {} — 行為探測報告'.format(TITLE))
    output.print_md(
        u'唯讀查詢，未建立或修改任何元素。'
        u'API 成員是否存在已由 RevitAPI.dll metadata 確認（2020 與 2024 一致），'
        u'此處只驗證 metadata answer 不了的行為面。')

    app = _probe_value(lambda: doc.Application)
    output.print_table(
        table_data=[
            [u'Revit 版本', u'{}'.format(
                _probe_value(lambda: app.VersionNumber))],
            [u'Revit build', u'{}'.format(
                _probe_value(lambda: app.VersionBuild))],
            [u'文件標題', u'{}'.format(_probe_value(lambda: doc.Title))],
        ],
        columns=[u'項目', u'值'])

    output.print_md(u'### 面積計畫')
    schemes = sources.area_schemes(doc)
    if not schemes:
        output.print_md(u'（沒有面積計畫）')
    else:
        output.print_table(
            table_data=[[
                u'{}'.format(sources.id_value(scheme.Id)),
                sources.element_name(scheme),
                u'{}'.format(_probe_value(
                    lambda s=scheme: s.IsGrossBuildingArea)),
            ] for scheme in schemes],
            columns=[u'Id', u'名稱', u'IsGrossBuildingArea'])

    output.print_md(u'### 面積平面圖')
    views = sources.area_plan_views(doc)
    levels = sources.level_index(doc)
    if not views:
        output.print_md(u'（沒有面積平面圖）')
    else:
        output.print_table(
            table_data=[[
                u'{}'.format(sources.id_value(view.Id)),
                sources.element_name(view),
                u'{}'.format(sources.view_area_scheme_id(view)),
                levels.get(sources.view_level_id(view), (u'', 0.0))[0],
            ] for view in views],
            columns=[u'View Id', u'名稱', u'SchemeId', u'樓層'])

    output.print_md(u'### 既有面積')
    areas = sources.collect_areas(doc, levels=levels)
    output.print_md(u'共 {} 個。'.format(len(areas)))
    if areas:
        output.print_table(
            table_data=[[
                u'{}'.format(item['id']), item['number'], item['name'],
                u'{}'.format(item['placed']),
                u'{:.2f}'.format(item['area_sqft'] * SQ_FT_TO_SQ_M),
                u'{}'.format(len(item['loops'])),
            ] for item in areas[:40]],
            columns=[u'Id', u'編號', u'名稱', u'已放置', u'面積(m²)',
                     u'邊界迴圈數'])

    output.print_md(u'### 面積相關警告')
    flags = sources.warning_flags(doc)
    if not flags:
        output.print_md(
            u'（沒有牽涉面積的警告。要驗證「多餘面積」的分類，'
            u'請手動製造一個再跑一次）')
    else:
        rows = []
        for area_id in sorted(flags):
            for entry in flags[area_id]:
                rows.append([u'{}'.format(area_id), entry['kind'],
                             entry['label'], entry['text'][:60]])
        output.print_table(
            table_data=rows[:40],
            columns=[u'Area Id', u'kind', u'分類', u'Revit 描述'])

    output.print_md(u'### 面積標籤類型')
    tag_types = sources.area_tag_types(doc)
    output.print_md(u'可用標籤類型 {} 個：{}'.format(
        len(tag_types),
        u'、'.join(label for label, unused in tag_types[:10]) or u'（無）'))


def main():
    doc = revit.doc
    if doc is None:
        forms.alert(u'請先開啟 Revit 專案文件，再執行面積工具。',
                    title=TITLE, exitscript=True)

    levels = sources.level_index(doc)
    tag_types = sources.area_tag_types(doc)
    spec, problem = _build_spec(doc, levels, tag_types)
    if spec is None:
        forms.alert(problem, title=TITLE)
        return

    values = ui.ask(spec)
    if values is None:
        return

    mode = values['mode']
    if mode == MODE_PROBE:
        run_probe(doc)
        forms.alert(u'探測報告已列在 pyRevit 輸出視窗。', title=TITLE)
        return

    scheme = values['scheme']
    if mode == MODE_AUDIT:
        run_audit(doc, scheme, levels)
        return

    view = values['view']
    scheme_id = sources.id_value(scheme.Id)
    if sources.view_area_scheme_id(view) != scheme_id:
        forms.alert(
            u'選定的面積平面圖不屬於「{}」這個面積計畫。\n\n'
            u'請改選同一計畫底下的平面圖。'.format(
                sources.scheme_label(scheme)), title=TITLE)
        return
    run_place(doc, scheme, view, levels, values)


try:
    main()
except Exception as error:
    forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
