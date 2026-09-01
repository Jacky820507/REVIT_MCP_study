# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""``sheet_layout`` 的單元測試。

這支要證的不是「函式會回傳字串」，而是 open-sheet 的那條前提：
**在欄位中間插一欄，所有公式要自己重解，不需要有人回頭改任何字母。**
``test_inserting_a_column_reresolves_every_formula`` 就是那一案。
"""

import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

from sheet_layout import SheetLayout, UnknownColumn, column_letter


COLUMNS = ['room_no', 'room_name', 'length', 'height', 'area', 'thickness']


def layout():
    return SheetLayout(COLUMNS, first_data_row=6, name='測試表')


class ColumnLetterTests(unittest.TestCase):
    def test_first_twenty_six(self):
        self.assertEqual('A', column_letter(0))
        self.assertEqual('Z', column_letter(25))

    def test_two_letter_columns(self):
        self.assertEqual('AA', column_letter(26))
        self.assertEqual('AB', column_letter(27))
        self.assertEqual('BA', column_letter(52))

    def test_negative_index_is_refused(self):
        self.assertRaises(ValueError, column_letter, -1)


class AddressTests(unittest.TestCase):
    def setUp(self):
        self.L = layout()

    def test_column_letters_follow_declaration_order(self):
        self.assertEqual('A', self.L.col('room_no'))
        self.assertEqual('C', self.L.col('length'))
        self.assertEqual('F', self.L.col('thickness'))

    def test_cell_and_range(self):
        self.assertEqual('C6', self.L.cell('length', 6))
        self.assertEqual('C6:C20', self.L.rng('length', 6, 20))

    def test_unknown_column_names_the_available_ones(self):
        try:
            self.L.col('lenght')
        except UnknownColumn as error:
            message = '{0}'.format(error)
        else:
            self.fail('打錯欄位名稱應該要拋錯')
        self.assertIn('lenght', message)
        self.assertIn('length', message, '錯誤訊息要列出可用欄位')
        self.assertIn('測試表', message)

    def test_duplicate_column_names_are_refused_at_construction(self):
        self.assertRaises(ValueError, SheetLayout, ['a', 'b', 'a'])


class FormulaTests(unittest.TestCase):
    def setUp(self):
        self.L = layout()

    def test_same_row_references(self):
        self.assertEqual('=C6*D6', self.L.formula(6, '{length}*{height}'))

    def test_row_offset_reference(self):
        self.assertEqual('=E6-E7', self.L.formula(6, '{area}-{area@1}'))
        self.assertEqual('=E6-E5', self.L.formula(6, '{area}-{area@-1}'))

    def test_range_reference(self):
        self.assertEqual('=SUM(E6:E20)',
                         self.L.formula(6, 'SUM({area:6:20})'))
        self.assertEqual('=SUM(E6:E20)', self.L.sum_of('area', 6, 20))

    def test_expr_leaves_the_equals_sign_off(self):
        self.assertEqual('C6*D6', self.L.expr(6, '{length}*{height}'))

    def test_string_concatenation_formula(self):
        self.assertEqual('="("&C6&"*"&D6&")"',
                         self.L.formula(6, '"("&{length}&"*"&{height}&")"'))

    def test_unknown_column_in_a_formula_is_refused(self):
        self.assertRaises(UnknownColumn, self.L.formula, 6, '{nope}*2')


class RowTests(unittest.TestCase):
    def setUp(self):
        self.L = layout()

    def test_blank_row_is_as_wide_as_the_layout(self):
        self.assertEqual(len(COLUMNS), len(self.L.blank_row()))

    def test_put_and_get_by_name(self):
        row = self.L.blank_row()
        self.L.put(row, 'length', 6.0)
        self.assertEqual(6.0, self.L.get(row, 'length'))
        self.assertEqual(6.0, row[2])

    def test_row_from_mapping_leaves_the_rest_blank(self):
        row = self.L.row_from({'room_no': '101', 'thickness': 0.15})
        self.assertEqual('101', row[0])
        self.assertEqual(0.15, row[5])
        self.assertEqual('', row[1])


class DynamicColumnTests(unittest.TestCase):
    def test_extra_columns_land_after_the_fixed_ones(self):
        full = layout().with_columns(['RC 15cm', 'RC 25cm'])
        self.assertEqual(len(COLUMNS) + 2, full.width)
        self.assertEqual('G', full.col('RC 15cm'))
        self.assertEqual('H6', full.cell('RC 25cm', 6))

    def test_the_base_layout_is_not_mutated(self):
        base = layout()
        base.with_columns(['RC 15cm'])
        self.assertFalse(base.has('RC 15cm'))


class ReResolutionTests(unittest.TestCase):
    """整支 sheet_layout 存在的理由。"""

    def test_inserting_a_column_reresolves_every_formula(self):
        before = SheetLayout(COLUMNS)
        after = SheetLayout(
            ['room_no', 'room_name', 'zone', 'length', 'height', 'area',
             'thickness'])

        template = '{length}*{height}'
        self.assertEqual('=C6*D6', before.formula(6, template))
        # 中間插了 zone 之後，同一段模板自己指到新的位置——沒有任何一個字母
        # 需要有人回頭改。
        self.assertEqual('=D6*E6', after.formula(6, template))

    def test_appending_a_type_column_does_not_move_the_fixed_ones(self):
        base = SheetLayout(COLUMNS)
        full = base.with_columns(['TYPE-A'])
        self.assertEqual(base.col('thickness'), full.col('thickness'))


if __name__ == '__main__':
    unittest.main()
