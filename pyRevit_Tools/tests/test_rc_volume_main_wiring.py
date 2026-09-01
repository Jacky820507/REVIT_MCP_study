# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""真的執行 ``RcVolumeExcel`` 的 ``main()``，驗它的接線而不是它的算式。

## 這支和 test_rc_volume.py 的分工

``test_rc_volume.py`` 測的是 ``lib\\rc_volume_logic.py``——純函式、沒有 Revit。
那支很完整，但它從頭到尾**沒有 import 過按鈕的 script.py**，所以 1636 行裡
「拿到資料之後要怎麼組、怎麼寫檔、怎麼回報」那一段，一個案例都沒有。

這支補的就是那一段。它用 ``revit_stub`` 把 Revit／pyrevit／.NET 換成假貨，在
``collect_data`` 這個接縫餵 fixture，然後**呼叫真正的 ``main()``**，對真正寫出來的
``.xlsx`` 下斷言。

## 它針對的是哪幾次真實事故

1. **sheet 2 餵錯來源**：sheet 1 吃的是分攤後的 ``grouped_by_room``，sheet 2 要的是
   整支牆 ``rc_walls``。餵錯不會報錯，只會讓同一支牆在稽核分頁重複列出。
   → ``test_sheet_two_lists_whole_walls_not_room_slices``

2. **寫死的欄位字母**（就是那個 ``$V``）：欄位一搬動，陣列索引跟著位移，但公式裡的
   字母不會。這裡不比對字面值，而是**從表頭反推該欄應該是哪個字母**，所以任何一次
   欄位增刪都會當場被抓到。
   → ``HardcodedColumnTests`` 三個案例

3. **``report()`` 讀 stats 少一個 key**：Excel 已經寫完才 KeyError，使用者會誤以為
   匯出失敗。這支把 ``report()`` 也跑過一次。
   → ``test_report_runs_and_prints_the_same_total_as_the_sheet``

4. **對話框流程漂移**：加了新對話框卻沒接上、或取消之後沒有提早 return。
   ``ScriptedForms`` 對沒排答案的提問會丟例外，不會安靜地回 ``None``。
   → ``test_dialog_sequence_is_exactly_what_main_promises`` 等三個案例

## 這支測不到什麼

``collect_data`` 內部（Revit 幾何、Solid 布林、Room 邊界）在 fixture 的另一邊，
測不到——那一層要在 Revit 裡實測。其餘限制見 ``revit_stub`` 的模組 docstring。
"""

import os
import shutil
import tempfile
import unittest
import zipfile

import revit_stub
import takeoff_harness as harness
from takeoff_harness import (cells_in_row, column_of, display,
                             find_row_containing, read_sheets,
                             row_of)


BUTTON = revit_stub.button_path('Takeoff.panel', 'RcVolumeExcel')
SUM_RANGE = harness.SUM_RANGE


# ---------------------------------------------------------------------------
# fixture：collect_data 回傳的六元組
# ---------------------------------------------------------------------------

def _opening(name, width, height):
    return {'name': name, 'width': width, 'height': height}


def _wall(element_id, type_name, length, thickness, openings,
          room_number, room_name, overlap=0.0):
    return {
        'element_id': element_id,
        'type_name': type_name,
        'location_mark': 'A(1.2)/2',
        'zone': 'Z1',
        'length': length,
        'height': 3.2,
        'thickness': thickness,
        'openings': list(openings),
        'room_number': room_number,
        'room_name': room_name,
        'room_assign': 'boundary',
        'base_constraint': '1FL',
        'height_source': 'area-derived',
        'overlap_deduct': overlap,
        'overlap_detail': '梁 B1 0.120' if overlap else '',
        'join_state': 'unjoined' if overlap else 'joined',
        'revit_volume': length * 3.2 * thickness,
        'allocation_text': '{0} 100%'.format(room_number) if room_number else '',
    }


def make_fixture(module):
    """一份小而完整的 ``collect_data`` 回傳值。

    刻意包含：兩種牆類型、一支帶開口的牆、一支帶樑柱板扣除的牆、一支沒有房間
    歸屬的牆——後者是最容易在彙總時被漏掉的那一種。
    """
    rooms = [
        {'key': '101', 'number': '101', 'name': '大廳', 'perimeter': '24.00'},
        {'key': '102', 'number': '102', 'name': '機房', 'perimeter': '18.00'},
    ]

    wall_a = _wall(311001, 'RC 牆 15cm', 6.0, 0.15,
                   [_opening('D1', 0.9, 2.1)], '101', '大廳')
    wall_b = _wall(311002, 'RC 牆 25cm', 4.0, 0.25, [], '102', '機房',
                   overlap=0.12)
    wall_c = _wall(311003, 'RC 牆 15cm', 2.5, 0.15, [], '', '')
    wall_c['room_assign'] = 'none'
    wall_c['room_name'] = module.logic.UNASSIGNED_ROOM_LABEL
    wall_c['allocation_text'] = ''

    rc_walls = [wall_a, wall_b, wall_c]
    grouped_by_room = {
        '101': [dict(wall_a, share=1.0, room_key='101')],
        '102': [dict(wall_b, share=1.0, room_key='102')],
    }
    unassigned = [dict(wall_c, share=1.0, room_key='')]
    wall_type_cols = sorted(set(wall['type_name'] for wall in rc_walls),
                            key=module.logic.type_sort_key)

    stats = {
        'rooms': len(rooms),
        'grids': 8,
        'scanned_walls': 57,
        'rc_walls': len(rc_walls),
        'assigned_openings': 1,
        'opening_warnings': [],
        'missing_thickness': [],
        'missing_height': [],
        'unassigned': unassigned,
        'assign_sources': {'boundary': 2, 'none': 1},
        'height_sources': {'area-derived': 3},
        'clear_height_rooms': 2,
        'clear_height_error': '',
        'revit_volume_total': sum(w['revit_volume'] for w in rc_walls),
        'overlap_total': 0.12,
        'overlap_by_category': {'梁': 0.12},
        'overlap_failures': 0,
        'joined_pairs': 4,
        'deducted_pairs': 1,
        'split_walls': 0,
        'deduct_overlaps': True,
    }
    return rooms, grouped_by_room, unassigned, wall_type_cols, rc_walls, stats


# ---------------------------------------------------------------------------
# 共用的執行外殼
# ---------------------------------------------------------------------------

class ButtonRun(object):
    """跑一次 ``main()``，把假貨、模組與產出的檔案一起帶回來。"""

    def __init__(self, tmpdir, answers, fixture=None, document=None):
        self.tmpdir = tmpdir
        self.answers = answers
        self.fixture = fixture
        self.document = document
        self.module = None
        self.stub = None
        self.collect_calls = []

    def __enter__(self):
        document = self.document or revit_stub.FakeDocument(
            path_name=os.path.join(self.tmpdir, '示範專案.rvt'))
        self._ctx = revit_stub.install(document=document,
                                       answers=self.answers)
        self.stub = self._ctx.__enter__()
        self.module = revit_stub.load_button(BUTTON, 'rc_volume_button')

        fixture = self.fixture
        if fixture is None:
            fixture = make_fixture(self.module)
        elif callable(fixture):
            fixture = fixture(self.module)
        self.fixture_value = fixture

        calls = self.collect_calls

        def fake_collect_data(keywords, deduct_overlaps):
            calls.append((keywords, deduct_overlaps))
            return fixture

        self.module.collect_data = fake_collect_data
        return self

    def __exit__(self, *exc):
        return self._ctx.__exit__(*exc)

    def run(self):
        self.module.main()
        return self


class MainWiringTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='rcvol-')
        self.outpath = os.path.join(self.tmpdir, '輸出.xlsx')
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    # 「不傳」與「傳 None（＝使用者按取消）」是兩件事，用哨兵分開
    _DEFAULT = object()

    def default_answers(self, save_to=_DEFAULT):
        return {
            'ask_for_string': 'RC',
            'alert_yes_no': True,
            'save_file': self.outpath if save_to is self._DEFAULT else save_to,
        }

    # -- 端對端 ------------------------------------------------------------

    def test_main_writes_a_parsable_two_sheet_workbook(self):
        with ButtonRun(self.tmpdir, self.default_answers()) as run:
            run.run()
        self.assertTrue(os.path.exists(self.outpath))
        self.assertTrue(zipfile.is_zipfile(self.outpath))

        with zipfile.ZipFile(self.outpath) as archive:
            names = archive.namelist()
        self.assertEqual(sorted(set(names)), sorted(names),
                         'xlsx 內有重複的 part，Excel 開檔會要求修復')
        for required in ('[Content_Types].xml', '_rels/.rels',
                         'xl/workbook.xml', 'xl/styles.xml',
                         'xl/worksheets/sheet1.xml',
                         'xl/worksheets/sheet2.xml'):
            self.assertIn(required, names)

        self.assertEqual(2, len(read_sheets(self.outpath)))

    def test_keywords_and_overlap_answers_reach_collect_data(self):
        """使用者在對話框回答的東西，要真的走到 collect_data，不是被吞掉。"""
        answers = self.default_answers()
        answers['ask_for_string'] = 'RC、混凝土'
        answers['alert_yes_no'] = False
        with ButtonRun(self.tmpdir, answers) as run:
            run.run()
            self.assertEqual(1, len(run.collect_calls))
            keywords, deduct = run.collect_calls[0]
            self.assertEqual(['RC', '混凝土'], keywords)
            self.assertFalse(deduct)

    def test_dialog_sequence_is_exactly_what_main_promises(self):
        """問答順序固定：關鍵字 → 要不要扣重疊 → 存檔位置 → 完成通知。"""
        with ButtonRun(self.tmpdir, self.default_answers()) as run:
            run.run()
            self.assertEqual(
                ['ask_for_string', 'alert_yes_no', 'save_file', 'alert'],
                run.stub.forms.prompt_sequence)

    # -- 提早 return 的三條路 ----------------------------------------------

    def test_cancelling_the_keyword_prompt_writes_no_file(self):
        answers = self.default_answers()
        answers['ask_for_string'] = None
        with ButtonRun(self.tmpdir, answers) as run:
            run.run()
            self.assertEqual([], run.collect_calls,
                             '使用者已取消，不該再去掃模型')
        self.assertFalse(os.path.exists(self.outpath))

    def test_cancelling_the_save_dialog_writes_no_file(self):
        answers = self.default_answers(save_to=None)
        with ButtonRun(self.tmpdir, answers) as run:
            run.run()
            self.assertEqual([], run.collect_calls)
        self.assertFalse(os.path.exists(self.outpath))

    def test_no_rc_wall_alerts_and_stops_before_writing(self):
        def empty(module):
            rooms, grouped, unassigned, cols, walls, stats = \
                make_fixture(module)
            stats = dict(stats, rc_walls=0)
            return rooms, {}, [], [], [], stats

        with ButtonRun(self.tmpdir, self.default_answers(),
                       fixture=empty) as run:
            run.run()
            self.assertEqual(1, len(run.stub.forms.alerts))
            self.assertIn('未匯出', run.stub.forms.alerts[0])
        self.assertFalse(os.path.exists(self.outpath))

    def test_missing_extension_is_appended(self):
        bare = os.path.join(self.tmpdir, '沒有副檔名')
        with ButtonRun(self.tmpdir, self.default_answers(save_to=bare)) as run:
            run.run()
        self.assertTrue(os.path.exists(bare + '.xlsx'))
        self.assertFalse(os.path.exists(bare))

    # -- sheet 2 的來源 ----------------------------------------------------

    def test_sheet_two_lists_whole_walls_not_room_slices(self):
        """出過事的那一次：sheet 2 被餵了分攤後的切片而不是整支牆。"""
        with ButtonRun(self.tmpdir, self.default_answers()) as run:
            run.run()
            rc_walls = run.fixture_value[4]

        detail = read_sheets(self.outpath)[1]
        total_row = find_row_containing(detail, run.module.SUMMARY_LABEL)
        ids = []
        for ref, cell in sorted(detail.items(), key=lambda kv: row_of(kv[0])):
            if column_of(ref) != 'A':
                continue
            if row_of(ref) < run.module.DETAIL_FIRST_DATA_ROW:
                continue
            if total_row and row_of(ref) >= total_row:
                continue
            if cell['v'] is not None:
                ids.append(int(cell['v']))

        self.assertEqual([w['element_id'] for w in rc_walls], ids)
        self.assertEqual(len(set(ids)), len(ids),
                         '同一支牆在稽核分頁重複出現，代表餵進來的是房間切片')

    # -- report() ----------------------------------------------------------

    def test_report_runs_and_prints_the_same_total_as_the_sheet(self):
        """report() 讀遍 stats 的每個 key；少一個就是寫完檔之後才炸的 KeyError。"""
        with ButtonRun(self.tmpdir, self.default_answers()) as run:
            run.run()
            rooms, grouped, unassigned = run.fixture_value[:3]
            expected = run.module.summary_total_volume(rooms, grouped,
                                                       unassigned)
            printed = run.stub.output.text

        self.assertIn('RC體積 Excel 匯出完成', printed)
        self.assertIn(run.module.fixed(expected, 3), printed)
        self.assertIn('未分配到房間', printed,
                      '沒有房間歸屬的牆必須在報告裡點名，否則會被當成漏算')


class HardcodedColumnTests(unittest.TestCase):
    """欄位字母寫死的防線：不比對字面值，從表頭反推該欄應該是什麼。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='rcvol-col-')
        self.outpath = os.path.join(self.tmpdir, '欄位.xlsx')
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

        self.run = ButtonRun(self.tmpdir, {
            'ask_for_string': 'RC',
            'alert_yes_no': True,
            'save_file': self.outpath,
        })
        self.run.__enter__()
        self.addCleanup(self.run.__exit__, None, None, None)
        self.run.run()
        self.module = self.run.module
        self.summary, self.detail = read_sheets(self.outpath)

    def column_for_header(self, sheet, header_row, title):
        for ref, cell in sheet.items():
            if row_of(ref) == header_row and display(cell) == title:
                return column_of(ref)
        raise AssertionError('表頭找不到「{0}」'.format(title))

    def test_grand_total_rows_sum_their_own_column(self):
        """總計列的每個 SUM 都必須加自己那一欄——這正是 $V 那次的形狀。"""
        checked = 0
        for sheet in (self.summary, self.detail):
            total_row = find_row_containing(sheet, self.module.SUMMARY_LABEL)
            self.assertIsNotNone(total_row, '找不到總計列')
            for ref, cell in cells_in_row(sheet, total_row).items():
                if not cell['f']:
                    continue
                match = SUM_RANGE.match(cell['f'])
                if not match:
                    continue
                checked += 1
                self.assertEqual(
                    column_of(ref), match.group(1),
                    '{0} 的公式 =SUM({1}...) 沒有加自己那一欄'.format(
                        ref, match.group(1)))
                self.assertEqual(match.group(1), match.group(2))
        self.assertGreaterEqual(checked, 4, '總計列的 SUM 公式太少，斷言沒生效')

    def test_opening_subtotal_sums_the_opening_area_column(self):
        """sheet 2 的「開口合計面積」跨欄加總，字母必須指向「面積小計」那一欄。"""
        header_row = self.module.DETAIL_FIRST_DATA_ROW - 1
        area_col = self.column_for_header(self.detail, header_row,
                                          '面積小計 (m²)')
        subtotal_col = self.column_for_header(self.detail, header_row,
                                              '開口合計面積 (m²)')
        cell = self.detail.get(
            '{0}{1}'.format(subtotal_col, self.module.DETAIL_FIRST_DATA_ROW))
        self.assertIsNotNone(cell)
        match = SUM_RANGE.match(cell['f'] or '')
        self.assertIsNotNone(match, '開口合計欄應該是 SUM 公式')
        self.assertEqual(area_col, match.group(1))

    def test_type_column_formula_points_at_the_net_volume_column(self):
        """sheet 1 每種牆類型的欄位轉抄淨體積；字母必須指向「淨體積」那一欄。"""
        header_row = self.module.FIRST_DATA_ROW - 1
        net_col = self.column_for_header(self.summary, header_row,
                                         '淨體積 (m³)')
        type_cols = [self.column_for_header(self.summary, header_row, name)
                     for name in self.run.fixture_value[3]]
        self.assertTrue(type_cols)

        found = 0
        for ref, cell in self.summary.items():
            if column_of(ref) not in type_cols or not cell['f']:
                continue
            if row_of(ref) < self.module.FIRST_DATA_ROW:
                continue
            if SUM_RANGE.match(cell['f']):
                continue
            found += 1
            self.assertEqual(
                '{0}{1}'.format(net_col, row_of(ref)), cell['f'],
                '{0} 應該轉抄同一列的淨體積'.format(ref))
        self.assertGreaterEqual(found, 1, '沒有任何類型欄公式，斷言沒生效')


class NoHandWrittenAddressTests(harness.NoHandWrittenAddresses,
                                unittest.TestCase):
    """欄位字母只能由 ``SheetLayout`` 產生，原始碼裡不該再出現手寫的。

    這條是 open-sheet 的那句「There is not a single A1 address in an open-sheet
    source file」搬過來的常駐版本。實作在 ``takeoff_harness``，因為其他按鈕陸續
    移轉後都要套同一條。

    2026-08-31 實測：在 sheet 1 中間插一欄「澆置分區」，重構前的版本有一個案例
    失敗（公式安靜地指到隔壁欄），重構後全數通過。
    """

    BUTTON = BUTTON


class EntrypointTests(unittest.TestCase):
    def test_button_ends_with_exactly_one_bare_main_call(self):
        """按鈕靠檔尾那行 main() 啟動；刪掉它按鈕就變成什麼都不做。"""
        with revit_stub.install(answers={}) as _stub:
            module = revit_stub.load_button(BUTTON, 'rc_volume_entry_check')
        with open(BUTTON, 'rb') as handle:
            total_lines = len(handle.read().decode('utf-8').splitlines())
        self.assertEqual(total_lines, module.__entrypoint_line__,
                         'main() 必須是檔案的最後一行')


if __name__ == '__main__':
    unittest.main()
