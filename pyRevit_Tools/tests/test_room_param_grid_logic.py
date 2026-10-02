# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import room_param_grid_logic as logic


COLUMNS = [
    {'key': 'id', 'header': logic.ID_HEADER, 'editable': False},
    {'key': 'level', 'header': logic.LEVEL_HEADER, 'editable': False},
    {'key': 'p0', 'header': u'名稱', 'editable': True},
    {'key': 'p1', 'header': u'面積', 'editable': False},
    {'key': 'p2', 'header': u'備註', 'editable': True},
]


class ClipboardTests(unittest.TestCase):
    def test_excel_trailing_newline_is_dropped(self):
        self.assertEqual(logic.parse_clipboard(u'a\tb\r\nc\td\r\n'),
                         [[u'a', u'b'], [u'c', u'd']])

    def test_inner_blank_line_is_kept(self):
        self.assertEqual(logic.parse_clipboard(u'a\n\nb\n'),
                         [[u'a'], [u''], [u'b']])

    def test_empty_clipboard_is_one_blank_cell(self):
        self.assertEqual(logic.parse_clipboard(u''), [[u'']])


class PasteTests(unittest.TestCase):
    def test_block_pastes_from_anchor_and_skips_readonly(self):
        writes, skipped = logic.paste_plan(
            [[u'A', u'X', u'B']], (0, 2), [(0, 2)], 3, COLUMNS)
        self.assertEqual(writes, [(0, 2, u'A'), (0, 4, u'B')])
        self.assertEqual(skipped, 1)

    def test_single_value_fills_every_selected_cell(self):
        selected = [(0, 2), (1, 2), (2, 2), (0, 1)]
        writes, skipped = logic.paste_plan(
            [[u'會議室']], (0, 1), selected, 3, COLUMNS)
        self.assertEqual(writes, [(0, 2, u'會議室'), (1, 2, u'會議室'),
                                  (2, 2, u'會議室')])
        self.assertEqual(skipped, 1)

    def test_block_is_clipped_at_table_edge(self):
        writes, unused = logic.paste_plan(
            [[u'a'], [u'b'], [u'c']], (1, 4), [(1, 4)], 2, COLUMNS)
        self.assertEqual(writes, [(1, 4, u'a')])

    def test_anchor_is_top_left_of_selection(self):
        self.assertEqual(logic.anchor_of([(3, 4), (1, 2), (2, 3)]), (1, 2))
        self.assertIsNone(logic.anchor_of([]))


class FillDownTests(unittest.TestCase):
    def test_top_value_fills_rest_of_column(self):
        values = {(0, 2): u'A', (1, 2): u'B', (2, 2): u'C'}
        writes, skipped = logic.fill_down_plan(
            [(2, 2), (0, 2), (1, 2)], lambda r, c: values[(r, c)], COLUMNS)
        self.assertEqual(writes, [(1, 2, u'A'), (2, 2, u'A')])
        self.assertEqual(skipped, 0)

    def test_readonly_column_is_not_filled(self):
        writes, skipped = logic.fill_down_plan(
            [(0, 3), (1, 3)], lambda r, c: u'9', COLUMNS)
        self.assertEqual(writes, [])
        self.assertEqual(skipped, 1)

    def test_single_cell_does_nothing(self):
        writes, unused = logic.fill_down_plan(
            [(0, 2)], lambda r, c: u'x', COLUMNS)
        self.assertEqual(writes, [])

    def test_clear_skips_readonly(self):
        writes, skipped = logic.clear_plan([(0, 2), (0, 3)], COLUMNS)
        self.assertEqual(writes, [(0, 2, u'')])
        self.assertEqual(skipped, 1)


class ChangeTests(unittest.TestCase):
    def test_only_editable_real_changes_count(self):
        original = {1: {'p0': u'A', 'p1': u'10', 'p2': u''}}
        rows = {1: {'p0': u'A ', 'p1': u'99', 'p2': u'新'}}
        result = logic.changes(rows, original, COLUMNS)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['header'], u'備註')
        self.assertEqual(result[0]['new'], u'新')
        self.assertEqual(logic.changed_count_by_room(result), {1: 1})


class ExcelTests(unittest.TestCase):
    def test_export_writes_id_as_number(self):
        rows = logic.export_rows(
            COLUMNS, [{'id': 7}],
            {7: {'level': u'1F', 'p0': u'A', 'p1': u'10 m²', 'p2': u''}})
        self.assertEqual(rows[0], [u'ElementId', u'樓層', u'名稱', u'面積',
                                   u'備註'])
        self.assertEqual(rows[1], [7, u'1F', u'A', u'10 m²', u''])

    def test_import_maps_by_header_and_id(self):
        sheet = [
            [u'ElementId', u'備註', u'面積', u'不存在', u'樓層'],
            [u'7', u'新備註', u'1', u'x', u'2F'],
            [u'8.0', u'', u'', u'', u''],
            [u'abc', u'z', u'', u'', u''],
            [u'', u'', u'', u'', u''],
        ]
        plan = logic.import_plan(sheet, COLUMNS, [7])
        self.assertEqual(plan['writes'], [(7, 'p2', u'新備註')])
        self.assertEqual(plan['unknown_ids'], [8])
        self.assertEqual(plan['bad_rows'], [4])
        self.assertEqual(plan['readonly_headers'], [u'面積'])
        self.assertEqual(plan['ignored_headers'], [u'不存在'])

    def test_import_short_row_blanks_missing_cells(self):
        plan = logic.import_plan(
            [[u'ElementId', u'名稱', u'備註'], [u'7', u'A']], COLUMNS, [7])
        self.assertEqual(plan['writes'], [(7, 'p0', u'A'), (7, 'p2', u'')])

    def test_import_without_id_column_is_an_error(self):
        plan = logic.import_plan([[u'名稱'], [u'A']], COLUMNS, [7])
        self.assertTrue(plan['error'])
        self.assertEqual(plan['writes'], [])


class LabelTests(unittest.TestCase):
    def test_yesno(self):
        self.assertEqual(logic.parse_yesno(u'是'), 1)
        self.assertEqual(logic.parse_yesno(u'Yes'), 1)
        self.assertEqual(logic.parse_yesno(u'0'), 0)
        self.assertIsNone(logic.parse_yesno(u'也許'))

    def test_room_label(self):
        self.assertEqual(logic.room_label(
            {'number': u'101', 'name': u'會議室', 'level': u'1F'}),
            u'101 會議室〔1F〕')
        self.assertIn(u'未放置', logic.room_label(
            {'number': u'', 'name': u'', 'level': u'', 'placed': False}))

    def test_sort_params_preferred_then_editable(self):
        infos = [{'name': u'面積', 'editable': False},
                 {'name': u'備註', 'editable': True},
                 {'name': u'名稱', 'editable': True},
                 {'name': u'編號', 'editable': True}]
        names = [info['name'] for info in
                 logic.sort_params(infos, (u'編號', u'名稱'))]
        self.assertEqual(names, [u'編號', u'名稱', u'備註', u'面積'])


if __name__ == '__main__':
    unittest.main()
