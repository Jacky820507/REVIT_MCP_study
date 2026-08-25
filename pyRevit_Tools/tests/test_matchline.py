# -*- coding: utf-8 -*-
import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import matchline_logic as logic


PRIMARY = {'id': 100, 'name': 'B1F 平面圖', 'is_dependent': False,
           'primary_name': ''}
DEPENDENT = {'id': 101, 'name': 'B1F 平面圖 - A區', 'is_dependent': True,
             'primary_name': 'B1F 平面圖'}

VIEWS = [
    {'id': 1, 'name': 'B1F-A區', 'sheet_number': 'ARB-D02002'},
    {'id': 2, 'name': 'B1F-B區', 'sheet_number': 'ARB-D02003'},
    {'id': 3, 'name': 'B1F-C區', 'sheet_number': ''},
]


class MatchlineLogicTests(unittest.TestCase):
    def test_style_default_matches_the_csharp_contains_rule(self):
        names = ['細線', '中線', 'MCP 粗虛線', '粗實線']
        self.assertEqual(2, logic.default_index(names, logic.DEFAULT_LINE_STYLE))
        resolved, matched = logic.resolve_style(names, logic.DEFAULT_LINE_STYLE)
        self.assertEqual('MCP 粗虛線', resolved)
        self.assertTrue(matched)

    def test_style_falls_back_to_first_when_absent(self):
        names = ['細線', '中線']
        resolved, matched = logic.resolve_style(names, logic.DEFAULT_LINE_STYLE)
        self.assertEqual('細線', resolved)
        self.assertFalse(matched)

    def test_resolve_style_handles_empty_list(self):
        self.assertEqual((None, False), logic.resolve_style([], '粗虛線'))

    def test_style_names_use_default_when_collector_is_empty(self):
        self.assertEqual(
            ['Revit 預設文字型式'],
            logic.style_names_with_fallback([], 'Revit 預設文字型式'))

    def test_style_names_keep_collected_types_over_default(self):
        self.assertEqual(
            ['既有文字型式'],
            logic.style_names_with_fallback(['既有文字型式'], 'Revit 預設文字型式'))

    def test_style_match_ignores_spacing_and_width(self):
        names = ['微軟正黑體3.5mm']
        resolved, matched = logic.resolve_style(names, logic.DEFAULT_TEXT_STYLE)
        self.assertTrue(matched, resolved)

    def test_dependent_view_is_a_hard_stop(self):
        """domain: the command must run from the primary view."""
        blockers = logic.preflight_blockers(DEPENDENT, VIEWS)
        self.assertEqual(1, len(blockers))
        self.assertIn('母視圖', blockers[0])
        self.assertIn('B1F 平面圖', blockers[0])

    def test_no_dependent_views_is_a_hard_stop(self):
        blockers = logic.preflight_blockers(PRIMARY, [])
        self.assertEqual(1, len(blockers))
        self.assertIn('沒有任何從屬視圖', blockers[0])

    def test_primary_view_with_dependents_passes(self):
        self.assertEqual([], logic.preflight_blockers(PRIMARY, VIEWS))

    def test_unlabelled_views_are_split_out(self):
        labelled, unlabelled = logic.split_labelled(VIEWS)
        self.assertEqual(2, len(labelled))
        self.assertEqual(['B1F-C區'], [v['name'] for v in unlabelled])

    def test_preflight_warns_about_views_not_on_sheets(self):
        text = logic.preflight_text(
            PRIMARY, VIEWS, '粗虛線', '微軟正黑體 3.5 mm', 24, 48)
        self.assertIn('從屬視圖：3 個（已上圖紙 2／未上圖紙 1）', text)
        self.assertIn('24 條線、48 組文字', text)
        self.assertIn('ARB-D02002', text)
        self.assertIn('尚未放上圖紙', text)
        self.assertIn('B1F-C區', text)

    def test_preflight_has_no_warning_when_all_on_sheets(self):
        text = logic.preflight_text(
            PRIMARY, VIEWS[:2], '粗虛線', '微軟正黑體 3.5 mm', 0, 0)
        self.assertNotIn('尚未放上圖紙', text)

    def test_result_text_reports_deletions_and_creations(self):
        text = logic.result_text({
            'Success': True, 'DeletedLines': 24, 'DeletedTexts': 48,
            'CreatedMatchlines': 2, 'CreatedTexts': 4,
            'Details': [{'View1': 'ARB-D02002', 'View2': 'ARB-D02003'},
                        {'View1': 'ARB-D02003', 'View2': 'ARB-D02004'}],
        })
        self.assertIn('24 條線、48 組文字', text)
        self.assertIn('新建銜接線：2 條', text)
        self.assertIn('新建兩側文字：4 組', text)
        self.assertIn('ARB-D02002 ↔ ARB-D02003', text)

    def test_result_text_never_reports_suppressed_labels(self):
        text = logic.result_text({
            'Success': True, 'DeletedLines': 2, 'DeletedTexts': 4,
            'CreatedMatchlines': 2, 'CreatedTexts': 4,
            'SuppressedTextMatchlines': 1,
            'SuppressedGridTextMatchlines': 1,
            'SuppressedCrowdedTextMatchlines': 1,
            'Details': []})
        self.assertIn('新建兩側文字：4 組', text)
        self.assertNotIn('省略文字', text)

    def test_result_text_explains_a_zero_result(self):
        text = logic.result_text({
            'Success': True, 'DeletedLines': 0, 'DeletedTexts': 0,
            'CreatedMatchlines': 0, 'Details': []})
        self.assertIn('命令未回傳可用候選', text)

    def test_result_text_surfaces_command_failure(self):
        text = logic.result_text({
            'Success': False, 'Message': '該視圖沒有任何叢屬視圖 (Dependent Views)。'})
        self.assertIn('叢屬視圖', text)
        self.assertIn('沒有回傳結果', logic.result_text(None))

    def test_view_label_marks_missing_sheet(self):
        self.assertIn('（未上圖紙）', logic.view_label(VIEWS[2]))
        self.assertIn('ARB-D02002', logic.view_label(VIEWS[0]))


if __name__ == '__main__':
    unittest.main()
