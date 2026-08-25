# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import group_height_logic as logic


def group(group_id, type_id=100, type_name=u'標準層A戶', level_id=10,
          level=u'2F', level_elevation=3000.0, offset=0.0,
          bottom=None, top=None, next_level=None, members=12):
    """One placed model group instance, as the button hands it over."""
    if bottom is None:
        bottom = level_elevation
    if top is None:
        top = level_elevation + 2800.0
    return {
        'id': group_id,
        'type_id': type_id,
        'type_name': type_name,
        'level_id': level_id,
        'level': level,
        'level_elevation_mm': level_elevation,
        'offset_mm': offset,
        'bottom_mm': bottom,
        'top_mm': top,
        'next_level_elevation_mm': next_level,
        'member_count': members,
    }


class ExpectedOffsetTests(unittest.TestCase):
    def test_all_agreeing_gives_that_offset(self):
        rows = [group(1), group(2), group(3)]
        expected = logic.expected_offsets(rows)
        self.assertEqual((0.0, True), expected[100])

    def test_majority_wins(self):
        rows = [group(1), group(2), group(3, offset=300.0)]
        offset, decided = logic.expected_offsets(rows)[100]
        self.assertTrue(decided)
        self.assertAlmostEqual(0.0, offset, 3)

    def test_a_tie_decides_nothing(self):
        """Two at 0 and two at 300 — blaming either half would be a guess."""
        rows = [group(1), group(2), group(3, offset=300.0),
                group(4, offset=300.0)]
        offset, decided = logic.expected_offsets(rows)[100]
        self.assertFalse(decided)

    def test_types_are_independent(self):
        rows = [group(1, type_id=100, offset=0.0),
                group(2, type_id=100, offset=0.0),
                group(3, type_id=200, offset=500.0),
                group(4, type_id=200, offset=500.0)]
        expected = logic.expected_offsets(rows)
        self.assertAlmostEqual(0.0, expected[100][0], 3)
        self.assertAlmostEqual(500.0, expected[200][0], 3)

    def test_float_noise_does_not_split_a_majority(self):
        rows = [group(1, offset=0.0), group(2, offset=0.0000001),
                group(3, offset=-0.0000001)]
        offset, decided = logic.expected_offsets(rows)[100]
        self.assertTrue(decided)

    def test_single_instance_is_its_own_expectation(self):
        offset, decided = logic.expected_offsets([group(1, offset=250.0)])[100]
        self.assertTrue(decided)
        self.assertAlmostEqual(250.0, offset, 3)


class OffsetFlagTests(unittest.TestCase):
    def test_the_odd_one_out_is_flagged(self):
        rows = [group(1), group(2), group(3, offset=300.0)]
        report = logic.analyze(rows)
        flagged = dict((item['id'], item['flags']) for item in report['rows'])
        self.assertEqual([], flagged[1])
        self.assertEqual([], flagged[2])
        self.assertIn(logic.FLAG_OFFSET_MISMATCH, flagged[3])

    def test_a_split_type_flags_everyone_without_naming_a_culprit(self):
        rows = [group(1), group(2), group(3, offset=300.0),
                group(4, offset=300.0)]
        report = logic.analyze(rows)
        for item in report['rows']:
            self.assertIn(logic.FLAG_OFFSET_SPLIT, item['flags'])
            self.assertNotIn(logic.FLAG_OFFSET_MISMATCH, item['flags'])

    def test_consistent_nonzero_offset_is_fine_by_default(self):
        """Some projects place every instance at an offset on purpose."""
        rows = [group(1, offset=150.0), group(2, offset=150.0)]
        report = logic.analyze(rows)
        self.assertEqual([], report['flagged_ids'])

    def test_nonzero_offset_can_be_asked_about(self):
        rows = [group(1, offset=150.0), group(2, offset=150.0)]
        report = logic.analyze(rows, flag_nonzero=True)
        self.assertEqual(2, report['counts'][logic.FLAG_OFFSET_NONZERO])

    def test_tolerance_absorbs_a_tiny_difference(self):
        rows = [group(1, offset=0.0), group(2, offset=0.0), group(3,
                                                                  offset=0.4)]
        self.assertEqual([], logic.analyze(rows, tolerance_mm=1.0)
                         ['flagged_ids'])
        self.assertEqual([3], logic.analyze(rows, tolerance_mm=0.1)
                         ['flagged_ids'])


class ExtentTests(unittest.TestCase):
    def test_content_poking_above_the_next_level_is_flagged(self):
        rows = [group(1, level_elevation=3000.0, bottom=3000.0, top=6200.0,
                      next_level=6000.0)]
        report = logic.analyze(rows)
        self.assertIn(logic.FLAG_ABOVE_NEXT_LEVEL, report['rows'][0]['flags'])

    def test_content_fitting_under_the_next_level_is_fine(self):
        rows = [group(1, level_elevation=3000.0, bottom=3000.0, top=5800.0,
                      next_level=6000.0)]
        self.assertEqual([], logic.analyze(rows)['flagged_ids'])

    def test_top_level_without_a_next_level_is_not_flagged(self):
        rows = [group(1, level_elevation=3000.0, bottom=3000.0, top=9999.0,
                      next_level=None)]
        self.assertEqual([], logic.analyze(rows)['flagged_ids'])

    def test_missing_geometry_is_reported_not_guessed(self):
        rows = [group(1, bottom=None, top=None)]
        rows[0]['bottom_mm'] = None
        rows[0]['top_mm'] = None
        report = logic.analyze(rows)
        self.assertIn(logic.FLAG_NO_GEOMETRY, report['rows'][0]['flags'])
        self.assertIsNone(report['rows'][0]['content_height_mm'])

    def test_relative_extents_are_measured_from_the_level(self):
        rows = [group(1, level_elevation=3000.0, bottom=3050.0, top=5850.0)]
        item = logic.analyze(rows)['rows'][0]
        self.assertAlmostEqual(50.0, item['relative_bottom_mm'], 3)
        self.assertAlmostEqual(2850.0, item['relative_top_mm'], 3)
        self.assertAlmostEqual(2800.0, item['content_height_mm'], 3)


class LevelTests(unittest.TestCase):
    def test_group_without_a_level_is_flagged(self):
        rows = [group(1, level_id=-1, level=u'')]
        report = logic.analyze(rows)
        self.assertIn(logic.FLAG_NO_LEVEL, report['rows'][0]['flags'])

    def test_no_level_outranks_other_flags_in_the_headline(self):
        rows = [group(1, level_id=-1, offset=300.0), group(2), group(3)]
        item = [row for row in logic.analyze(rows)['rows']
                if row['id'] == 1][0]
        self.assertEqual(logic.FLAG_NO_LEVEL, logic.headline_flag(item))

    def test_headline_of_a_clean_row_is_empty(self):
        self.assertEqual(u'', logic.headline_flag({'flags': []}))
        self.assertEqual(u'', logic.headline_flag({}))


class GroupingTests(unittest.TestCase):
    def test_rows_are_grouped_by_type(self):
        rows = [group(1, type_id=100, type_name=u'A'),
                group(2, type_id=200, type_name=u'B'),
                group(3, type_id=100, type_name=u'A')]
        report = logic.analyze(rows)
        self.assertEqual(2, len(report['types']))
        names = [entry['type_name'] for entry in report['types']]
        self.assertEqual([u'A', u'B'], names)

    def test_rows_sort_by_type_then_elevation(self):
        rows = [group(1, type_name=u'A', level_elevation=6000.0),
                group(2, type_name=u'A', level_elevation=0.0),
                group(3, type_name=u'A', level_elevation=3000.0)]
        report = logic.analyze(rows)
        self.assertEqual([2, 3, 1], [item['id'] for item in report['rows']])

    def test_empty_input(self):
        report = logic.analyze([])
        self.assertEqual(0, report['total'])
        self.assertEqual([], report['flagged_ids'])
        self.assertIn(u'沒有發現高度異常', logic.report_lines(report))


class ReportTests(unittest.TestCase):
    def test_clean_model_says_so(self):
        text = logic.report_lines(logic.analyze([group(1), group(2)]))
        self.assertIn(u'沒有發現高度異常', text)

    def test_mismatch_is_named_with_the_majority_offset(self):
        rows = [group(1), group(2), group(3, offset=300.0, level=u'4F')]
        text = logic.report_lines(logic.analyze(rows))
        self.assertIn(u'1 個實例有問題', text)
        self.assertIn(logic.FLAG_OFFSET_MISMATCH, text)
        self.assertIn(u'多數偏移 0 mm', text)
        self.assertIn(u'4F', text)

    def test_split_type_is_described_as_split(self):
        rows = [group(1), group(2), group(3, offset=300.0),
                group(4, offset=300.0)]
        text = logic.report_lines(logic.analyze(rows))
        self.assertIn(u'偏移分歧', text)


if __name__ == '__main__':
    unittest.main()
