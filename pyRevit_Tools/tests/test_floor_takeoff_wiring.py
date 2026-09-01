# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""真的執行「地坪 Excel」的 ``main()``。

地坪這顆的進入點跟其他幾顆不一樣——它把 ``main()`` 包在模組層的 ``try/except``
裡好把例外轉成對話框，所以 ``revit_stub.load_button`` 認得的是這種形狀。
另外它多一道「沒有有效房間就中止」的守衛，那條路單獨測（走不到寫檔，卻也不該
沉默地產出空表）。共用的合約案例在 ``takeoff_harness.WorkbookContract``。
"""

import os
import unittest

import revit_stub
import takeoff_harness as harness
from takeoff_harness import column_for_header, read_sheets, row_of


BUTTON = revit_stub.button_path('Takeoff.panel', 'FloorTakeoff')

SOURCES = [('host', '主模型', None, None, 0)]


def _room(number, name, code, area):
    return {
        'element_id': 1200 + int(number),
        'number': number,
        'name': name,
        'level': '1FL',
        'source_label': '主模型',
        'area': area,
        'regular_codes': [code],
        'quantity_by_code': {code: area},
        'warnings': [],
    }


def make_fixture(module):
    rooms = [
        _room('101', '辦公室', 'F1', 48.0),
        _room('102', '會議室', 'F2', 24.0),
        _room('103', '走廊', 'F1', 18.0),
    ]
    material_cols = ['F1', 'F2']
    stats = {
        'rooms': len(rooms),
        'rooms_with_code': len(rooms),
        'rooms_without_code': 0,
        'base_rooms': [],          # 報告用 len() 取，型別是清單
        'missing_material_codes': [],
    }
    return rooms, material_cols, stats, SOURCES


MATERIAL_DEFINITIONS = {
    'F1': {'name': '磁磚', 'code': 'F1'},
    'F2': {'name': '架高地板', 'code': 'F2'},
}


class FloorTakeoffAddressTests(harness.NoHandWrittenAddresses,
                               unittest.TestCase):
    """欄位字母只能由 SheetLayout 產生，不該再出現手寫的。"""

    BUTTON = BUTTON


class FloorTakeoffWiringTests(harness.WorkbookContract, unittest.TestCase):
    BUTTON = BUTTON
    SEAM = 'collect_selected_sources'
    SHEET_COUNT = 2
    DONE_MARK = '地坪 Excel 匯出完成'
    OUT_NAME = '地坪.xlsx'

    def make_fixture(self, module):
        return make_fixture(module)

    def extra_patches(self, module):
        return {
            'takeoff_entry.iter_sources':
                lambda host_doc, options: list(SOURCES),
            'collect_families_for_documents': lambda documents: {},
            'choose_material_family':
                lambda families: ('地坪材料版', families),
            'load_material_definitions':
                lambda family_name, families: dict(MATERIAL_DEFINITIONS),
        }

    # -- 地坪特有 ----------------------------------------------------------

    def test_no_eligible_room_stops_before_writing(self):
        """沒有有效房間就中止；沉默地產出一張空表比報錯更難發現。"""
        def empty(module):
            _rooms, cols, stats, sources = make_fixture(module)
            return [], cols, dict(stats, rooms=0), sources

        with self.make_run(fixture=empty) as run:
            run.run()
            self.assertTrue(run.stub.forms.alerts)
            self.assertIn('有效房間', run.stub.forms.alerts[-1])
        self.assertFalse(os.path.exists(self.outpath))

    def test_material_column_formula_points_at_the_area_column(self):
        """材料欄轉抄同列的「面積」；欄位一搬動，寫死的字母就會指錯。"""
        with self.make_run() as run:
            run.run()
            module = run.module
        sheet = read_sheets(self.outpath)[0]
        area_col = column_for_header(sheet, module.FIRST_DATA_ROW - 1, '面積')

        found = 0
        for ref, cell in sheet.items():
            if not cell['f'] or row_of(ref) < module.FIRST_DATA_ROW:
                continue
            if harness.SUM_RANGE.match(cell['f']):
                continue
            found += 1
            self.assertEqual('{0}{1}'.format(area_col, row_of(ref)),
                             cell['f'],
                             '{0} 應該轉抄同一列的面積'.format(ref))
        self.assertGreaterEqual(found, 1, '沒有材料欄公式，斷言沒生效')

    def test_audit_sheet_lists_every_room(self):
        with self.make_run() as run:
            run.run()
        audit = read_sheets(self.outpath)[1]
        text = '\n'.join(harness.display(cell) for cell in audit.values())
        for number in ('101', '102', '103'):
            self.assertIn(number, text, '稽核表少了 {0} 房'.format(number))


if __name__ == '__main__':
    unittest.main()
