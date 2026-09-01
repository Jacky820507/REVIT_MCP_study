# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""產生／驗證固化在 ``tests\\goldens\\*.json`` 裡的回歸基準。

## 這支解決的問題

2026-08-31 那一輪 SheetLayout 重構，每一步都靠「重構前 vs 重構後」的產出比對
證明沒有動到行為——但那些比對腳本全部寫在 session 的 scratchpad 裡，session
一結束就消失了。下次有人動這些按鈕，同樣的驗證得重寫一遍。

這支把「怎麼產生一顆按鈕的完整輸出」收斂成一個函式（每顆一份），``tests\\goldens\\``
底下放的是**這些函式現在的輸出**，``test_golden_regression.py`` 每次跑測試都重新
呼叫這些函式，跟存檔的 JSON 比對——**逐格逐公式**，比「表頭對不對得上欄位字母」
再往下一層。

## 誰用這支

* ``test_golden_regression.py``：每次 CI／pre-deploy 都跑，比對現在的輸出跟
  golden 檔案，不同就是回歸。
* ``tools\\regen_goldens.py``：**刻意**改變行為之後（不是重構，是真的要換算式／
  改版面），跑這支重新產生 golden 檔案並蓋掉舊的。這是唯一「golden 該被更新」的
  情境；平常測試失敗代表程式壞了，不是 golden 該更新。

## 涵蓋範圍與盲點

涵蓋六顆已移轉 SheetLayout 的 Takeoff 按鈕（儲存格值、公式、合併範圍、欄寬、
凍結窗格）、``scaffold_excel`` 對 Excel COM 下的完整指令序列（見
``com_recorder.py`` 的模組 docstring 說明為什麼要記指令而不是比檔案）、以及
三支 ``*_logic`` 產出的獨立匯出表。**不覆蓋** Excel 實際開啟後的行為（公式重算、
樣式呈現）——那一層仍然只能在真的 Excel 裡驗。
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import revit_stub  # noqa: E402
import takeoff_harness as harness  # noqa: E402
from com_recorder import CommandRecorder  # noqa: E402


GOLDEN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          'goldens')


# ---------------------------------------------------------------------------
# 六顆已移轉 SheetLayout 的 Takeoff 按鈕
# ---------------------------------------------------------------------------

def _workbook_payload(run, outpath):
    """把 ``TakeoffRun``/``ButtonRun`` 跑完之後的產出收成一份可序列化的 dict。"""
    sheets = harness.read_sheets(outpath)
    xml = []
    import zipfile
    import xml.etree.ElementTree as ElementTree
    NS = harness.NS
    with zipfile.ZipFile(outpath) as archive:
        for name in sorted(n for n in archive.namelist()
                           if 'worksheets/sheet' in n):
            root = ElementTree.fromstring(archive.read(name))
            xml.append({
                'sheet': name,
                'merges': [m.get('ref') for m in root.iter(NS + 'mergeCell')],
                'cols': [(c.get('min'), c.get('max'), c.get('width'))
                        for c in root.iter(NS + 'col')],
                'panes': [(p.get('ySplit'), p.get('topLeftCell'))
                         for p in root.iter(NS + 'pane')],
            })
    return {'cells': sheets, 'xml': xml}


def rc_volume_excel():
    import test_rc_volume_main_wiring as mod
    tmp = tempfile.mkdtemp(prefix='golden-')
    path = os.path.join(tmp, 'g.xlsx')
    with mod.ButtonRun(tmp, {'ask_for_string': 'RC', 'alert_yes_no': True,
                             'save_file': path}) as run:
        run.run()
    return _workbook_payload(run, path)


def _workbook_contract_case(modname, casename):
    """把 ``harness.WorkbookContract`` 子類別跑一次，取它的 make_fixture。"""
    mod = __import__(modname)
    case_cls = getattr(mod, casename)
    case = case_cls()
    case.tmpdir = tempfile.mkdtemp(prefix='golden-')
    case.outpath = os.path.join(case.tmpdir, case.OUT_NAME)
    with case.make_run() as run:
        run.run()
    return _workbook_payload(run, case.outpath)


def partition_takeoff():
    return _workbook_contract_case('test_partition_takeoff_wiring',
                                   'PartitionTakeoffWiringTests')


def baseboard():
    return _workbook_contract_case('test_baseboard_wiring',
                                   'BaseboardWiringTests')


def interior_wall_paint():
    return _workbook_contract_case('test_interior_wall_paint_wiring',
                                   'InteriorWallPaintWiringTests')


def ceiling_takeoff():
    return _workbook_contract_case('test_ceiling_takeoff_wiring',
                                   'CeilingTakeoffWiringTests')


def floor_takeoff():
    return _workbook_contract_case('test_floor_takeoff_wiring',
                                   'FloorTakeoffWiringTests')


TAKEOFF_BUTTONS = {
    'rc_volume_excel': rc_volume_excel,
    'partition_takeoff': partition_takeoff,
    'baseboard': baseboard,
    'interior_wall_paint': interior_wall_paint,
    'ceiling_takeoff': ceiling_takeoff,
    'floor_takeoff': floor_takeoff,
}


# ---------------------------------------------------------------------------
# scaffold_excel：Excel COM 指令序列 + 獨立匯出表
# ---------------------------------------------------------------------------

TAKEOFF_EXTERIOR = {
    'quantity': 128.5, 'perimeter': 42.0, 'height': 3.06,
    'source': u'選取的詳圖線', 'command': 'calculate_selected_detail_line_perimeter',
}


def _scaffold_room_item(number, name, category, **extra):
    item = {
        'revit_id': 'host:' + number, 'level': '1F', 'number': number,
        'name': name, 'category': category, 'category_name': u'一般',
        'rule': u'代碼', 'space_row': 12, 'space_sheet': u'01空間表',
        'perimeter_col': 6, 'length': 8.0, 'width': 6.0, 'height': 3.2,
        'height_ref': None, 'height_source': u'射線',
        'formula_text': u'8 × 6', 'unit': 'M2', 'included': True,
        'warnings': [], 'source_key': 'host', 'source_label': u'主模型',
        'local_element_id': 101, 'dimension_source': u'房間邊界',
    }
    item.update(extra)
    return item


def _scaffold_room_takeoff():
    return {
        'space_sheet': u'01空間表',
        'rows': [
            _scaffold_room_item('101', u'辦公室', 'general_scaffold'),
            _scaffold_room_item('102', u'裝修區', 'interior_finish_scaffold'),
            _scaffold_room_item('103', u'排除區', 'other', included=False,
                                warnings=[u'未分類']),
            _scaffold_room_item('104', u'高區', 'general_scaffold',
                                height_ref={'sheet': u'01空間表', 'col': 9,
                                           'row': 15}),
        ],
        'totals': {'general': 48.0, 'interior_finish': 12.0},
    }


def scaffold_excel_com():
    """對 ``_ensure_audit_sheet`` / ``_write_exterior_audit`` /
    ``_write_room_audit`` 下的完整 COM 指令序列。"""
    journal = []
    with revit_stub.install(answers={}):
        module = revit_stub.load_lib('scaffold_excel')

        wb = CommandRecorder(journal, 'wb')
        journal.append('--- _ensure_audit_sheet ---')
        module._sheet_by_trim = lambda *a, **k: CommandRecorder(journal, 'ws')
        module._ensure_audit_sheet(wb)

        journal.append('--- _write_exterior_audit ---')
        module._write_exterior_audit(CommandRecorder(journal, 'ws'),
                                     dict(TAKEOFF_EXTERIOR))

        journal.append('--- _write_room_audit ---')
        # _write_general_level_summary 刻意不 stub：那段（樓層小計的字型／
        # 邊框／欄寬格式化）正是這次重構動到的地方之一，golden 要涵蓋它。
        module._clear_room_audit = lambda ws: journal.append(
            'CALL _clear_room_audit()')
        module._write_room_audit(CommandRecorder(journal, 'ws'),
                                 _scaffold_room_takeoff())
    return {'journal': journal}


def scaffold_excel_standalone():
    def item(number, category, **extra):
        row = {
            'source_key': 'host', 'source_label': u'主模型',
            'revit_id': 'host:' + number, 'local_element_id': int(number),
            'level': '1F', 'number': number, 'name': u'房間' + number,
            'category': category, 'perimeter': 28.0, 'length': 8.0,
            'width': 6.0, 'height': 3.2, 'height_source': u'射線',
            'included': True, 'unit': 'M2', 'rule': u'代碼',
            'dimension_source': u'房間邊界', 'audit_warnings': [],
        }
        row.update(extra)
        return row

    takeoff = {'rows': [item('101', 'general_scaffold'),
                        item('102', 'interior_finish_scaffold', unit='M3'),
                        item('103', 'other', included=False,
                             audit_warnings=[u'未分類'])],
              'totals': {'general': 48.0, 'interior_finish': 12.0}}
    with revit_stub.install(answers={}):
        module = revit_stub.load_lib('scaffold_excel')
        return module._scaffold_standalone_tables(takeoff)


# ---------------------------------------------------------------------------
# 三支 *_logic 的獨立匯出表
# ---------------------------------------------------------------------------

def parking_excel_logic():
    with revit_stub.install(answers={}):
        module = revit_stub.load_lib('parking_excel_logic')
        detail = [{
            'source_key': 'host', 'source_label': u'主模型', 'level_id': 1,
            'element_id': 1000 + i, 'type_name': u'停車位',
            'category_key': key, 'category': u'車位', 'width_mm': 2500,
            'length_mm': 5500, 'grouped': 0, 'status': u'OK',
            'level_name': 'B1', 'geometry_level_id': 1,
            'geometry_level': 'B1', 'base_elevation_mm': -3000,
            'level_basis': 'parameter',
        } for i, key in enumerate([it['key'] for it in module.ITEMS])]
        takeoff = {'details': detail, 'rows': detail, 'source_counts': [],
                  'unclassified': [], 'ignored': [],
                  'annotation_candidates': []}
        return module.standalone_tables(takeoff, 2)


def door_window_excel_logic():
    with revit_stub.install(answers={}):
        module = revit_stub.load_lib('door_window_excel_logic')
        takeoff = {
            'audit_rows': [
                {'source_key': 'host', 'model': u'主模型', 'level': '1F',
                 'key': 'D1', 'name': u'單開門', 'count': 3},
                {'source_key': 'host', 'model': u'主模型', 'level': '2F',
                 'key': 'W1', 'name': u'固定窗', 'count': 5},
            ],
            'sources': [u'主模型'], 'total': 8,
        }
        return module.standalone_tables(takeoff)


def machine_room_threshold_logic():
    with revit_stub.install(answers={}):
        module = revit_stub.load_lib('machine_room_threshold_logic')
        summary = {'doors': [
            {'source_key': 'host', 'source_label': u'主模型',
             'element_id': 501, 'from_number': '101', 'from_name': u'機房',
             'to_number': '102', 'to_name': u'走廊', 'width_m': 0.9},
            {'source_key': 'host', 'source_label': u'主模型',
             'element_id': 502, 'from_number': '103', 'from_name': u'配電室',
             'to_number': '104', 'to_name': u'走廊', 'width_m': 1.2},
        ]}
        return module.standalone_tables([], summary, [])


ALL_FIXTURES = dict(TAKEOFF_BUTTONS)
ALL_FIXTURES.update({
    'scaffold_excel_com': scaffold_excel_com,
    'scaffold_excel_standalone': scaffold_excel_standalone,
    'parking_excel_logic': parking_excel_logic,
    'door_window_excel_logic': door_window_excel_logic,
    'machine_room_threshold_logic': machine_room_threshold_logic,
})
