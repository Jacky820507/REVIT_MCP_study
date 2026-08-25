# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import material_tools_logic as logic
import xlsx_xml


def room_record(room_id, surface, material_id, material_name, area,
                element_ids=None, **overrides):
    row = {
        u'room_id': room_id,
        u'level': u'4F',
        u'room_number': u'401',
        u'room_name': u'討論室',
        u'surface_kind': surface,
        u'material_id': material_id,
        u'material_name': material_name,
        u'material_source': u'face material',
        u'area_m2': area,
        u'face_count': 1,
        u'boundary_category': u'牆',
        u'boundary_element_ids': element_ids or [],
        u'method': u'GetMaterialArea',
        u'estimated': False,
        u'warnings': [],
    }
    row.update(overrides)
    return row


class FilterTests(unittest.TestCase):
    def setUp(self):
        self.materials = [
            {u'id': 1, u'name': u'木紋 WOOD', u'material_class': u'木材',
             u'usage_count': 2, u'type_reference_count': 0},
            {u'id': 2, u'name': u'玻璃', u'material_class': u'Glass',
             u'usage_count': 0, u'type_reference_count': 3},
            {u'id': 3, u'name': u'未使用材質', u'material_class': u'木材',
             u'usage_count': 0, u'type_reference_count': 0},
        ]

    def test_unicode_and_case_insensitive_search(self):
        self.assertEqual([self.materials[0]], logic.filter_materials(
            self.materials, u'ｗｏｏｄ'))
        self.assertEqual([self.materials[2]], logic.filter_materials(
            self.materials, u'未使用'))

    def test_used_includes_type_references(self):
        result = logic.filter_materials(self.materials, usage_filter='used')
        self.assertEqual([1, 2], [item[u'id'] for item in result])

    def test_unused_requires_both_counts_to_be_zero(self):
        result = logic.filter_materials(self.materials, usage_filter='unused')
        self.assertEqual([3], [item[u'id'] for item in result])

    def test_class_filter_is_unicode_case_insensitive(self):
        result = logic.filter_materials(self.materials, class_filter=u'ｇｌａｓｓ')
        self.assertEqual([2], [item[u'id'] for item in result])


class RenameTests(unittest.TestCase):
    def test_prefix_suffix_and_literal_replace(self):
        result = logic.build_rename_preview(
            [{u'id': 7, u'name': u'舊_牆面'}], prefix=u'P-', suffix=u'-S',
            find_text=u'舊_', replace_text=u'新_')
        self.assertEqual(u'P-新_牆面-S', result[u'items'][0][u'new_name'])
        self.assertEqual([], result[u'errors'])

    def test_empty_name_is_blocked(self):
        result = logic.build_rename_preview(
            [{u'id': 1, u'name': u'A'}], find_text=u'A', replace_text=u'')
        self.assertTrue(result[u'errors'])
        self.assertIn(u'空白', result[u'errors'][0])

    def test_duplicate_result_is_blocked_case_insensitively(self):
        result = logic.build_rename_preview([
            {u'id': 1, u'name': u'A-牆'},
            {u'id': 2, u'name': u'a-牆'},
        ], find_text=u'-牆', replace_text=u'')
        self.assertTrue(any(u'重名' in error for error in result[u'errors']))

    def test_project_name_conflict_excludes_selected_old_names(self):
        safe = logic.build_rename_preview(
            [{u'id': 1, u'name': u'A'}], prefix=u'X-', project_names=[u'A'])
        self.assertEqual([], safe[u'errors'])
        conflict = logic.build_rename_preview(
            [{u'id': 1, u'name': u'A'}], prefix=u'X-',
            project_names=[u'A', u'X-A'])
        self.assertTrue(any(u'未選取' in error
                            for error in conflict[u'errors']))

    def test_same_batch_swap_is_blocked(self):
        validation = logic.validate_rename_items([
            {u'id': 1, u'old_name': u'A', u'new_name': u'B'},
            {u'id': 2, u'old_name': u'B', u'new_name': u'A'},
        ], project_names=[u'A', u'B'])
        self.assertTrue(any(u'交換' in error
                            for error in validation[u'errors']))


class RoomGroupingTests(unittest.TestCase):
    def _records(self):
        return [
            room_record(101, u'wall', 10, u'白漆', 1.111111111,
                        [1001, 1002], face_count=2),
            room_record(101, u'wall', 10, u'白漆', 2.222222222,
                        [1002, 1003], face_count=3),
            room_record(101, u'floor', 20, u'木地板', 4.444444444,
                        [2001]),
            room_record(102, u'wall', 10, u'白漆', 5.555555555,
                        [1003, 1004], room_number=u'402', room_name=u'辦公室'),
            room_record(102, u'other', None, u'', 0.1256789,
                        [3001], room_number=u'402', room_name=u'辦公室',
                        material_source=u'unknown', method=u'fallback',
                        estimated=True),
        ]

    def test_surface_filtering(self):
        grouped = logic.group_room_records(
            self._records(), surface_keys=[u'wall'])
        self.assertEqual(set([u'wall']), set(
            [row[u'surface_kind'] for row in grouped[u'detail']]))
        self.assertAlmostEqual(8.888888888, grouped[u'total_area_m2'])

    def test_same_room_surface_material_source_and_method_merge(self):
        grouped = logic.group_room_records(self._records())
        rows = [row for row in grouped[u'detail']
                if row[u'room_id'] == 101 and row[u'material_id'] == 10]
        self.assertEqual(1, len(rows))
        self.assertAlmostEqual(3.333333333, rows[0][u'area_m2'])
        self.assertEqual(5, rows[0][u'face_count'])
        self.assertEqual([1001, 1002, 1003],
                         rows[0][u'boundary_element_ids'])

    def test_material_summary_crosses_rooms_and_deduplicates_elements(self):
        grouped = logic.group_room_records(self._records())
        summary = [row for row in grouped[u'materials']
                   if row[u'material_id'] == 10][0]
        self.assertEqual(2, summary[u'room_count'])
        self.assertEqual(6, summary[u'face_count'])
        self.assertEqual([1001, 1002, 1003, 1004],
                         summary[u'boundary_element_ids'])
        self.assertEqual([101, 102], summary[u'room_ids'])
        self.assertAlmostEqual(8.888888888, summary[u'area_m2'])

    def test_unknown_material_is_retained(self):
        grouped = logic.group_room_records(self._records())
        unknown = [row for row in grouped[u'detail']
                   if row[u'material_id'] is None]
        self.assertEqual(1, len(unknown))
        self.assertEqual(logic.UNKNOWN_MATERIAL_NAME,
                         unknown[0][u'material_name'])
        self.assertTrue(grouped[u'warnings'])

    def test_all_three_modes_reconcile_without_rounding(self):
        grouped = logic.group_room_records(self._records())
        detail_total = sum(row[u'area_m2'] for row in grouped[u'detail'])
        room_total = sum(row[u'total_area_m2'] for row in grouped[u'rooms'])
        material_total = sum(row[u'area_m2'] for row in grouped[u'materials'])
        self.assertEqual(detail_total, grouped[u'total_area_m2'])
        self.assertAlmostEqual(detail_total, room_total, places=12)
        self.assertAlmostEqual(detail_total, material_total, places=12)
        self.assertNotEqual(round(detail_total, 3), detail_total)

    def test_explicit_empty_surface_filter_returns_empty_views(self):
        grouped = logic.group_room_records(self._records(), surface_keys=[])
        self.assertEqual([], grouped[u'detail'])
        self.assertEqual([], grouped[u'rooms'])
        self.assertEqual([], grouped[u'materials'])
        self.assertEqual(0, grouped[u'total_area_m2'])


class WorkbookTests(unittest.TestCase):
    def test_material_workbook_names_headers_specs_and_xml_shape(self):
        sheets = logic.material_workbook(
            [{u'id': 1, u'name': u'白漆', u'usage_count': 2}],
            [{u'material_id': 1, u'material_name': u'白漆',
              u'element_id': 22, u'area_m2': 1.23456,
              u'source_kind': u'paint'}],
            [u'測試警告'])
        self.assertEqual([u'材質庫', u'使用元素', u'警告'],
                         [sheet[0] for sheet in sheets])
        self.assertEqual(u'材質 ID', sheets[0][1][0][0])
        self.assertIn(u'使用數', sheets[0][1][0])
        self.assertIn(u'面積 (m²)', sheets[1][1][0])
        self.assertEqual(1, sheets[0][2][u'freeze'])
        self.assertEqual(xlsx_xml.STYLE_DECIMAL,
                         sheets[1][2][u'formats'][9])
        self.assertEqual(xlsx_xml.STYLE_INT,
                         sheets[1][2][u'formats'][3])
        self.assertEqual(u'paint', sheets[1][1][1][7])
        usage_xml = xlsx_xml.sheet_xml(sheets[1][1], sheets[1][2])
        self.assertIn(u'r="I2" s="3"', usage_xml)
        self.assertIn(u'r="C2" s="2"', usage_xml)
        self.assertTrue(dict(xlsx_xml.workbook_parts(sheets)))

    def test_room_workbook_names_headers_rounding_and_specs(self):
        records = [room_record(1, u'wall', 5, u'白漆', 1.23456, [99],
                               material_class=u'Paint')]
        sheets = logic.room_workbook(records)
        self.assertEqual(
            [u'房間材質明細', u'依房間彙總', u'依材質彙總', u'警告'],
            [sheet[0] for sheet in sheets])
        self.assertIn(u'面積 (m²)', sheets[0][1][0])
        self.assertIn(u'合計 (m²)', sheets[1][1][0])
        self.assertIn(u'房間數', sheets[2][1][0])
        self.assertIn(u'房間 ID', sheets[2][1][0])
        self.assertEqual(1.235, sheets[0][1][1][8])
        self.assertEqual(xlsx_xml.STYLE_DECIMAL,
                         sheets[0][2][u'formats'][9])
        self.assertEqual(xlsx_xml.STYLE_DECIMAL,
                         sheets[1][2][u'formats'][9])
        self.assertEqual(xlsx_xml.STYLE_DECIMAL,
                         sheets[2][2][u'formats'][5])
        self.assertEqual(u'Paint', sheets[2][1][1][2])
        self.assertIn(u'r="I2" s="3"', xlsx_xml.sheet_xml(
            sheets[0][1], sheets[0][2]))
        self.assertIn(u'r="I2" s="3"', xlsx_xml.sheet_xml(
            sheets[1][1], sheets[1][2]))
        self.assertIn(u'r="E2" s="3"', xlsx_xml.sheet_xml(
            sheets[2][1], sheets[2][2]))
        self.assertEqual(1, sheets[2][2][u'freeze'])
        self.assertTrue(dict(xlsx_xml.workbook_parts(sheets)))

    def test_dict_warning_is_normalized_instead_of_using_python_repr(self):
        records = [room_record(
            1, u'wall', 5, u'白漆', 1.0, [99],
            warnings=[{u'source': u'face', u'message': u'boom'}])]
        grouped = logic.group_room_records(records)
        self.assertIn(u'boom', grouped[u'warnings'])
        self.assertFalse(any(u"'message'" in item
                             for item in grouped[u'warnings']))
        sheets = logic.room_workbook(records)
        self.assertEqual(u'boom', sheets[3][1][1][1])


if __name__ == '__main__':
    unittest.main()
