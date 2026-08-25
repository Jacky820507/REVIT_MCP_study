# -*- coding: utf-8 -*-
__title__ = u'空間表\nExcel'
import os
import re
import shutil
from collections import Counter

from pyrevit import forms, revit, script
import mcp_bridge as mcp
import room_takeoff_sources
import room_takeoff_sources_logic
import takeoff_direct_publish
import takeoff_entry

from System import Type, Activator, GC
from System.Runtime.InteropServices import Marshal

XL_UP = -4162
XL_PASTE_FORMATS = -4122
XL_NONE = -4142
XL_BORDER_EDGES = (7, 8, 9, 10)
DIFF_TOL = 0.005
FUZZY_TOL = 0.05      # bootstrap 名稱+數值匹配的周長/面積容差 (m / ㎡)
REMOVED_PREFIX = u'【已拆除】'
RID_HEADER = u'RevitId'
TOOL_TITLE = u'空間表 Excel'
TARGET_SPACE_SHEET = u'01空間表'
_MCP_EMBEDDED_RESULT = globals().get('_MCP_EMBEDDED_RESULT')
_TAKEOFF_OPTIONS = globals().get('_TAKEOFF_OPTIONS')


class _EmbeddedSpaceTableReady(Exception):
    """Return control to a calling pyRevit button when no Excel write is needed."""
    pass

try:
    STRING_TYPES = basestring  # IronPython 2.7
except NameError:
    STRING_TYPES = str

STATUS_LABEL = {
    'ok': u'一致',
    'idfill': u'一致(回填Id)',
    'idfilled': u'一致(已回填Id)',
    'update': u'需更新',
    'updated': u'已更新',
    'insert': u'新房間(插列)',
    'inserted': u'新房間(已插列)',
    'manual_append': u'新房間(表尾,需人工)',
    'appended': u'新房間(已附加表尾)',
    'move': u'需搬移排序',
    'moved': u'已搬移排序',
    'delete_row': u'已拆除(整列刪除)',
    'deleted_row': u'已拆除(已刪列)',
    'mark_zero': u'已拆除(保留標記:有殘留引用)',
    'marked_zero': u'已拆除(已標記:有殘留引用)',
    'unresolved': u'待人工裁決(不寫入)',
    'dup_rid': u'RevitId重複(跳過)',
    'out_of_scope': u'本次範圍外(保留)',
    'source_conflict': u'來源衝突(不寫入)',
}

MANUAL_CLEAR_COLS = {
    u'踢腳': list(range(5, 10)),
    u'內牆': list(range(11, 15)),
    u'地坪': list(range(4, 15)),
    u'天花': list(range(4, 15)),
}


def _excel_open(path, read_only):
    xl_type = Type.GetTypeFromProgID('Excel.Application')
    if xl_type is None:
        raise Exception(u'找不到 Excel（COM）。此功能需要本機安裝 Excel。')
    excel = Activator.CreateInstance(xl_type)
    excel.Visible = False
    excel.DisplayAlerts = False
    wb = excel.Workbooks.Open(path, 0, read_only)
    return excel, wb


def _excel_close(excel, wb, save):
    try:
        if wb is not None:
            try:
                if save:
                    wb.Save()
                wb.Close(False)
            finally:
                try:
                    Marshal.FinalReleaseComObject(wb)
                except Exception:
                    try:
                        Marshal.ReleaseComObject(wb)
                    except Exception:
                        pass
    finally:
        if excel is not None:
            try:
                excel.Quit()
            except Exception:
                pass
            try:
                Marshal.FinalReleaseComObject(excel)
            except Exception:
                try:
                    Marshal.ReleaseComObject(excel)
                except Exception:
                    pass
        try:
            GC.Collect()
            GC.WaitForPendingFinalizers()
            GC.Collect()
            GC.WaitForPendingFinalizers()
        except Exception:
            pass


def _split_number(num):
    number = room_takeoff_sources_logic.normalize_room_number(num)
    m = re.match(u'^(.*?)(\\d+)$', number)
    if not m:
        return (number, None)
    return (m.group(1), int(m.group(2)))


def _find_columns(ws):
    """以欄名唯一定位表頭；RevitId 不存在時建議新欄位置。"""
    targets = {u'房間編號': 'number', u'房間名稱': 'name',
               u'周長': 'perimeter', u'面積': 'area',
               RID_HEADER: 'rid'}
    used = ws.UsedRange
    first_row = max(1, int(used.Row))
    last_row = first_row + max(1, int(used.Rows.Count)) - 1
    first_col = max(1, int(used.Column))
    last_col = first_col + max(1, int(used.Columns.Count)) - 1
    candidates = []
    for r in range(first_row, last_row + 1):
        found = {}
        for c in range(first_col, last_col + 1):
            value = ws.Cells(r, c).Value2
            text = u'{}'.format(value) if value is not None else u''
            if not text:
                continue
            for key, field in targets.items():
                if field not in found and key in text:
                    found[field] = c
        if all(f in found for f in
               ('number', 'name', 'perimeter', 'area')):
            candidates.append((r, found))
    if len(candidates) != 1:
        raise Exception(
            u'「01空間表」必須有且只有一列同時包含房間編號、房間名稱、'
            u'周長、面積；目前找到 {} 列，禁止用預設列號猜測。'.format(
                len(candidates)))
    header_row, cols = candidates[0]
    rid_new = 'rid' not in cols
    if rid_new:
        # 找 header 與前幾列資料皆空的欄當 RevitId 欄（預期 F 欄）
        for c in range(max(cols.values()) + 1, 21):
            if all(not ws.Cells(r, c).Text
                   for r in range(header_row, header_row + 6)):
                cols['rid'] = c
                break
        else:
            cols['rid'] = 20
    return header_row, cols, rid_new


def _space_entries_signature(entries):
    """Workbook identity without transient row numbers."""
    return tuple(sorted(
        (u'{}'.format(item.get('rid') or u''),
         u'{}'.format(item.get('number') or u''),
         u'{}'.format(item.get('name') or u''),
         item.get('perimeter'), item.get('area'))
        for item in entries or []))


def _read_space_table(ws, header_row, cols):
    last_row = ws.Cells(ws.Rows.Count, cols['number']).End(XL_UP).Row
    entries = []
    for r in range(header_row + 1, last_row + 1):
        number = (ws.Cells(r, cols['number']).Text or u'').strip()
        if not number:
            continue
        peri = ws.Cells(r, cols['perimeter']).Value2
        area = ws.Cells(r, cols['area']).Value2
        rid_value = ws.Cells(r, cols['rid']).Value2
        rid = (u'{}'.format(rid_value)
               if rid_value is not None else u'').strip()
        entries.append({
            'row': r, 'number': number,
            'name': (ws.Cells(r, cols['name']).Text or u'').strip(),
            'perimeter': float(peri) if isinstance(peri, (int, float)) else None,
            'area': float(area) if isinstance(area, (int, float)) else None,
            'rid': rid})
    return entries, last_row


def _sheet_by_trim(wb, requested):
    wanted = u'{}'.format(requested or u'').strip()
    for ws in wb.Worksheets:
        if u'{}'.format(ws.Name or u'').strip() == wanted:
            return ws
    raise Exception(u'Excel 找不到必要分頁「{}」。'.format(requested))


def _standalone_default_name(doc):
    title = u'{}'.format(getattr(doc, 'Title', u'空間表')).strip()
    title = re.sub(r'[\\/:*?"<>|]+', u'_', title) or u'空間表'
    return title + u'_空間表.xlsx'


def _write_space_standalone(data):
    path = forms.save_file(
        file_ext='xlsx',
        default_name=_standalone_default_name(revit.doc),
        title=u'匯出空間表 Excel',
    )
    if not path:
        return None
    if not path.lower().endswith('.xlsx'):
        path += '.xlsx'
    import takeoff_standalone
    payload = room_takeoff_sources.space_standalone_tables(
        data.get('Rooms') or [], data.get('SkippedRooms') or [])
    takeoff_standalone.write_standard_workbook(
        path,
        payload['detail_rows'], payload['detail_headers'],
        payload['formula_rows'], payload['formula_headers'],
        payload['audit_rows'], payload['audit_headers'],
        TOOL_TITLE,
    )
    return path


def _scan_ref_sheets(wb, target):
    pat = re.compile(u"^='?" + re.escape(target) +
                     u"'?!\\$?([A-H])\\$?(\\d+)$")
    result = {}
    for ws in wb.Worksheets:
        if ws.Name == target:
            continue
        used = ws.UsedRange
        last = used.Row + used.Rows.Count - 1
        if last < 2:
            continue
        arr = ws.Range(ws.Cells(1, 1), ws.Cells(last, 8)).Formula
        rows_map = {}
        for r in range(1, last + 1):
            refs, space_row = [], None
            for c in range(1, 9):
                f = arr.GetValue(r, c)
                if not isinstance(f, STRING_TYPES):
                    continue
                m = pat.match(f)
                if m:
                    refs.append((c, m.group(1)))
                    if m.group(1) == 'B':
                        space_row = int(m.group(2))
            if space_row is not None:
                rows_map[space_row] = {'row': r, 'refs': refs}
        if rows_map:
            result[ws.Name] = rows_map
    return result


def _num_diff(old, new):
    if old is None:
        return True
    return abs(round(new, 2) - round(old, 2)) >= DIFF_TOL


def _close_t(old, new, tol):
    return old is not None and abs(round(new, 2) - round(old, 2)) <= tol


def _close(old, new):
    return _close_t(old, new, FUZZY_TOL)


def _fmt_change(old, new, changed):
    if not changed:
        return u'{:.2f}'.format(new) if isinstance(new, float) else (new or u'')
    if isinstance(new, float):
        old_s = u'{:.2f}'.format(old) if old is not None else u'(空)'
        return u'**{} → {:.2f}**'.format(old_s, new)
    return u'**{} → {}**'.format(old or u'(空)', new)


def _match(entries, revit_rooms, allow_bootstrap=True):
    """三階段身份匹配。回傳 (bound, excel_left, revit_left, dup_rids)
    bound = [(entry, room, basis)]"""
    rooms, dup_rids, seen_rid = [], [], set()
    for rm in revit_rooms:
        identity = rm.get('CompositeId') or rm.get('ElementId')
        rid = u'{}'.format(identity) if identity else None
        num = (rm.get('Number') or u'').strip()
        if not rid or not num:
            continue
        if rid in seen_rid:
            dup_rids.append(rid)
            continue
        seen_rid.add(rid)
        rooms.append({'rid': rid, 'number': num,
                      'source_key': (rm.get('SourceKey') or u'').strip(),
                      'local_element_id': (
                          rm.get('LocalElementId') or rm.get('ElementId')),
                      'name': (rm.get('Name') or u'').strip(),
                      'perimeter': round(float(rm.get('PerimeterM') or 0), 2),
                      'area': round(float(rm.get('AreaM2') or 0), 2),
                      'level': rm.get('Level'),
                      'boundary_loop_count': int(rm.get('BoundaryLoopCount') or 0),
                      'boundary_segment_count': int(rm.get('BoundarySegmentCount') or 0)})
    bound, used_e, used_r = [], set(), set()
    revit_rids = set(rm['rid'] for rm in rooms)
    # Phase A：RevitId（穩定身份，重編號免疫）
    for rm in rooms:
        es = [
            entry for entry in entries
            if room_takeoff_sources_logic.exact_room_identity_matches(
                entry.get('rid'), rm.get('source_key'),
                rm.get('local_element_id'), rm.get('rid'))
        ]
        if es and len(es) == 1 and id(es[0]) not in used_e:
            bound.append((es[0], rm, u'Id'))
            used_e.add(id(es[0]))
            used_r.add(rm['rid'])

    if not allow_bootstrap:
        excel_left = [e for e in entries if id(e) not in used_e]
        revit_left = [rm for rm in rooms if rm['rid'] not in used_r]
        return bound, excel_left, revit_left, dup_rids

    def _rebindable(e):
        # 無 Id（首次），或 Id 已不存在於 Revit（房間曾刪除重建）
        return (not e['rid']) or (e['rid'] not in revit_rids)

    # Phase B：編號＋名稱皆一致（首次 bootstrap 或刪除重建）
    by_num = {}
    for e in entries:
        if _rebindable(e) and id(e) not in used_e:
            by_num.setdefault(e['number'], []).append(e)
    for rm in rooms:
        if rm['rid'] in used_r:
            continue
        es = by_num.get(rm['number'])
        if es and len(es) == 1 and id(es[0]) not in used_e and \
                es[0]['name'] == rm['name']:
            bound.append((es[0], rm, u'編號+名稱'))
            used_e.add(id(es[0]))
            used_r.add(rm['rid'])
    # Phase C：名稱＋數值近似（先嚴後寬兩段容差，處理重編號後的身份追蹤；
    # 嚴格段可分開兩間同名但面積僅差 0.01 的房間，例如梯廳）
    for tol in (DIFF_TOL, FUZZY_TOL):
        for rm in rooms:
            if rm['rid'] in used_r:
                continue
            cands = [e for e in entries
                     if _rebindable(e) and id(e) not in used_e and
                     e['name'] == rm['name'] and
                     _close_t(e['perimeter'], rm['perimeter'], tol) and
                     _close_t(e['area'], rm['area'], tol)]
            if len(cands) == 1:
                bound.append((cands[0], rm, u'名稱+數值'))
                used_e.add(id(cands[0]))
                used_r.add(rm['rid'])
    # Phase D：名稱唯一（雙邊皆只剩一筆同名時綁定——
    # 容許「重編號＋幾何同時改變」的房間，如吸收鄰室後面積大改）
    left_names = Counter(rm['name'] for rm in rooms
                         if rm['rid'] not in used_r)
    for rm in rooms:
        if rm['rid'] in used_r or left_names[rm['name']] != 1:
            continue
        cands = [e for e in entries
                 if _rebindable(e) and id(e) not in used_e and
                 e['name'] == rm['name']]
        if len(cands) == 1:
            bound.append((cands[0], rm, u'名稱唯一'))
            used_e.add(id(cands[0]))
            used_r.add(rm['rid'])
    excel_left = [e for e in entries if id(e) not in used_e]
    revit_left = [rm for rm in rooms if rm['rid'] not in used_r]
    return bound, excel_left, revit_left, dup_rids


def _pick_anchor(number, final_rows, planned):
    prefix, n = _split_number(number)
    if n is None:
        return ('tail', None)
    pred, pred_n, succ, succ_n = None, None, None, None
    for other in list(final_rows.keys()) + list(planned):
        op, on = _split_number(other)
        if op != prefix or on is None or other == number:
            continue
        if on < n and (pred_n is None or on > pred_n):
            pred, pred_n = other, on
        if (on > n and other in final_rows and
                (succ_n is None or on < succ_n)):
            succ, succ_n = other, on
    if pred is not None:
        return ('after', pred)
    if succ is not None:
        return ('before', succ)
    return ('tail', None)


def _plan(entries, revit_rooms, allow_removals=True, allow_bootstrap=True):
    bound, excel_left, revit_left, dup_rids = _match(
        entries, revit_rooms, allow_bootstrap=allow_bootstrap)
    items = []
    for rid in dup_rids:
        items.append({'number': rid, 'status': 'dup_rid'})

    for e, rm, basis in bound:
        d_number = rm['number'] != e['number']
        d_name = rm['name'] != e['name']
        d_peri = _num_diff(e['perimeter'], rm['perimeter'])
        d_area = _num_diff(e['area'], rm['area'])
        need_rid = e['rid'] != rm['rid']
        if d_number or d_name or d_peri or d_area:
            status = 'update'
        elif need_rid:
            status = 'idfill'
        else:
            status = 'ok'
        items.append({
            'entry': e, 'status': status, 'basis': basis,
            'rid': rm['rid'], 'need_rid': need_rid,
            'identity_migration': (
                room_takeoff_sources_logic.is_host_identity_migration(
                    e.get('rid'), rm['rid'])),
            'number': rm['number'], 'old_number': e['number'],
            'd_number': d_number,
            'name': rm['name'], 'old_name': e['name'], 'd_name': d_name,
            'perimeter': rm['perimeter'], 'old_perimeter': e['perimeter'],
            'd_peri': d_peri,
            'area': rm['area'], 'old_area': e['area'], 'd_area': d_area})

    still_e, still_r = list(excel_left), []
    if not allow_bootstrap:
        conflict_numbers = (
            room_takeoff_sources_logic.source_conflict_numbers(
                still_e, revit_left))
        for rm in revit_left:
            if (room_takeoff_sources_logic.normalize_room_number(
                    rm['number']) in conflict_numbers):
                items.append({
                    'entry': None,
                    'status': 'source_conflict',
                    'basis': u'房號已被本次範圍外的 Excel 列占用',
                    'number': rm['number'],
                    'name': rm['name'],
                    'rid': rm['rid'],
                    'level': rm['level'],
                    'perimeter': rm['perimeter'],
                    'area': rm['area'],
                })
            else:
                still_r.append(rm)
    else:
        # 疑似「改名＋重編」同時發生：數值吻合但名稱不同 → 不寫入，待人工
        for rm in revit_left:
            twin = None
            for e in still_e:
                if (_close(e['perimeter'], rm['perimeter'])
                        and _close(e['area'], rm['area'])):
                    twin = e
                    break
            if twin is None:
                still_r.append(rm)
                continue
            still_e.remove(twin)
            items.append({
                'entry': twin, 'status': 'unresolved',
                'basis': u'數值吻合',
                'number': rm['number'], 'old_number': twin['number'],
                'name': rm['name'], 'old_name': twin['name'],
                'perimeter': rm['perimeter'], 'area': rm['area'],
                'rid': rm['rid']})

    item_by_entry = dict(
        (id(i.get('entry')), i)
        for i in items
        if i.get('entry') is not None and i['status'] not in (
            'unresolved', 'out_of_scope'))
    moves = room_takeoff_sources_logic.plan_space_row_moves(
        entries,
        [i.get('entry') for i in item_by_entry.values()])
    for move in moves:
        item = item_by_entry.get(id(move['entry']))
        if item is None:
            continue
        item['needs_move'] = True
        item['move_before_entry'] = move.get('before')
        item['move_anchor_entry'] = move.get('anchor')
        item['move_from_row'] = item['entry'].get('row')
        if item['status'] == 'ok':
            item['status'] = 'move'

    # 全新房間：插列
    final_rows = room_takeoff_sources_logic.space_insert_anchor_rows(
        entries, items)
    planned = set()
    for rm in sorted(
            still_r,
            key=lambda r: room_takeoff_sources_logic.room_number_sort_key(
                r['number'])):
        mode, anchor = _pick_anchor(rm['number'], final_rows, planned)
        planned.add(rm['number'])
        items.append({
            'entry': None, 'status': 'insert' if mode != 'tail'
            else 'manual_append',
            'basis': u'—', 'mode': mode, 'anchor': anchor,
            'rid': rm['rid'], 'level': rm['level'],
            'number': rm['number'], 'name': rm['name'],
            'perimeter': rm['perimeter'], 'area': rm['area']})

    # 已拆除：整列刪除（含先前留下的【已拆除】墓碑列；
    # 套用時若偵測到其他儲存格殘留引用，該列退回保留標記防 #REF!）
    for e in still_e:
        items.append({
            'entry': e,
            'status': (
                room_takeoff_sources_logic.unmatched_workbook_status(
                    allow_removals)),
            'basis': u'—', 'number': e['number'], 'name': e['name']})
    return items


def _note_text(i):
    st = i['status']
    parts = []
    if i.get('identity_migration'):
        parts.append(
            u'一次性識別遷移：RevitId {} → {}（加入 host 來源）'.format(
                i.get('entry', {}).get('rid') or u'空白',
                i.get('rid') or u''))
    if st in ('update', 'updated') and i.get('d_number'):
        parts.append(u'重編號 {}→{}（列位不動，下游手填資料跟著房間走）'.format(
            i['old_number'], i['number']))
    if st in ('insert', 'inserted'):
        pos = (u'插在 {} 之後'.format(i['anchor']) if i['mode'] == 'after'
               else u'插在 {} 之前'.format(i['anchor']))
        if i.get('sheet_rows'):
            sheets = u'；'.join(u'{} 列{}'.format(s, r)
                                for s, r, flag in i['sheet_rows'])
            flags = [s for s, r, flag in i['sheet_rows'] if flag]
            if flags:
                sheets += u'（{} 鄰分節邊界，小計範圍請抽查）'.format(
                    u'、'.join(flags))
            parts.append(u'{}；連動：{}'.format(pos, sheets))
        else:
            parts.append(u'{}；連動分頁於套用時插列'.format(pos))
    if st in ('manual_append', 'appended'):
        parts.append(u'同前綴無鄰居→附加表尾，下游分頁請人工補列')
    if i.get('needs_move') or st in ('move', 'moved'):
        anchor = i.get('move_anchor_entry') or {}
        before = i.get('move_before_entry') or {}
        if anchor.get('number'):
            parts.append(u'搬到 {} 後方，恢復同前綴房號排序'.format(
                anchor.get('number')))
        elif before.get('number'):
            parts.append(u'搬到 {} 前方，恢復同前綴房號排序'.format(
                before.get('number')))
        else:
            parts.append(u'搬移到同前綴房號排序位置')
        if i.get('move_from_row'):
            parts.append(u'原列 {}'.format(i.get('move_from_row')))
    if st in ('delete_row', 'deleted_row'):
        if i.get('deleted_sheets'):
            parts.append(u'空間表整列刪除；下游連動刪：{}'.format(
                u'；'.join(u'{} 列{}~{}'.format(s, a, b)
                           for s, a, b in i['deleted_sheets'])))
        else:
            parts.append(u'空間表與下游對應列整列刪除，其餘列引用自動上移')
        if i.get('repaired'):
            parts.append(u'序號公式已修復：{}'.format(
                u'、'.join(i['repaired'])))
    if st in ('mark_zero', 'marked_zero'):
        parts.append(u'偵測到其他儲存格仍引用該列（{}），改保留標記防 #REF!：'
                     u'編號加註(拆)＋名稱加註{}＋歸零'.format(
                         i.get('stray_at') or u'?', REMOVED_PREFIX))
    if st == 'unresolved':
        parts.append(u'疑似改名+重編（Excel {} {} ↔ Revit {} {}），'
                     u'請人工確認後再處理'.format(
                         i['old_number'], i['old_name'],
                         i['number'], i['name']))
    if st == 'out_of_scope':
        parts.append(u'本次只同步部分來源／樓層，未匹配列保留且不歸零')
    if st == 'source_conflict':
        parts.append(
            u'同房號已由本次範圍外的 Excel 列占用；不覆寫也不插入重複列')
    return u'；'.join(parts)


def _print_detail(items, title):
    out = script.get_output()
    out.print_md(u'### {}'.format(title))
    out.print_md(u'| 房間編號 | 房間名稱 | 周長(M) | 面積(㎡) | 狀態 | 匹配依據 | 備註/連動 |')
    out.print_md(u'|---|---|---|---|---|---|---|')
    for i in items:
        st = i['status']
        if (st == 'ok' or
                (st in ('idfill', 'idfilled') and
                 not i.get('identity_migration'))):
            continue  # 一致與純 Id 回填不佔版面，見摘要計數
        num_s = i['number']
        if i.get('d_number'):
            num_s = u'**{} → {}**'.format(i['old_number'], i['number'])
        if st in ('update', 'updated'):
            name_s = _fmt_change(i['old_name'], i['name'], i['d_name'])
            peri_s = _fmt_change(i['old_perimeter'], i['perimeter'], i['d_peri'])
            area_s = _fmt_change(i['old_area'], i['area'], i['d_area'])
        elif st in (
                'insert', 'inserted', 'manual_append', 'appended',
                'source_conflict'):
            name_s = u'{}（樓層: {}）'.format(i.get('name') or u'',
                                             i.get('level') or u'?')
            peri_s = u'{:.2f}'.format(i['perimeter'])
            area_s = u'{:.2f}'.format(i['area'])
        elif st in ('move', 'moved'):
            name_s = i.get('name') or u''
            peri_s = area_s = u'—'
        elif st in ('delete_row', 'deleted_row'):
            name_s = i['name']
            peri_s = area_s = u'刪除'
        elif st in ('mark_zero', 'marked_zero'):
            name_s = u'{} → {}{}'.format(i['name'], REMOVED_PREFIX, i['name'])
            peri_s = area_s = u'→ 0'
        elif st == 'unresolved':
            name_s = u'{} ↔ {}'.format(i['old_name'], i['name'])
            peri_s = u'{:.2f}'.format(i['perimeter'])
            area_s = u'{:.2f}'.format(i['area'])
        else:
            name_s = i.get('name') or u''
            peri_s = area_s = u'—'
        out.print_md(u'| {} | {} | {} | {} | {} | {} | {} |'.format(
            num_s, name_s, peri_s, area_s,
            STATUS_LABEL.get(st, st), i.get('basis') or u'—',
            _note_text(i)))


def _summary(items):
    c = Counter(i['status'] for i in items)
    renum = sum(1 for i in items if i.get('d_number'))
    idfill = (c.get('idfill', 0) + c.get('idfilled', 0) +
              sum(1 for i in items
                  if i.get('need_rid') and i['status'] in
                  ('update', 'updated')))
    identity_migrations = sum(
        1 for i in items if i.get('identity_migration'))
    moved = (c.get('move', 0) + c.get('moved', 0) +
             sum(1 for i in items
                 if i.get('needs_move') and i['status'] in (
                     'update', 'updated', 'idfill', 'idfilled')))
    lines = [u'一致 {}、需更新 {}（其中重編號 {}）、需搬移排序 {}、新房間插列 {}、'
             u'表尾附加 {}、拆除刪列 {}、拆除保留標記 {}、待人工 {}、'
             u'範圍外保留 {}、來源衝突 {}、Id回填 {}'.format(
                 c.get('ok', 0),
                 c.get('update', 0) + c.get('updated', 0), renum,
                 moved,
                 c.get('insert', 0) + c.get('inserted', 0),
                 c.get('manual_append', 0) + c.get('appended', 0),
                 c.get('delete_row', 0) + c.get('deleted_row', 0),
                 c.get('mark_zero', 0) + c.get('marked_zero', 0),
                 c.get('unresolved', 0), c.get('out_of_scope', 0),
                 c.get('source_conflict', 0), idfill)]
    if c.get('unresolved'):
        lines.append(u'⚠ 有 {} 筆疑似「改名+重編」不會寫入，'
                     u'請先到輸出視窗逐筆確認。'.format(c['unresolved']))
    if c.get('source_conflict'):
        lines.append(
            u'⚠ 有 {} 筆選取來源房號與範圍外 Excel 列衝突，'
            u'不會覆寫或插入；請人工決定來源歸屬。'.format(
                c['source_conflict']))
    if identity_migrations:
        lines.append(
            u'ℹ {} 筆舊 bare RevitId 將一次性遷移為 host:<ElementId>。'.format(
                identity_migrations))
    shown = [i for i in items if i['status'] in
              ('update', 'move', 'insert', 'manual_append', 'delete_row',
              'mark_zero', 'unresolved', 'out_of_scope',
              'source_conflict')][:10]
    for i in shown:
        st = i['status']
        if st == 'update':
            parts = []
            if i['d_number']:
                parts.append(u'編號{}→{}'.format(i['old_number'], i['number']))
            if i['d_name']:
                parts.append(u'名稱→{}'.format(i['name']))
            if i['d_peri']:
                parts.append(u'周長→{:.2f}'.format(i['perimeter']))
            if i['d_area']:
                parts.append(u'面積→{:.2f}'.format(i['area']))
            lines.append(u'  {} {}'.format(i['old_number'], u'；'.join(parts)))
        else:
            lines.append(u'  {} {}'.format(i['number'],
                                           STATUS_LABEL.get(st, st)))
    return u'\n'.join(lines)


def _print_boundary_summary(data, revit_rooms):
    params = data.get('Parameters') or {}
    skipped = data.get('SkippedRooms') or []
    multi = sum(1 for rm in revit_rooms
                if int(rm.get('BoundaryLoopCount') or 0) > 1)
    no_boundary = sum(1 for rm in skipped
                      if u'boundary' in u' '.join(rm.get('Warnings') or []).lower())
    boundary_location = params.get('BoundaryLocation') or u'Finish'
    out = script.get_output()
    out.print_md(
        u'- 周長來源：`GetBoundarySegments({})`，已加總所有 boundary loops；'
        u'多重邊界房間 {}，無邊界房間 {}'.format(
            boundary_location, multi, no_boundary))


def _is_detail_row(ws, r):
    for c in range(1, 4):
        if ws.Cells(r, c).Value2 not in (None, u''):
            return False
    for c in range(4, 15):
        if ws.Cells(r, c).Value2 not in (None, u''):
            return True
    return False


def _col_letter(c):
    if c <= 26:
        return chr(64 + c)
    return chr(64 + (c - 1) // 26) + chr(65 + (c - 1) % 26)


def _repair_bare_ref(ws, row, repaired, sheet_name):
    """刪列後，緊接列的裸 #REF!（如遞增序號 =#REF!+1）重指向上一列同欄。
    帶分頁前綴的舊傷（='01空間表'!#REF!）不動。"""
    for c in range(1, 21):
        f = ws.Cells(row, c).Formula
        if isinstance(f, STRING_TYPES) and u'#REF!' in f:
            fixed = re.sub(u'(?<!!)#REF!',
                           u'{}{}'.format(_col_letter(c), row - 1), f)
            if fixed != f:
                ws.Cells(row, c).Formula = fixed
                repaired.append(u'{} {}{}'.format(
                    sheet_name, _col_letter(c), row))


def _block_rows(ws, main_row):
    """房間區塊 = 主列＋其下連續的開口明細列。回傳 (首列, 尾列)。"""
    end = main_row
    while _is_detail_row(ws, end + 1):
        end += 1
    return main_row, end


def _find_stray_ref(wb, target, space_row, allowed):
    """全簿掃描是否有 allowed 之外的儲存格公式引用空間表該列。
    含嵌在運算式中的引用（如 =C6-'01空間表'!E14）。
    回傳第一個殘留位置描述，無則 None。"""
    pat = re.compile(u"'?" + re.escape(target) +
                     u"'?!\\$?[A-Z]{1,2}\\$?" + str(space_row) +
                     u"(?!\\d)")
    for ws in wb.Worksheets:
        used = ws.UsedRange
        last_r = used.Row + used.Rows.Count - 1
        last_c = used.Column + used.Columns.Count - 1
        if last_r < 1:
            continue
        arr = ws.Range(ws.Cells(1, 1), ws.Cells(last_r, last_c)).Formula
        ok_rows = allowed.get(ws.Name, ())
        single = (last_r == 1 and last_c == 1)
        for r in range(1, last_r + 1):
            if ok_rows and ok_rows[0] <= r <= ok_rows[1]:
                continue
            for c in range(1, last_c + 1):
                f = arr if single else arr.GetValue(r, c)
                if isinstance(f, STRING_TYPES) and pat.search(f):
                    return u'{} 第{}列'.format(ws.Name, r)
    return None


def _shift_rows(entries, ref_maps, pos, tail):
    """空間表插列後的簿記位移。回傳新 tail。"""
    for e in entries:
        if e['row'] >= pos:
            e['row'] += 1
    for name in ref_maps:
        ref_maps[name] = dict(
            (sr + 1 if sr >= pos else sr, v)
            for sr, v in ref_maps[name].items())
    return tail + 1 if tail >= pos else pos


def _row_has_complete_borders(ws, row, first_col, last_col):
    for col in range(first_col, last_col + 1):
        cell = ws.Cells(row, col)
        for edge in XL_BORDER_EDGES:
            try:
                line_style = cell.Borders.Item(edge).LineStyle
            except Exception:
                return False
            if line_style in (None, XL_NONE):
                return False
    return True


def _copy_row_formats(ws, excel, source_row, target_row,
                      first_col, last_col):
    source = ws.Range(
        ws.Cells(source_row, first_col),
        ws.Cells(source_row, last_col))
    target = ws.Range(
        ws.Cells(target_row, first_col),
        ws.Cells(target_row, last_col))
    source.Copy()
    target.PasteSpecial(XL_PASTE_FORMATS)
    excel.CutCopyMode = False
    try:
        ws.Rows(target_row).RowHeight = ws.Rows(source_row).RowHeight
    except Exception:
        pass


def _incomplete_border_rows(ws, entries, first_col, last_col):
    return [
        int(entry['row']) for entry in entries
        if entry.get('rid') and not _row_has_complete_borders(
            ws, int(entry['row']), first_col, last_col)
    ]


def _repair_space_row_formats(ws, excel, entries,
                              first_col, last_col):
    repaired = []
    rows = sorted(set(
        int(entry['row']) for entry in entries
        if entry.get('row') is not None and entry.get('rid')))
    template_rows = sorted(set(
        int(entry['row']) for entry in entries
        if entry.get('row') is not None))
    for row in rows:
        if _row_has_complete_borders(
                ws, row, first_col, last_col):
            continue
        template = None
        for candidate in sorted(template_rows, key=lambda value: (
                abs(value - row), value)):
            if candidate == row:
                continue
            if _row_has_complete_borders(
                    ws, candidate, first_col, last_col):
                template = candidate
                break
        if template is None:
            continue
        _copy_row_formats(
            ws, excel, template, row, first_col, last_col)
        repaired.append(row)
    return repaired


def _move_ref_map_keys(ref_maps, source_row, dest_row):
    for name in ref_maps:
        updated = {}
        for space_row, value in ref_maps[name].items():
            if space_row == source_row:
                updated[dest_row] = value
            elif source_row > dest_row and dest_row <= space_row < source_row:
                updated[space_row + 1] = value
            elif source_row < dest_row and source_row < space_row <= dest_row:
                updated[space_row - 1] = value
            else:
                updated[space_row] = value
        ref_maps[name] = updated


def _move_entry_rows(entries, ref_maps, source_row, dest_row):
    if source_row == dest_row:
        return
    for entry in entries:
        row = entry.get('row')
        if row == source_row:
            entry['row'] = dest_row
        elif source_row > dest_row and dest_row <= row < source_row:
            entry['row'] = row + 1
        elif source_row < dest_row and source_row < row <= dest_row:
            entry['row'] = row - 1
    _move_ref_map_keys(ref_maps, source_row, dest_row)


def _move_space_row(ws, excel, entries, ref_maps, item):
    entry = item.get('entry')
    before_entry = item.get('move_before_entry')
    if entry is None or before_entry is None:
        return False
    source_row = int(entry['row'])
    dest_row = int(before_entry['row'])
    if source_row == dest_row or source_row == dest_row - 1:
        return False
    if source_row < dest_row:
        dest_row -= 1
    ws.Rows(source_row).Cut()
    ws.Rows(dest_row).Insert()
    excel.CutCopyMode = False
    _move_entry_rows(entries, ref_maps, source_row, dest_row)
    item['move_to_row'] = dest_row
    return True


def _insert_downstream(wb, excel, target, ref_maps, anchor_srow, new_srow,
                       before_mode):
    results = []
    for sheet_name in sorted(ref_maps):
        rows_map = ref_maps[sheet_name]
        if anchor_srow not in rows_map:
            continue
        ws = wb.Worksheets.Item(sheet_name)
        tmpl = rows_map[anchor_srow]
        tmpl_row = tmpl['row']
        if before_mode:
            ins = tmpl_row
        else:
            ins = tmpl_row + 1
            while _is_detail_row(ws, ins):
                ins += 1
        next_rows = [v['row'] for v in rows_map.values() if v['row'] >= ins]
        boundary = (not next_rows) or (min(next_rows) != ins)
        ws.Rows(tmpl_row).Copy()
        ws.Rows(ins).Insert()
        excel.CutCopyMode = False
        for col_idx, space_col in tmpl['refs']:
            ws.Cells(ins, col_idx).Formula = u"='{}'!{}{}".format(
                target, space_col, new_srow)
        clear_cols = MANUAL_CLEAR_COLS.get(sheet_name)
        if clear_cols:
            ref_cols = set(c for c, _ in tmpl['refs'])
            for c in clear_cols:
                if c not in ref_cols:
                    ws.Cells(ins, c).ClearContents()
        else:
            boundary = True
        for v in rows_map.values():
            if v['row'] >= ins:
                v['row'] += 1
        rows_map[new_srow] = {'row': ins, 'refs': list(tmpl['refs'])}
        results.append((sheet_name, ins, sheet_name if boundary else None))
    return results


try:
    # 1. 共用入口是唯一的來源／樓層／主檔選擇。
    if revit.doc is None:
        forms.alert(u'請先開啟 Revit 專案文件。', title=TOOL_TITLE)
        script.exit()
    entry_options = _TAKEOFF_OPTIONS
    if entry_options is None:
        entry_options = takeoff_entry.choose_options(
            revit.doc, TOOL_TITLE, allow_host=True, host_required=False)
    if not entry_options:
        script.exit()

    # 2. 逐來源直接讀 Revit 房間；ElementId 一律加上來源 key。
    data = room_takeoff_sources.collect_selected_rooms(
        revit.doc, entry_options)
    revit_rooms = data.get('Rooms') or []
    if not revit_rooms:
        forms.alert(
            u'選取的模型／樓層中沒有已放置且有面積的房間。',
            title=TOOL_TITLE, exitscript=True)
    _print_boundary_summary(data, revit_rooms)

    xls_path = entry_options.get('workbook_path')
    if not xls_path:
        if _MCP_EMBEDDED_RESULT is not None:
            _MCP_EMBEDDED_RESULT.update({
                'path': None,
                'sheet': None,
                'backup': None,
                'updated': False,
                'data': data,
            })
            raise _EmbeddedSpaceTableReady()
        standalone_path = _write_space_standalone(data)
        if standalone_path:
            forms.alert(
                u'空間表 Excel 已匯出：\n\n{}'.format(standalone_path),
                title=TOOL_TITLE)
        script.exit()

    duplicate_numbers = room_takeoff_sources_logic.duplicate_room_numbers(
        revit_rooms)
    if duplicate_numbers:
        detail = u'\n'.join(
            u'{}：{}'.format(number, u'、'.join(identities))
            for number, identities in sorted(duplicate_numbers.items()))
        raise Exception(
            u'主檔「01空間表」以房號對應資料，但選取來源含重複房號；'
            u'為避免固定列誤寫，本次已停止。\n\n{}'.format(detail))

    # 3. 唯讀開啟指定的 01空間表，讀資料與全簿引用。
    excel = wb = None
    try:
        excel, wb = _excel_open(xls_path, True)
        ws = _sheet_by_trim(wb, TARGET_SPACE_SHEET)
        target = ws.Name
        header_row, cols, rid_new = _find_columns(ws)
        entries, last_row = _read_space_table(ws, header_row, cols)
        preview_entries_signature = _space_entries_signature(entries)
        ref_maps = _scan_ref_sheets(wb, target)
        visible_last_col = max(
            1, cols['number'], cols['name'],
            cols['perimeter'], cols['area'])
        layout_issues = {
            'rid_visible': not bool(ws.Columns(cols['rid']).Hidden),
            'border_rows': _incomplete_border_rows(
                ws, entries, 1, visible_last_col),
        }
    finally:
        _excel_close(excel, wb, False)
    if not entries:
        forms.alert(u'分頁「{}」讀不到房間資料列。'.format(target),
                    title=TOOL_TITLE, exitscript=True)

    # 4. 三階段身份匹配 → dry-run 驗證表
    full_host_contract = (
        room_takeoff_sources_logic.destructive_space_sync_allowed(
            entry_options)
        and room_takeoff_sources_logic.workbook_is_host_only(entries))
    items = _plan(
        entries,
        revit_rooms,
        allow_removals=full_host_contract,
        allow_bootstrap=full_host_contract,
    )
    _print_detail(items, u'空間表 Excel dry-run 驗證表（{}｜{}）'.format(
        os.path.basename(xls_path), target))
    pending = [
        i for i in items
        if room_takeoff_sources_logic.space_status_is_pending(i['status'])
    ]
    if not pending and not (
            layout_issues['rid_visible']
            or layout_issues['border_rows']):
        if _MCP_EMBEDDED_RESULT is not None:
            _MCP_EMBEDDED_RESULT.update({
                'path': xls_path,
                'sheet': target,
                'backup': None,
                'updated': False,
            })
            raise _EmbeddedSpaceTableReady()
        forms.alert(u'{}\n\n沒有需要更新的項目。'.format(_summary(items)),
                    title=TOOL_TITLE)
        script.exit()

    layout_notes = []
    if layout_issues['rid_visible']:
        layout_notes.append(u'隱藏 RevitId 識別欄')
    if layout_issues['border_rows']:
        layout_notes.append(u'補齊 {} 列完整框線'.format(
            len(layout_issues['border_rows'])))
    layout_summary = (
        u'\n\n版面修復：{}'.format(u'、'.join(layout_notes))
        if layout_notes else u'')
    if not forms.alert(
            u'【dry-run 驗證】\n\n{}{}\n\n確定要備份並寫入 Excel 嗎？'.format(
                _summary(items), layout_summary),
            title=TOOL_TITLE, yes=True, no=True):
        script.exit()

    # 5. 備份 → 讀寫開啟 → 套用
    backup = takeoff_direct_publish.make_backup_path(xls_path)
    shutil.copy2(xls_path, backup)

    excel = wb = None
    try:
        excel, wb = _excel_open(xls_path, False)
        if wb.ReadOnly:
            forms.alert(
                u'Excel 檔目前是唯讀（可能正被開啟中）。\n'
                u'請先關閉該檔案再執行。', title=TOOL_TITLE)
            script.exit()
        ws = wb.Worksheets.Item(target)
        current_header_row, current_cols, current_rid_new = _find_columns(ws)
        current_entries, current_last_row = _read_space_table(
            ws, current_header_row, current_cols)
        if _space_entries_signature(
                current_entries) != preview_entries_signature:
            raise Exception(
                u'「01空間表」內容自 dry-run 預覽後已改變；為避免沿用舊列號，'
                u'本次未寫入，請重新執行按鈕。')
        header_row = current_header_row
        cols = current_cols
        rid_new = current_rid_new
        entries = current_entries
        last_row = current_last_row
        ref_maps = _scan_ref_sheets(wb, target)
        visible_last_col = max(
            1, cols['number'], cols['name'],
            cols['perimeter'], cols['area'])
        items = _plan(
            entries,
            revit_rooms,
            allow_removals=full_host_contract,
            allow_bootstrap=full_host_contract,
        )
        pending = [
            item for item in items
            if room_takeoff_sources_logic.space_status_is_pending(
                item['status'])]
        if rid_new:
            ws.Cells(header_row, cols['rid']).Value2 = RID_HEADER
        ws.Columns(cols['rid']).Hidden = True
        tail_row = last_row

        # 5a. 既有房間列錯位：先搬回同前綴房號自然序。
        moves = [
            i for i in pending
            if i.get('needs_move') or i['status'] == 'move'
        ]
        for i in moves:
            if _move_space_row(ws, excel, entries, ref_maps, i):
                if i['status'] == 'move':
                    i['status'] = 'moved'

        # 5b. 新房間：空間表插列＋下游連動插列
        final_rows = room_takeoff_sources_logic.space_insert_anchor_rows(
            entries, items)
        inserts = sorted(
            [i for i in pending if i['status'] in ('insert', 'manual_append')],
            key=lambda i: room_takeoff_sources_logic.room_number_sort_key(
                i['number']))
        for i in inserts:
            if i['status'] == 'manual_append':
                pos = tail_row + 1
            else:
                anchor_item = final_rows.get(i['anchor'])
                if anchor_item is None:
                    pos = tail_row + 1
                    i['status'] = 'manual_append'
                else:
                    a = anchor_item['row']
                    pos = a + 1 if i['mode'] == 'after' else a
            excel.CutCopyMode = False
            ws.Rows(pos).Insert()
            tail_row = _shift_rows(entries, ref_maps, pos, tail_row)
            ws.Cells(pos, 1).Value2 = i.get('level') or u''
            ws.Cells(pos, cols['number']).Value2 = i['number']
            ws.Cells(pos, cols['name']).Value2 = i['name']
            ws.Cells(pos, cols['perimeter']).Value2 = i['perimeter']
            ws.Cells(pos, cols['area']).Value2 = i['area']
            ws.Cells(pos, cols['rid']).Value2 = i['rid']
            src = pos - 1 if pos > header_row + 1 else pos + 1
            for c in (cols['perimeter'], cols['area']):
                ws.Cells(pos, c).NumberFormat = ws.Cells(src, c).NumberFormat
            new_entry = {'row': pos, 'number': i['number'],
                         'name': i['name'], 'perimeter': i['perimeter'],
                         'area': i['area'], 'rid': i['rid']}
            entries.append(new_entry)
            final_rows[i['number']] = new_entry
            if i['status'] == 'insert':
                anchor_srow = final_rows[i['anchor']]['row']
                i['sheet_rows'] = _insert_downstream(
                    wb, excel, target, ref_maps, anchor_srow, pos,
                    i['mode'] == 'before')
                i['status'] = 'inserted'
            else:
                i['status'] = 'appended'

        # 5c. 既有房間就地改值（含重編號）＋ Id 回填
        for i in pending:
            if i['status'] not in ('update', 'idfill'):
                continue
            r = i['entry']['row']
            if i['status'] == 'update':
                if i['d_number']:
                    ws.Cells(r, cols['number']).Value2 = i['number']
                if i['d_name']:
                    ws.Cells(r, cols['name']).Value2 = i['name']
                if i['d_peri']:
                    ws.Cells(r, cols['perimeter']).Value2 = i['perimeter']
                if i['d_area']:
                    ws.Cells(r, cols['area']).Value2 = i['area']
            if i.get('need_rid'):
                ws.Cells(r, cols['rid']).Value2 = i['rid']
            i['status'] = 'updated' if i['status'] == 'update' else 'idfilled'

        # 5d. 已拆除：整列刪除＋下游連動刪（由下往上處理；
        # 偵測到殘留引用時退回保留標記防 #REF!）
        removals = sorted(
            [i for i in pending if i['status'] == 'delete_row'],
            key=lambda i: -i['entry']['row'])
        for i in removals:
            r = i['entry']['row']
            allowed = {target: (r, r)}
            for sheet_name in ref_maps:
                info = ref_maps[sheet_name].get(r)
                if info:
                    wsd = wb.Worksheets.Item(sheet_name)
                    allowed[sheet_name] = _block_rows(wsd, info['row'])
            stray = _find_stray_ref(wb, target, r, allowed)
            if stray:
                i['status'] = 'marked_zero'
                i['stray_at'] = stray
                if not i['name'].startswith(REMOVED_PREFIX):
                    ws.Cells(r, cols['name']).Value2 = \
                        REMOVED_PREFIX + i['name']
                if not i['number'].startswith(u'(拆)'):
                    ws.Cells(r, cols['number']).Value2 = u'(拆)' + i['number']
                ws.Cells(r, cols['perimeter']).Value2 = 0
                ws.Cells(r, cols['area']).Value2 = 0
                continue
            deleted, repaired = [], []
            for sheet_name in sorted(ref_maps):
                rows_map = ref_maps[sheet_name]
                info = rows_map.get(r)
                if not info:
                    continue
                wsd = wb.Worksheets.Item(sheet_name)
                first, last = allowed[sheet_name]
                wsd.Range(u'{}:{}'.format(first, last)).EntireRow.Delete()
                n = last - first + 1
                del rows_map[r]
                for v in rows_map.values():
                    if v['row'] > last:
                        v['row'] -= n
                _repair_bare_ref(wsd, first, repaired, sheet_name)
                deleted.append((sheet_name, first, last))
            ws.Rows(r).Delete()
            _repair_bare_ref(ws, r, repaired, target)
            i['repaired'] = repaired
            entries.remove(i['entry'])
            for e in entries:
                if e['row'] > r:
                    e['row'] -= 1
            for name in ref_maps:
                ref_maps[name] = dict(
                    (sr - 1 if sr > r else sr, v)
                    for sr, v in ref_maps[name].items())
            if tail_row >= r:
                tail_row -= 1
            i['deleted_sheets'] = deleted
            i['status'] = 'deleted_row'

        repaired_format_rows = _repair_space_row_formats(
            ws, excel, entries, 1, visible_last_col)
        _excel_close(excel, wb, True)
        excel = wb = None
    finally:
        if excel is not None:
            _excel_close(excel, wb, False)

    # 6. 完成報告
    _print_detail(items, u'空間表 Excel 已套用')
    msg = u'【已套用】\n\n{}\n\n備份：{}'.format(
        _summary(items), os.path.basename(backup))
    renum = sum(1 for i in items if i.get('d_number'))
    if renum:
        msg += (u'\n\n{} 筆重編號已就地改編號欄（列位不動，'
                u'下游手填資料跟著房間本體，不會錯位）。').format(renum)
    if repaired_format_rows:
        msg += u'\n\n已補齊 {} 列空間資料的完整儲存格框線。'.format(
            len(repaired_format_rows))
    msg += u'\n\nRevitId 識別欄已隱藏，不再顯示 link 字樣。'
    unresolved = sum(1 for i in items if i['status'] == 'unresolved')
    if unresolved:
        msg += (u'\n\n⚠ {} 筆疑似改名+重編未寫入，'
                u'請依輸出視窗逐筆人工確認。').format(unresolved)
    if _MCP_EMBEDDED_RESULT is not None:
        _MCP_EMBEDDED_RESULT.update({
            'path': xls_path,
            'sheet': target,
            'backup': backup,
            'updated': True,
        })
    else:
        forms.alert(msg, title=TOOL_TITLE)
except _EmbeddedSpaceTableReady:
    pass
except mcp.MCPBridgeError as e:
    mcp.show_error(e, TOOL_TITLE)
    if _MCP_EMBEDDED_RESULT is not None:
        _MCP_EMBEDDED_RESULT['handled_error'] = True
except Exception as e:
    if _MCP_EMBEDDED_RESULT is not None:
        _MCP_EMBEDDED_RESULT['error'] = u'{}'.format(e)
    else:
        forms.alert(u'執行失敗：\n\n{}'.format(e), title=TOOL_TITLE)
