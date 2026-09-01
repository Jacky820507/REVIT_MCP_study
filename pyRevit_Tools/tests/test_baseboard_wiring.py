# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""真的執行「踢腳 Excel」的 ``main()``。

踢腳這顆比輕隔間多三個會碰外部世界的步驟——掃族群符號、跳材料版選單、讀材料
名稱 CSV——所以除了主接縫 ``collect_selected_sources`` 之外，那三個也一起換掉，
``main()`` 才走得到寫檔那一步。換掉的東西列在 ``extra_patches``，名字對不上會
直接失敗（函式被改名或搬走時不會靜悄悄地略過）。

共用的合約案例在 ``takeoff_harness.WorkbookContract``。這裡只寫踢腳特有的：
材料欄要轉抄同列的「總計」，以及沒有開口的房間仍要佔一列。
"""

import unittest

import revit_stub
import takeoff_harness as harness
from takeoff_harness import (column_for_header, column_of, display,
                             read_sheets, row_of)


BUTTON = revit_stub.button_path('Takeoff.panel', 'Baseboard')

SECTION_ROW = 4  # build_sheet_values 的第四列，材料名稱與「總計」都在這一列
ROOM_WITHOUT_OPENING = {
    'element_id': 703, 'number': '103', 'name': '走廊', 'perimeter': 30.0,
    'baseboard': 'PVC', 'source_label': '主模型',
}


def _room(element_id, number, name, perimeter, baseboard):
    return {
        'element_id': element_id,
        'number': number,
        'name': name,
        'perimeter': perimeter,
        'baseboard': baseboard,
        'source_label': '主模型',
    }


def make_fixture(module):
    rooms = [
        _room(701, '101', '辦公室', 24.0, 'PVC'),
        _room(702, '102', '會議室', 18.0, 'ST'),
        dict(ROOM_WITHOUT_OPENING),
    ]
    openings_by_room = {
        701: [{'name': 'D1', 'width': 0.9},
              {'name': 'D1', 'width': 0.9},
              {'name': 'D2', 'width': 1.2}],
        702: [{'name': 'D1', 'width': 0.9}],
    }
    material_cols = ['PVC', 'ST']
    stats = {
        'rooms': len(rooms),
        'perimeter_boundary': 3,
        'perimeter_parameter': 0,
        'perimeter_missing': 0,
        'multi_loop_rooms': 0,
        'doors': 4,
        'door_room_deductions': 4,
        'skipped_no_width': 0,
        'skipped_no_host': 0,
        'skipped_no_room': 0,
        'skipped_not_boundary': 0,
        'baseboard_types': len(material_cols),
        'missing_baseboard': 0,
    }
    sources = [('host', '主模型', None, None, 0)]
    return rooms, openings_by_room, material_cols, stats, sources


class BaseboardAddressTests(harness.NoHandWrittenAddresses,
                            unittest.TestCase):
    """欄位字母只能由 SheetLayout 產生，不該再出現手寫的。"""

    BUTTON = BUTTON


class BaseboardWiringTests(harness.WorkbookContract, unittest.TestCase):
    BUTTON = BUTTON
    SEAM = 'collect_selected_sources'
    SHEET_COUNT = 1
    DONE_MARK = '踢腳 Excel 匯出完成'
    OUT_NAME = '踢腳.xlsx'

    def make_fixture(self, module):
        return make_fixture(module)

    def extra_patches(self, module):
        """族群符號、材料版選單、材料名稱 CSV：這三個都會碰外部世界。"""
        return {
            'collect_family_symbols_for_documents': lambda documents: {},
            'choose_material_family':
                lambda material_cols, families=None: ('踢腳材料版', families),
            'load_material_names':
                lambda: {'PVC': 'PVC 踢腳板', 'ST': '石材踢腳'},
            'load_material_names_from_family':
                lambda family_name, family_symbols, material_cols: {},
        }

    # -- 踢腳特有 ----------------------------------------------------------

    def read_sheet(self):
        with self.make_run() as run:
            run.run()
            self.module = run.module
        return read_sheets(self.outpath)[0]

    def test_material_column_formula_points_at_the_total_column(self):
        """材料欄轉抄同列的「總計」；欄位一搬動，寫死的字母就會指錯。"""
        sheet = self.read_sheet()
        total_col = column_for_header(sheet, SECTION_ROW, '總計')
        material_cols = [column_for_header(sheet, SECTION_ROW, name)
                         for name in ('PVC', 'ST')]

        found = 0
        for ref, cell in sheet.items():
            if column_of(ref) not in material_cols or not cell['f']:
                continue
            if row_of(ref) < self.module.FIRST_DATA_ROW:
                continue
            if harness.SUM_RANGE.match(cell['f']):
                continue
            found += 1
            self.assertEqual('{0}{1}'.format(total_col, row_of(ref)),
                             cell['f'],
                             '{0} 應該轉抄同一列的總計'.format(ref))
        self.assertGreaterEqual(found, 2, '沒有足夠的材料欄公式，斷言沒生效')

    def test_a_room_with_no_opening_still_gets_a_row(self):
        """沒有門的房間整段周長都要算；漏掉這一列不會報錯，只會少算。"""
        sheet = self.read_sheet()
        numbers = [display(cell) for ref, cell in sheet.items()
                   if column_of(ref) == 'A'
                   and row_of(ref) >= self.module.FIRST_DATA_ROW]
        self.assertIn(ROOM_WITHOUT_OPENING['number'], numbers)

    def test_repeated_openings_collapse_into_a_count(self):
        """同尺寸的門要併成一列帶數量，否則同一間房會多出重複列。

        欄位一律從表頭反推——測試自己寫死 'D'／'E' 的話，欄位一搬動這支就會
        以「按鈕壞了」的形式失敗，其實壞的是測試。2026-08-31 實際踩過。
        """
        sheet = self.read_sheet()
        header_row = self.module.FIRST_DATA_ROW - 1
        name_col = column_for_header(sheet, header_row, '名稱')
        count_col = column_for_header(sheet, header_row, '數量')

        first_room_rows = [
            row_of(ref) for ref, cell in sheet.items()
            if column_of(ref) == name_col and display(cell) == 'D1'
            and row_of(ref) >= self.module.FIRST_DATA_ROW]
        self.assertTrue(first_room_rows)
        counts = [display(sheet['{0}{1}'.format(count_col, row)])
                  for row in sorted(first_room_rows)]
        self.assertIn('2', counts, '101 房的兩扇 D1 沒有併成數量 2')


if __name__ == '__main__':
    unittest.main()
