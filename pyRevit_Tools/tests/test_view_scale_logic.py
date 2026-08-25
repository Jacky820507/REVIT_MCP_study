# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import view_scale_logic as logic


def view(name, scale=100, writable=logic.STATUS_OK, sheets=None):
    return {
        'id': abs(hash(name)) % 100000,
        'name': name,
        'scale': scale,
        'writable': writable,
        'view_type': u'FloorPlan',
        'sheet_numbers': sheets or [],
    }


class ParseScaleTests(unittest.TestCase):
    def test_plain_number(self):
        self.assertEqual(100, logic.parse_scale(u'100'))

    def test_ratio_forms(self):
        self.assertEqual(100, logic.parse_scale(u'1:100'))
        self.assertEqual(100, logic.parse_scale(u'1/100'))
        self.assertEqual(100, logic.parse_scale(u'1 : 100'))

    def test_fullwidth_input(self):
        self.assertEqual(100, logic.parse_scale(u'１：１００'))

    def test_rejects_out_of_range(self):
        self.assertIsNone(logic.parse_scale(u'0'))
        self.assertIsNone(logic.parse_scale(u'24001'))

    def test_rejects_nonsense(self):
        self.assertIsNone(logic.parse_scale(u''))
        self.assertIsNone(logic.parse_scale(None))
        self.assertIsNone(logic.parse_scale(u'abc'))
        self.assertIsNone(logic.parse_scale(u'2:100'))

    def test_boundaries_accepted(self):
        self.assertEqual(1, logic.parse_scale(u'1'))
        self.assertEqual(24000, logic.parse_scale(u'24000'))

    def test_label(self):
        self.assertEqual(u'1:100', logic.scale_label(100))
        self.assertEqual(u'(無)', logic.scale_label(0))
        self.assertEqual(u'(無)', logic.scale_label(None))


class DistributionTests(unittest.TestCase):
    def test_counts_group_by_scale_and_sort(self):
        records = [view(u'B', 200), view(u'A', 100), view(u'C', 100)]
        distribution = logic.scale_distribution(records)
        self.assertEqual([100, 200],
                         [entry['scale'] for entry in distribution])
        self.assertEqual(2, distribution[0]['count'])
        self.assertEqual([u'A', u'C'], distribution[0]['names'])

    def test_survey_flags_mixed_scales(self):
        text = logic.survey_lines([view(u'A', 100), view(u'B', 200)])
        self.assertIn(u'2 種比例', text)

    def test_survey_stays_quiet_when_uniform(self):
        text = logic.survey_lines([view(u'A', 100), view(u'B', 100)])
        self.assertNotIn(u'種比例', text)


class BuildPlanTests(unittest.TestCase):
    def test_only_differing_views_are_written(self):
        records = [view(u'A', 100), view(u'B', 200)]
        plan = logic.build_plan(records, u'100')
        self.assertEqual(1, len(plan['writes']))
        self.assertEqual(u'B', plan['writes'][0]['record']['name'])
        self.assertEqual(1, len(plan['already']))

    def test_blocked_views_never_reach_writes(self):
        records = [view(u'A', 200, writable=logic.BLOCK_TEMPLATE),
                   view(u'B', 200)]
        plan = logic.build_plan(records, u'100')
        self.assertEqual(1, len(plan['writes']))
        self.assertEqual(logic.BLOCK_TEMPLATE, plan['blocked'][0]['reason'])

    def test_accepts_ratio_target(self):
        plan = logic.build_plan([view(u'A', 50)], u'1:100')
        self.assertEqual(100, plan['target_scale'])
        self.assertEqual(100, plan['writes'][0]['new'])

    def test_invalid_target_is_rejected_before_any_write(self):
        self.assertRaises(ValueError, logic.build_plan, [view(u'A')], u'0')
        self.assertRaises(ValueError, logic.build_plan, [view(u'A')], u'abc')

    def test_missing_scale_counts_as_a_change(self):
        plan = logic.build_plan([view(u'A', None)], u'100')
        self.assertEqual(1, len(plan['writes']))
        self.assertEqual(0, plan['writes'][0]['old'])

    def test_summary_reports_both_directions(self):
        records = [view(u'A', 100), view(u'B', 200),
                   view(u'C', 200, writable=logic.BLOCK_READONLY)]
        text = logic.plan_lines(logic.build_plan(records, u'100'))
        self.assertIn(u'已經是目標比例、不動：1 個', text)
        self.assertIn(u'將變更 1 個視圖', text)
        self.assertIn(logic.BLOCK_READONLY, text)


class ViewportResyncTests(unittest.TestCase):
    """Changing a scale invalidates viewport titles keyed to the old one."""

    def test_sheets_behind_changed_views_are_listed_once(self):
        records = [view(u'A', 200, sheets=[u'A-101', u'A-102']),
                   view(u'B', 200, sheets=[u'A-101'])]
        plan = logic.build_plan(records, u'100')
        self.assertEqual([u'A-101', u'A-102'],
                         logic.sheets_needing_viewport_resync(plan))

    def test_unchanged_views_do_not_list_their_sheets(self):
        records = [view(u'A', 100, sheets=[u'A-101'])]
        plan = logic.build_plan(records, u'100')
        self.assertEqual([], logic.sheets_needing_viewport_resync(plan))


if __name__ == '__main__':
    unittest.main()
