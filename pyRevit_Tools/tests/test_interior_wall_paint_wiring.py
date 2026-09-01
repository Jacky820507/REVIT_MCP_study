# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""真的執行「內牆粉刷 Excel」的 ``main()``。

形狀與踢腳那顆幾乎相同（``choose_options`` → ``collect_selected_sources`` →
材料版選單 → 產表），差別在多一個牆高欄位與開口帶高度。共用的合約案例在
``takeoff_harness.WorkbookContract``。
"""

import unittest

import revit_stub
import takeoff_harness as harness
from takeoff_harness import column_of, display, read_sheets, row_of


BUTTON = revit_stub.button_path('Takeoff.panel', 'InteriorWallPaint')

ROOM_WITHOUT_OPENING = {
    'element_id': 903, 'number': '103', 'name': '樓梯間', 'perimeter': 16.0,
    'height': 3.4, 'wall_finish': 'PT', 'source_label': '主模型',
}


def _room(element_id, number, name, perimeter, height, finish):
    return {
        'element_id': element_id,
        'number': number,
        'name': name,
        'perimeter': perimeter,
        'height': height,
        'wall_finish': finish,
        'source_label': '主模型',
    }


def make_fixture(module):
    rooms = [
        _room(901, '101', '辦公室', 24.0, 3.2, 'PT'),
        _room(902, '102', '會議室', 18.0, 3.2, 'WP'),
        dict(ROOM_WITHOUT_OPENING),
    ]
    openings_by_room = {
        901: [{'name': 'D1', 'width': 0.9, 'height': 2.1},
              {'name': 'D1', 'width': 0.9, 'height': 2.1},
              {'name': 'W1', 'width': 1.8, 'height': 1.2}],
        902: [{'name': 'D1', 'width': 0.9, 'height': 2.1}],
    }
    material_cols = ['PT', 'WP']
    # 這份 key 清單不是猜的：report 段落用 stats['x'] 直接取的每一個 key 都在
    # 這裡。少一個就會在 Excel 已經寫完之後才 KeyError，正是這支要擋的事故。
    stats = {
        'rooms': len(rooms),
        'perimeter_boundary': 3,
        'perimeter_parameter': 0,
        'perimeter_missing': 0,
        'multi_loop_rooms': 0,
        'openings': 4,
        'opening_room_deductions': 4,
        'skipped_no_size': 0,
        'skipped_no_host': 0,
        'skipped_no_room': 0,
        'skipped_not_boundary': 0,
        'wall_finish_types': len(material_cols),
        'missing_wall_finish': 0,
        'multi_wall_finish': 0,
        'height_bottom_ambiguous_rooms': 0,
        'height_bottom_fallback_rooms': 0,
        'height_bottom_detector_view': '',
        'height_detector': 'ray',
        'height_detector_view': '3D-檢討',
        'height_detector_updated': 3,
        'height_sources': {'ray-to-slab': 3},
        'slab_levels': 2,
    }
    sources = [('host', '主模型', None, None, 0)]
    return rooms, openings_by_room, material_cols, stats, sources


class InteriorWallPaintAddressTests(harness.NoHandWrittenAddresses,
                                    unittest.TestCase):
    """欄位字母只能由 SheetLayout 產生，不該再出現手寫的。"""

    BUTTON = BUTTON


class InteriorWallPaintWiringTests(harness.WorkbookContract,
                                   unittest.TestCase):
    BUTTON = BUTTON
    SEAM = 'collect_selected_sources'
    SHEET_COUNT = 1
    DONE_MARK = '內牆粉刷 Excel 匯出完成'
    OUT_NAME = '內牆粉刷.xlsx'

    def make_fixture(self, module):
        return make_fixture(module)

    def extra_patches(self, module):
        return {
            'collect_family_symbols_for_documents': lambda documents: {},
            'choose_material_family':
                lambda material_cols, families=None: ('粉刷材料版', families),
            'load_material_names':
                lambda: {'PT': '乳膠漆', 'WP': '壁布'},
            'load_material_names_from_family':
                lambda family_name, family_symbols, material_cols: {},
        }

    def read_sheet(self):
        with self.make_run() as run:
            run.run()
            self.module = run.module
        return read_sheets(self.outpath)[0]

    def test_a_room_with_no_opening_still_gets_a_row(self):
        sheet = self.read_sheet()
        numbers = [display(cell) for ref, cell in sheet.items()
                   if column_of(ref) == 'A'
                   and row_of(ref) >= self.module.FIRST_DATA_ROW]
        self.assertIn(ROOM_WITHOUT_OPENING['number'], numbers)


if __name__ == '__main__':
    unittest.main()
