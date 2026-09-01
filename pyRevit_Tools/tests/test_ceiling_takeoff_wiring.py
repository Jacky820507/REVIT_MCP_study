# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""真的執行「天花 Excel」的 ``main()``。

天花這顆比前幾顆多兩件事：材料版選單在**掃模型之前**就跳（所以取消時連
``collect_selected_sources`` 都不該被呼叫），以及它產的是兩個分頁——數量表加
一張「高度檢核」稽核表。兩者都靠共用的合約案例涵蓋，這裡只補分頁順序那一案。
"""

import unittest

import revit_stub
import takeoff_harness as harness
from takeoff_harness import column_for_header, read_sheets, row_of


BUTTON = revit_stub.button_path('Takeoff.panel', 'CeilingTakeoff')

SOURCES = [('host', '主模型', None, None, 0)]


def _room(number, name, code, area):
    return {
        'element_id': 1100 + int(number),
        'number': number,
        'name': name,
        'level': '1FL',
        'source_label': '主模型',
        'eligible_codes': [code],
        'quantity_area': area,
        'quantity_by_code': {code: area},
        'room_code': code,
        'ceiling_code': code,
        'height': 3.2,
    }


def make_fixture(module):
    rooms = [
        _room('101', '辦公室', 'C1', 48.0),
        _room('102', '會議室', 'C2', 24.0),
        _room('103', '走廊', 'C1', 18.0),
    ]
    material_cols = ['C1', 'C2']
    stats = {
        'rooms': len(rooms),
        'rooms_with_code': len(rooms),
        'ceilings': 5,
        'ceiling_finish_types': len(material_cols),
        'missing_ceiling_finish': 0,
        # 這兩個報告是用 len() 取的，型別是清單不是計數
        'room_code_missing_with_actual': [],
        'upper_ceiling_rejected_rooms': [],
        'slab_levels': 2,
    }
    return rooms, material_cols, stats, SOURCES


class CeilingTakeoffAddressTests(harness.NoHandWrittenAddresses,
                                 unittest.TestCase):
    """欄位字母只能由 SheetLayout 產生，不該再出現手寫的。"""

    BUTTON = BUTTON


class CeilingTakeoffWiringTests(harness.WorkbookContract, unittest.TestCase):
    BUTTON = BUTTON
    SEAM = 'collect_selected_sources'
    SHEET_COUNT = 2
    DONE_MARK = '天花 Excel 匯出完成'
    OUT_NAME = '天花.xlsx'

    def make_fixture(self, module):
        return make_fixture(module)

    def extra_patches(self, module):
        return {
            'takeoff_entry.iter_sources':
                lambda host_doc, options: list(SOURCES),
            'collect_family_symbols_for_documents': lambda documents: {},
            'choose_material_family':
                lambda families: ('天花材料版', families),
            'load_material_names_from_family':
                lambda family_name, family_symbols, material_cols: {
                    'C1': '礦纖天花', 'C2': '矽酸鈣板天花'},
        }

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
        """第二張是高度檢核稽核表；房間漏列在主表上看不出來。"""
        with self.make_run() as run:
            run.run()
        audit = read_sheets(self.outpath)[1]
        text = '\n'.join(harness.display(cell) for cell in audit.values())
        for number in ('101', '102', '103'):
            self.assertIn(number, text, '稽核表少了 {0} 房'.format(number))


if __name__ == '__main__':
    unittest.main()
