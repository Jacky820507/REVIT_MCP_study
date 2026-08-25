# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""區域線重新生成（JAC 01.05）.

Two modes over one idea of "the same line":

``依房間邊界生成``
    Redraw the area plan's boundary lines from the room boundaries Revit
    already computes, so the area plan stops drifting from the architecture
    every time a wall moves.

``清理重複區域線``
    Collapse boundary lines lying on top of each other — the thing that raises
    「面積邊界線重疊」 and accumulates because nothing stops you drawing the
    same line twice.

Both write, so both go dry-run → confirm → one Transaction that rolls back
completely. Deleting is offered but never implied: clearing the existing lines
is an explicit choice, and the preview says how many would go.
"""

__title__ = u'區域線\n重新生成'
__author__ = 'RevitMCP'

from pyrevit import forms, revit, script

import area_boundary_regen_logic as logic
import area_scheme_sources as sources
import link_level_logic as link_levels
import mcp_window as ui
import mcp_window_logic as uilogic
import wall_boundary_logic as walls


TITLE = u'區域線重新生成'

MODE_ROOMS = 'rooms'
MODE_WALLS = 'walls'
MODE_DEDUP = 'dedup'

MODES = (
    (u'依房間邊界生成區域線', MODE_ROOMS),
    (u'依牆生成區域線（牆心／核心／牆面）', MODE_WALLS),
    (u'清理重複的區域線（唯一動作是刪除重複）', MODE_DEDUP),
)

# 04.08 is the centreline; 04.09 is the core / face pair.
WALL_MODES = (
    (walls.MODE_LABELS[walls.MODE_CENTRE], walls.MODE_CENTRE),
    (walls.MODE_LABELS[walls.MODE_CORE], walls.MODE_CORE),
    (walls.MODE_LABELS[walls.MODE_FACE], walls.MODE_FACE),
)

WALL_SOURCES = (
    (u'目前模型的牆（預設）', 'host'),
    (u'連結模型的牆（JAC 04.10）', 'link'),
)

ROOM_SCOPES = (
    (u'這一層全部房間（預設）', 'all'),
    (u'目前選取的房間', 'selection'),
    (u'從清單複選房間', 'pick'),
)

CLEAR_CHOICES = (
    (u'保留既有區域線，只補上缺的（建議）', False),
    (u'先刪除既有區域線再重畫（整個重來）', True),
)


def _build_spec(doc, levels):
    """主視窗。回 ``(spec, problem)``；``spec`` 為 ``None`` 時 problem 是原因。

    三種模式的欄位都放在同一頁，用 enabled_when 跟著模式亮暗。真正相依而必須
    另開視窗的只有兩件事：房間範圍要先讀完邊界才知道有哪些房間，連結樓層要先
    知道是哪個連結——其餘全部一次問完。
    """
    views = sources.area_plan_views(doc)
    if not views:
        return None, (u'這個專案沒有面積平面圖（Area Plan）。@@NL@@@@NL@@'
                      u'區域線只能畫在面積平面圖上，本按鈕不會代為建立視圖。')
    view_rows = []
    for view in views:
        level_id = sources.view_level_id(view)
        elevation = levels.get(level_id, (u'', 0.0))[1]
        view_rows.append(
            (elevation, sources.view_label(doc, view, levels), view))
    view_rows.sort(key=lambda item: (item[0], item[1]))

    links = sources.link_instances(doc)

    fields = [
        uilogic.section(u'模式與去處'),
        uilogic.choice('mode', u'要做什麼', MODES, default=MODE_ROOMS),
        uilogic.choice('view', u'面積平面圖',
                       [(label, view) for unused, label, view in view_rows]),

        uilogic.section(u'依房間', u'以既有房間的邊界為來源。'),
        uilogic.choice('location', u'區域線要畫在牆的哪個位置',
                       list(sources.BOUNDARY_LOCATIONS),
                       enabled_when=('mode', MODE_ROOMS)),
        uilogic.choice('room_scope', u'要轉哪些房間', ROOM_SCOPES,
                       default='all', enabled_when=('mode', MODE_ROOMS),
                       help=u'選「指定房間」時，下一步會列出這一層每個房間'
                            u'實際貢獻幾段邊界。'),

        uilogic.section(u'依牆'),
        uilogic.choice('wall_mode', u'區域線要畫在牆的哪個位置', WALL_MODES,
                       default=walls.MODE_CENTRE,
                       enabled_when=('mode', MODE_WALLS)),
        uilogic.choice('wall_source', u'牆要從哪裡抓', WALL_SOURCES,
                       default='host', enabled_when=('mode', MODE_WALLS)),
        uilogic.choice('link', u'連結模型', list(links),
                       required=False,
                       enabled_when=('wall_source', 'link'),
                       help=u'未載入的連結讀不到內容，不會出現在這裡。'
                           if links else u'這個專案沒有已載入的 Revit 連結。'),

        uilogic.section(u'既有區域線'),
        uilogic.choice('clear', u'既有的區域線怎麼處理', CLEAR_CHOICES,
                       default=False,
                       enabled_when=('mode', (MODE_ROOMS, MODE_WALLS))),
    ]
    return uilogic.spec(
        TITLE, fields,
        subtitle=u'由房間、牆或連結模型的牆產生面積邊界線',
        badge=uilogic.BADGE_WRITE,
        run_label=u'下一步',
        footnote=u'寫入前一定會先預覽並由你確認；單一交易，全有全無。',
        width=1000, height=820), u''


def _build_room_spec(room_curves):
    """房間範圍要先讀完邊界才列得出來，所以是第二個視窗。"""
    options = []
    for item in sorted(logic.room_summary(room_curves),
                       key=logic.room_sort_key):
        options.append((u'{}　{}　（{} 段邊界）'.format(
            item.get('room_number') or u'(無編號)',
            item.get('room_name') or u'(無名稱)',
            item['segments']), item['room_id']))
    fields = [
        uilogic.section(u'房間'),
        uilogic.multichoice('rooms', u'要轉成區域線的房間（可複選）',
                            options, required=True),
    ]
    return uilogic.spec(
        TITLE, fields, subtitle=u'選擇房間',
        badge=uilogic.BADGE_WRITE, run_label=u'預覽',
        width=880, height=680)


def _build_link_level_spec(levels, proposed, quality, delta):
    """連結樓層要先知道是哪個連結才列得出來，所以是第二個視窗。"""
    options = []
    for level in link_levels.sorted_levels(levels):
        mark = u''
        if proposed is not None and level['id'] == proposed['id']:
            mark = u'　←　{}'.format(quality)
        options.append((u'{}{}'.format(link_levels.level_label(level), mark),
                        level))
    fields = [uilogic.section(u'連結模型的樓層')]
    warning = link_levels.match_warning(quality, delta)
    if warning:
        fields.append(uilogic.note(warning, tone='warning'))
    fields.append(uilogic.choice(
        'level', u'要抓哪一層的牆', options,
        default=proposed,
        help=u'連結樓層與目前模型的樓層是不同的元素，名稱與高程都不保證一致，'
             u'所以這裡只是**建議**最接近的那一層。'))
    return uilogic.spec(
        TITLE, fields, subtitle=u'選擇連結模型的樓層',
        badge=uilogic.BADGE_WRITE, run_label=u'預覽',
        width=820, height=560)


def _room_ids(doc, scope, room_curves):
    """``None`` 代表全部房間；``[]`` 代表停止。"""
    if scope == 'all':
        return None

    available = set(item['room_id']
                    for item in logic.room_summary(room_curves))

    if scope == 'selection':
        chosen = [value for value in _selected_room_ids(doc)
                  if value in available]
        if not chosen:
            forms.alert(
                u'目前選取的元素裡沒有這一層的房間。\n\n'
                u'請先在平面圖上選取房間，或改用其他範圍。', title=TITLE)
            return []
        return chosen

    picked = ui.ask(_build_room_spec(room_curves))
    if picked is None:
        return []
    return list(picked['rooms'])


def _selected_room_ids(doc):
    """Room ids in the current selection, ignoring anything that is not one."""
    builtin = getattr(DB.BuiltInCategory, 'OST_Rooms', None)
    if builtin is None:
        return []
    try:
        ids = list(revit.uidoc.Selection.GetElementIds())
    except Exception:
        return []
    found = []
    for element_id in ids:
        try:
            element = doc.GetElement(element_id)
            category = element.Category if element is not None else None
            if category is None:
                continue
            if sources.id_value(category.Id) != int(builtin):
                continue
        except Exception:
            continue
        found.append(sources.id_value(element.Id))
    return found


def _link_wall_records(instance, view_elevation_mm):
    """連結模型的牆，已轉到目前模型的座標。``None`` 表示中止。

    連結的樓層是它自己的元素：連結的「3FL」不必然與目前模型的 3FL 同高程，
    因此只**建議**最接近者並由人確認。把某一層的牆畫到另一層，在平面圖上完全
    看不出來，但產生的面積是錯的。
    """
    try:
        link_doc = instance.GetLinkDocument()
    except Exception:
        link_doc = None
    if link_doc is None:
        forms.alert(u'這個連結目前讀不到內容。', title=TITLE)
        return None

    levels = sources.link_levels(link_doc)
    if not levels:
        forms.alert(link_levels.match_warning(link_levels.MATCH_NONE),
                    title=TITLE)
        return None

    proposed, quality, delta = link_levels.match_level(view_elevation_mm,
                                                       levels)
    picked = ui.ask(_build_link_level_spec(levels, proposed, quality, delta))
    if picked is None:
        return None
    chosen = picked['level']
    if chosen is None:
        return None

    records = sources.collect_link_walls(instance, level_id=chosen['id'])
    if not records:
        forms.alert(u'連結模型的「{}」層沒有牆。'.format(chosen['name']),
                    title=TITLE)
        return None
    return records


def main():
    doc = revit.doc
    if doc is None:
        forms.alert(u'請先開啟 Revit 專案文件，再執行區域線重新生成。',
                    title=TITLE, exitscript=True)

    levels = sources.level_index(doc)
    spec, problem = _build_spec(doc, levels)
    if spec is None:
        forms.alert(problem, title=TITLE)
        return
    values = ui.ask(spec)
    if values is None:
        return

    mode = values['mode']
    view = values['view']
    view_label = sources.view_label(doc, view, levels)
    level_id = sources.view_level_id(view)
    existing = sources.collect_boundary_lines(doc, view)

    location_label = u''
    if mode == MODE_ROOMS:
        if level_id <= 0:
            forms.alert(
                u'這個面積平面圖讀不到對應樓層，無法決定要抓哪一層的房間。',
                title=TITLE)
            return
        location_name = values['location']
        location_label = uilogic.label_for_value(
            sources.BOUNDARY_LOCATIONS, location_name)
        clear_existing = values['clear']
        room_curves = sources.room_boundary_curves(
            doc, level_id=level_id, location_name=location_name)
        if not room_curves:
            forms.alert(
                u'這個樓層沒有房間，或房間都沒有邊界。\n\n'
                u'本模式以既有房間的邊界為來源，該樓層必須先有房間。',
                title=TITLE)
            return
        # 房間範圍在讀完邊界之後才問，這樣清單才能顯示每個房間實際貢獻
        # 幾段邊界。
        room_ids = _room_ids(doc, values['room_scope'], room_curves)
        if room_ids is not None and not room_ids:
            return
        room_curves = logic.filter_rooms(room_curves, room_ids)
        if room_ids is not None:
            location_label = u'{}（限 {} 個房間）'.format(
                location_label, len(room_ids))
        plan = logic.plan_from_rooms(room_curves, existing,
                                     clear_existing=clear_existing)
    elif mode == MODE_WALLS:
        if level_id <= 0:
            forms.alert(
                u'這個面積平面圖讀不到對應樓層，無法決定要抓哪一層的牆。',
                title=TITLE)
            return
        wall_mode = values['wall_mode']
        location_label = walls.MODE_LABELS[wall_mode]
        clear_existing = values['clear']
        wall_source = values['wall_source']
        if wall_source == 'link':
            instance = values.get('link')
            if instance is None:
                forms.alert(
                    u'這個專案沒有已載入的 Revit 連結。\n\n'
                    u'（未載入的連結讀不到內容，因此不會列出。）', title=TITLE)
                return
            elevation = levels.get(level_id, (u'', None))[1]
            wall_records = _link_wall_records(instance, elevation)
            if wall_records is None:
                return
            location_label = u'{}（連結模型）'.format(location_label)
        else:
            wall_records = sources.collect_walls(doc, level_id=level_id)
            if not wall_records:
                forms.alert(u'這個樓層沒有牆。', title=TITLE)
                return
        wall_plan = walls.build_plan(wall_records, wall_mode)
        curves = _wall_curves(wall_plan)
        if not curves:
            forms.alert(
                u'{}\n\n沒有可用的牆可以產生區域線。'.format(
                    walls.plan_lines(wall_plan)), title=TITLE)
            return
        plan = logic.plan_from_rooms(curves, existing,
                                     clear_existing=clear_existing)
        plan['wall_plan'] = wall_plan
    else:
        if not existing:
            forms.alert(u'這個面積平面圖沒有區域線。', title=TITLE)
            return
        plan = logic.plan_dedup(existing)

    _print_plan(plan, view_label)
    summary = logic.plan_summary(plan, view_label, location_label)
    if plan.get('wall_plan'):
        # The wall pass has its own reasons for skipping walls (curtain,
        # stacked, no core); they belong in the summary or the counts do not
        # add up against the walls on that floor.
        summary = u'{}\n\n{}'.format(walls.plan_lines(plan['wall_plan']),
                                     summary)

    if not logic.has_work(plan):
        forms.alert(u'【預覽】沒有需要變更的區域線，模型未變更。\n\n{}\n\n'
                    u'明細已列在 pyRevit 輸出視窗。'.format(summary),
                    title=TITLE)
        return

    removals = logic.delete_ids(plan)
    warning = u''
    if removals:
        warning = u'\n注意：這次會刪除 {} 條既有區域線。\n'.format(len(removals))
    if not forms.alert(
            u'【dry-run 預覽】模型目前未變更。\n\n{}\n{}\n'
            u'明細已列在 pyRevit 輸出視窗。\n'
            u'確定要寫入嗎？'.format(summary, warning),
            title=TITLE, yes=True, no=True):
        return

    drawn, deleted, error = sources.regenerate_boundary_lines(
        doc, view, level_id, plan['draws'], removals)
    if error:
        forms.alert(
            u'執行失敗，交易已完整回復，區域線維持原狀。\n\n{}'.format(error),
            title=TITLE)
        return
    forms.alert(u'已新增 {} 條區域線、刪除 {} 條。'.format(drawn, deleted),
                title=TITLE)


try:
    main()
except Exception as error:
    forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
