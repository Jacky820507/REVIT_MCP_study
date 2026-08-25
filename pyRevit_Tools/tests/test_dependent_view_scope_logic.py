# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import dependent_view_scope_logic as logic


class DependentViewScopeLogicTests(unittest.TestCase):
    def test_split_names_accepts_common_separators_and_deduplicates(self):
        self.assertEqual(
            ['A', 'B', 'C'],
            logic.split_names(' A, B;A\nC '))

    def test_canonicalize_names_is_case_insensitive(self):
        canonical, invalid = logic.canonicalize_names(
            ['b23', 'BE', 'missing'], ['B23', 'BE'])
        self.assertEqual(['B23', 'BE'], canonical)
        self.assertEqual(['missing'], invalid)

    def test_grid_settings_are_normalized_for_inline_ui_validation(self):
        settings, error = logic.validate_grid_settings(
            'b23', 'BE', '750', ['B23', 'BE'])
        self.assertIsNone(error)
        self.assertEqual(['B23'], settings['x_names'])
        self.assertEqual(['BE'], settings['y_names'])
        self.assertEqual(750.0, settings['offset_mm'])

    def test_grid_settings_report_all_common_validation_errors(self):
        settings, error = logic.validate_grid_settings(
            'missing', '', '500', ['B23'])
        self.assertIsNone(settings)
        self.assertIn('missing', error)

        settings, error = logic.validate_grid_settings('', '', '500', ['B23'])
        self.assertIsNone(settings)
        self.assertIn('至少', error)

        settings, error = logic.validate_grid_settings('B23', '', '-1', ['B23'])
        self.assertIsNone(settings)
        self.assertIn('不可小於 0', error)

    def test_batch_and_single_create_results_are_normalized(self):
        self.assertEqual(
            [{'NewViewName': 'A-1'}],
            logic.result_items([{'NewViewName': 'A-1'}]))
        self.assertEqual(
            [{'NewViewName': 'A-1'}],
            logic.result_items({'CreatedViews': [{'NewViewName': 'A-1'}]}))
        self.assertEqual(
            [{'NewViewName': 'A-1'}],
            logic.result_items({'Results': [{'NewViewName': 'A-1'}]}))

    def test_summary_reports_source_and_scope_box(self):
        summary = logic.result_summary(
            {'CreatedViews': [
                {'NewViewName': 'A-1', 'DeletedExistingViewIds': [10, 11]}
            ]},
            '複製指定母圖 CropBox', 1, '母圖 A', 'Scope 1', 4)
        self.assertIn('母圖 A', summary)
        self.assertIn('Scope 1', summary)
        self.assertIn('A-1', summary)
        self.assertIn('清除舊從屬視圖數：2', summary)
        self.assertIn('來源從屬視圖模板數：4', summary)


if __name__ == '__main__':
    unittest.main()
