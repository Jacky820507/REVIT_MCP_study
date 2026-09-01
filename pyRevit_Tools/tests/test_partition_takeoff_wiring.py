# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""真的執行「輕隔間 Excel」的 ``main()``。

跟 ``test_rc_volume_main_wiring`` 同一個目的：``test_*_logic`` 那些純函式測試
碰不到按鈕 ``script.py`` 的接線。這支把 ``collect_selected_sources`` 換成 fixture，
其餘（``make_rows`` → ``build_sheet_values`` → ``write_xlsx`` → 報告）全部照跑。

共用的合約案例在 ``takeoff_harness.WorkbookContract``；這裡只寫輕隔間特有的：
沒有牆的房間必須仍然佔一列（否則整間房會從表上消失），以及類型欄的公式要指向
「總計」欄而不是某個寫死的字母。
"""

import unittest

import revit_stub
import takeoff_harness as harness
from takeoff_harness import (column_for_header, column_of, display,
                             find_row_containing, read_sheets, row_of)


BUTTON = revit_stub.button_path('Takeoff.panel', 'PartitionTakeoff')


def _opening(name, width, height):
    return {'name': name, 'width': width, 'height': height}


def _wall(type_name, length, height, area, openings=(), level='1FL'):
    return {
        'type_name': type_name,
        'level': level,
        'height': height,
        'length': length,
        'area': area,
        'openings': list(openings),
    }


ROOM_WITHOUT_WALLS = {
    'element_id': 503, 'number': '103', 'name': '儲藏室', 'perimeter': '8.00',
}


def make_fixture(module):
    """兩種牆型、一間有開口、一間沒有牆——最後一種最容易在彙總時整列消失。"""
    rooms = [
        {'element_id': 501, 'number': '101', 'name': '辦公室',
         'perimeter': '24.00'},
        {'element_id': 502, 'number': '102', 'name': '茶水間',
         'perimeter': '12.00'},
        dict(ROOM_WITHOUT_WALLS),
    ]
    wall_a = _wall('TYPE-A 濕式輕隔間', 6.0, 3.2, 6.0 * 3.2 - 0.9 * 2.1,
                   [_opening('D1', 0.9, 2.1)])
    wall_b = _wall('TYPE-B 乾式輕隔間', 4.0, 3.2, 4.0 * 3.2)
    wall_c = _wall('TYPE-A 濕式輕隔間', 2.5, 2.8, 2.5 * 2.8)

    grouped_by_room = {501: [wall_a, wall_b], 502: [wall_c]}
    wall_type_cols = ['TYPE-A 濕式輕隔間', 'TYPE-B 乾式輕隔間']
    stats = {
        'rooms': len(rooms),
        'partition_walls': 3,
        'assigned_walls': 3,
        'openings': 1,
        'assigned_openings': 1,
        'skipped_openings': 0,
        'slab_levels': 2,
        'height_detector': 'ray',
        'height_detector_rooms': 3,
        'height_detector_ceiling_skipped': 0,
        'height_detector_walls': 3,
        'height_sources': {'ray-to-slab': 3},
        'excluded_walls': 1,
        'excluded_types': {'TYPE-X 誤建': 1},
    }
    sources = [('host', '主模型', None, None, 0)]
    return rooms, grouped_by_room, wall_type_cols, stats, sources


class PartitionTakeoffAddressTests(harness.NoHandWrittenAddresses,
                                   unittest.TestCase):
    BUTTON = BUTTON


class PartitionTakeoffWiringTests(harness.WorkbookContract, unittest.TestCase):
    BUTTON = BUTTON
    SEAM = 'collect_selected_sources'
    SHEET_COUNT = 1
    DONE_MARK = '輕隔間 Excel 匯出完成'
    OUT_NAME = '輕隔間.xlsx'

    def make_fixture(self, module):
        return make_fixture(module)

    # -- 輕隔間特有 --------------------------------------------------------

    def read_sheet(self):
        with self.make_run() as run:
            run.run()
            self.module = run.module
        return read_sheets(self.outpath)[0]

    def test_a_room_with_no_wall_still_gets_a_row(self):
        """沒有輕隔間的房間仍要佔一列；整列消失在表上看不出來，只會少算。"""
        sheet = self.read_sheet()
        numbers = [display(cell) for ref, cell in sheet.items()
                   if column_of(ref) == 'A'
                   and row_of(ref) >= self.module.FIRST_DATA_ROW]
        self.assertIn(ROOM_WITHOUT_WALLS['number'], numbers)

    def test_type_column_formula_points_at_the_total_column(self):
        """類型欄轉抄同列的「總計」；字母寫死時這裡會對不上。"""
        sheet = self.read_sheet()
        header_row = self.module.FIRST_DATA_ROW - 1
        total_col = column_for_header(sheet, header_row, '總計')
        type_cols = [column_for_header(sheet, header_row, name)
                     for name in ('TYPE-A 濕式輕隔間', 'TYPE-B 乾式輕隔間')]

        found = 0
        for ref, cell in sheet.items():
            if column_of(ref) not in type_cols or not cell['f']:
                continue
            if row_of(ref) < self.module.FIRST_DATA_ROW:
                continue
            if harness.SUM_RANGE.match(cell['f']):
                continue
            found += 1
            self.assertEqual('{0}{1}'.format(total_col, row_of(ref)),
                             cell['f'],
                             '{0} 應該轉抄同一列的總計'.format(ref))
        self.assertGreaterEqual(found, 2, '沒有足夠的類型欄公式，斷言沒生效')

    def test_summary_row_sits_directly_under_the_last_data_row(self):
        """報告會印摘要列的列號給發佈流程用；算錯就會寫到別的地方去。"""
        sheet = self.read_sheet()
        total_row = find_row_containing(sheet, self.module.SUMMARY_LABEL)
        self.assertIsNotNone(total_row)
        data_rows = set(
            row_of(ref) for ref, cell in sheet.items()
            if column_of(ref) == 'A'
            and row_of(ref) >= self.module.FIRST_DATA_ROW
            and display(cell) and row_of(ref) != total_row)
        self.assertTrue(data_rows)
        self.assertGreater(total_row, max(data_rows))


if __name__ == '__main__':
    unittest.main()
