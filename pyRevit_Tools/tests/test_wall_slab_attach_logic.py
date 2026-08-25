# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import wall_slab_attach_logic as logic


def slab(slab_id=1, min_x=0.0, min_y=0.0, max_x=10000.0, max_y=10000.0,
         bottom_z=3000.0, top_z=3200.0, category=u'樓板'):
    return {
        'id': slab_id,
        'min_x': min_x, 'min_y': min_y, 'max_x': max_x, 'max_y': max_y,
        'bottom_z': bottom_z, 'top_z': top_z,
        'category': category,
    }


def wall(wall_id=1, **overrides):
    """A wall from 0 to 3000, sitting exactly under the default slab."""
    record = {
        'id': wall_id,
        'name': u'',
        'type_name': u'RC-200',
        'level': u'1F',
        'is_curtain': False,
        'is_stacked_member': False,
        'top_attached': False,
        'bottom_attached': False,
        'top_z': 3000.0,
        'bottom_z': 0.0,
        'samples': [(1000.0, 1000.0), (2000.0, 1000.0), (3000.0, 1000.0)],
    }
    record.update(overrides)
    return record


class SampleParamTests(unittest.TestCase):
    def test_a_short_wall_still_gets_the_minimum_three_points(self):
        params = logic.sample_params(500.0)
        self.assertEqual(logic.MIN_SAMPLES, len(params))

    def test_a_long_wall_gets_a_point_roughly_every_metre(self):
        params = logic.sample_params(10000.0)
        self.assertEqual(11, len(params))

    def test_a_very_long_wall_is_capped(self):
        """Otherwise a 200 m wall costs 200 slab lookups for no extra truth."""
        self.assertEqual(logic.MAX_SAMPLES,
                         len(logic.sample_params(200000.0)))

    def test_points_stay_inside_the_wall(self):
        for length in (500.0, 5000.0, 200000.0):
            params = logic.sample_params(length)
            self.assertGreater(params[0], 0.0)
            self.assertLess(params[-1], 1.0)

    def test_points_are_ordered_and_span_the_wall(self):
        params = logic.sample_params(5000.0)
        self.assertEqual(sorted(params), params)
        self.assertAlmostEqual(logic.END_INSET, params[0], 9)
        self.assertAlmostEqual(1.0 - logic.END_INSET, params[-1], 9)

    def test_a_zero_length_wall_does_not_divide_by_zero(self):
        self.assertEqual(logic.MIN_SAMPLES, len(logic.sample_params(0.0)))

    def test_spacing_can_be_tightened(self):
        loose = logic.sample_params(10000.0, 2000.0)
        tight = logic.sample_params(10000.0, 500.0)
        self.assertLess(len(loose), len(tight))


class IndexTests(unittest.TestCase):
    def test_a_point_inside_the_slab_finds_it(self):
        index = logic.build_slab_index([slab()])
        self.assertEqual(1, len(logic.slabs_at(index, 5000.0, 5000.0)))

    def test_a_point_in_the_same_cell_but_outside_the_slab_does_not(self):
        """Cell membership is a filter, not the answer."""
        index = logic.build_slab_index([slab(max_x=1000.0, max_y=1000.0)])
        # Same 5 m cell as the slab, but past its edge.
        self.assertEqual([], logic.slabs_at(index, 2000.0, 500.0))

    def test_a_slab_spanning_many_cells_is_found_from_all_of_them(self):
        index = logic.build_slab_index([slab(max_x=40000.0, max_y=40000.0)])
        for x, y in ((100.0, 100.0), (20000.0, 20000.0), (39000.0, 39000.0)):
            self.assertEqual(1, len(logic.slabs_at(index, x, y)),
                             u'({}, {}) 找不到樓板'.format(x, y))

    def test_negative_coordinates_index_correctly(self):
        """Floor division on negatives is the classic off-by-one here."""
        index = logic.build_slab_index(
            [slab(min_x=-20000.0, min_y=-20000.0, max_x=-1000.0,
                  max_y=-1000.0)])
        self.assertEqual(1, len(logic.slabs_at(index, -10000.0, -10000.0)))
        self.assertEqual([], logic.slabs_at(index, 10000.0, 10000.0))

    def test_slabs_without_a_box_are_dropped_not_crashed_on(self):
        index = logic.build_slab_index([{'id': 9, 'bottom_z': 3000.0}])
        self.assertEqual({}, index)


class GapTests(unittest.TestCase):
    def _index(self, *slabs):
        return logic.build_slab_index(list(slabs) or [slab()])

    def test_flush_wall_top_reports_zero_gap(self):
        gap, found = logic.gap_above(self._index(), 1000.0, 1000.0, 3000.0)
        self.assertAlmostEqual(0.0, gap, 6)
        self.assertEqual(1, found['id'])

    def test_short_wall_reports_a_positive_gap(self):
        gap, unused = logic.gap_above(self._index(), 1000.0, 1000.0, 2800.0)
        self.assertAlmostEqual(200.0, gap, 6)

    def test_wall_poking_into_the_slab_reports_a_negative_gap(self):
        gap, unused = logic.gap_above(self._index(), 1000.0, 1000.0, 3100.0)
        self.assertAlmostEqual(-100.0, gap, 6)

    def test_a_slab_far_below_the_wall_top_is_not_this_wall_s_slab(self):
        """Otherwise a 2F wall matches the 1F slab it stands on."""
        gap, found = logic.gap_above(self._index(), 1000.0, 1000.0, 6000.0)
        self.assertIsNone(gap)
        self.assertIsNone(found)

    def test_the_lowest_slab_above_wins(self):
        index = self._index(slab(1, bottom_z=3000.0),
                            slab(2, bottom_z=6000.0))
        gap, found = logic.gap_above(index, 1000.0, 1000.0, 2900.0)
        self.assertEqual(1, found['id'])
        self.assertAlmostEqual(100.0, gap, 6)

    def test_no_slab_over_the_point_reports_nothing(self):
        index = self._index(slab(max_x=500.0, max_y=500.0))
        gap, found = logic.gap_above(index, 3000.0, 3000.0, 3000.0)
        self.assertIsNone(gap)
        self.assertIsNone(found)

    def test_base_gap_is_measured_from_the_slab_top(self):
        index = self._index(slab(bottom_z=-200.0, top_z=0.0))
        gap, unused = logic.gap_below(index, 1000.0, 1000.0, 0.0)
        self.assertAlmostEqual(0.0, gap, 6)

    def test_a_floating_wall_base_reports_a_positive_gap(self):
        index = self._index(slab(bottom_z=-200.0, top_z=0.0))
        gap, unused = logic.gap_below(index, 1000.0, 1000.0, 150.0)
        self.assertAlmostEqual(150.0, gap, 6)

    def test_the_highest_slab_below_wins(self):
        index = self._index(slab(1, bottom_z=-3200.0, top_z=-3000.0),
                            slab(2, bottom_z=-200.0, top_z=0.0))
        gap, found = logic.gap_below(index, 1000.0, 1000.0, 100.0)
        self.assertEqual(2, found['id'])


class ClassifyTests(unittest.TestCase):
    def test_attached_and_flush_is_the_clean_case(self):
        self.assertEqual(logic.STATE_OK, logic.classify(True, 0.0))

    def test_attached_but_off_is_reported(self):
        self.assertEqual(logic.STATE_ATTACHED_OFF,
                         logic.classify(True, 400.0))

    def test_unattached_but_flush_is_still_a_finding(self):
        """It works today and breaks the moment the slab moves."""
        self.assertEqual(logic.STATE_FLUSH_ONLY, logic.classify(False, 0.0))

    def test_unattached_with_a_gap(self):
        self.assertEqual(logic.STATE_GAP, logic.classify(False, 200.0))

    def test_unattached_and_embedded(self):
        self.assertEqual(logic.STATE_EMBEDDED, logic.classify(False, -100.0))

    def test_an_unreadable_flag_is_its_own_state_not_a_defect(self):
        """A failed parameter read must not become a 「未貼附」 finding."""
        self.assertEqual(logic.STATE_UNKNOWN, logic.classify(None, 0.0))
        self.assertEqual(logic.STATE_UNKNOWN, logic.classify(None, 500.0))
        self.assertNotIn(logic.STATE_UNKNOWN, logic.PROBLEM_STATES)

    def test_no_slab_at_all(self):
        self.assertEqual(logic.STATE_NO_SLAB, logic.classify(False, None))
        self.assertEqual(logic.STATE_NO_SLAB, logic.classify(True, None))

    def test_within_tolerance_counts_as_flush_on_both_signs(self):
        self.assertEqual(logic.STATE_FLUSH_ONLY, logic.classify(False, 4.0))
        self.assertEqual(logic.STATE_FLUSH_ONLY, logic.classify(False, -4.0))

    def test_exactly_on_the_tolerance_is_flush(self):
        self.assertEqual(logic.STATE_FLUSH_ONLY, logic.classify(False, 5.0))

    def test_just_past_the_tolerance_is_not(self):
        self.assertEqual(logic.STATE_GAP, logic.classify(False, 5.1))


class ExamineEndTests(unittest.TestCase):
    def _run(self, record, slabs=None, **options):
        index = logic.build_slab_index(slabs or [slab()])
        opts = {'cell_mm': logic.DEFAULT_CELL_MM,
                'penetration_mm': logic.DEFAULT_PENETRATION_MM,
                'flush_tol_mm': logic.DEFAULT_FLUSH_TOL_MM,
                'ignore_gap_mm': logic.DEFAULT_IGNORE_GAP_MM}
        opts.update(options)
        return logic.examine_end(record, index, logic.END_TOP, opts)

    def test_a_flush_unattached_wall(self):
        entry = self._run(wall())
        self.assertEqual(logic.STATE_FLUSH_ONLY, entry['state'])
        self.assertEqual(3, entry['covered'])
        self.assertEqual([], entry['flags'])

    def test_the_worst_sample_decides_the_verdict(self):
        """A wall is only as good as its worst point.

        Two samples sit under the 3000 slab; the third runs under a slab that
        is 300 higher, so a third of this wall has a hole over it.
        """
        slabs = [slab(1, max_x=2500.0, bottom_z=3000.0),
                 slab(2, min_x=2500.0, bottom_z=3300.0, top_z=3500.0)]
        entry = self._run(wall(), slabs)
        self.assertEqual(logic.STATE_GAP, entry['state'])
        self.assertAlmostEqual(300.0, entry['worst_gap_mm'], 6)

    def test_a_deeper_penetration_outranks_a_smaller_gap(self):
        slabs = [slab(1, max_x=2500.0, bottom_z=3050.0),
                 slab(2, min_x=2500.0, bottom_z=2600.0, top_z=2800.0)]
        entry = self._run(wall(), slabs)
        self.assertAlmostEqual(-400.0, entry['worst_gap_mm'], 6)
        self.assertEqual(logic.STATE_EMBEDDED, entry['state'])

    def test_a_wall_running_past_the_slab_edge_is_flagged_partial(self):
        entry = self._run(wall(), [slab(max_x=2500.0)])
        self.assertIn(logic.FLAG_PARTIAL, entry['flags'])
        self.assertEqual(2, entry['covered'])
        self.assertEqual(3, entry['sample_count'])

    def test_full_coverage_is_not_flagged_partial(self):
        self.assertEqual([], self._run(wall())['flags'])

    def test_no_coverage_at_all_is_not_flagged_partial(self):
        """Nothing above the whole wall is 「無樓板」, not 「部分無樓板」."""
        entry = self._run(wall(), [slab(min_x=50000.0, max_x=60000.0)])
        self.assertEqual([], entry['flags'])
        self.assertEqual(logic.STATE_NO_SLAB, entry['state'])

    def test_a_low_wall_far_under_a_slab_is_not_called_defective(self):
        """A 1200 高矮牆 under a 3000 slab is a railing, not a missing attach."""
        entry = self._run(wall(top_z=1200.0))
        self.assertEqual(logic.STATE_NO_SLAB, entry['state'])

    def test_lowering_the_ignore_threshold_brings_it_back(self):
        entry = self._run(wall(top_z=1200.0), ignore_gap_mm=5000.0)
        self.assertEqual(logic.STATE_GAP, entry['state'])
        self.assertAlmostEqual(1800.0, entry['worst_gap_mm'], 6)

    def test_the_slab_category_met_is_reported(self):
        entry = self._run(wall(), [slab(category=u'屋頂')])
        self.assertEqual([u'屋頂'], entry['slab_categories'])


class AnalyzeTests(unittest.TestCase):
    def test_curtain_walls_are_skipped_with_a_reason(self):
        result = logic.analyze([wall(1, is_curtain=True)], [slab()])
        self.assertEqual([], result['rows'])
        self.assertEqual(logic.SKIP_CURTAIN, result['skipped'][0]['reason'])

    def test_stacked_wall_members_are_skipped(self):
        result = logic.analyze([wall(1, is_stacked_member=True)], [slab()])
        self.assertEqual(logic.SKIP_STACKED_MEMBER,
                         result['skipped'][0]['reason'])

    def test_a_wall_without_geometry_is_skipped_not_guessed_at(self):
        result = logic.analyze([wall(1, top_z=None)], [slab()])
        self.assertEqual(logic.SKIP_NO_GEOMETRY,
                         result['skipped'][0]['reason'])

    def test_base_is_not_checked_unless_asked(self):
        result = logic.analyze([wall()], [slab()])
        self.assertEqual([logic.END_TOP],
                         [entry['end'] for entry in result['rows'][0]['ends']])

    def test_both_ends_when_asked(self):
        result = logic.analyze([wall()], [slab()], {'check_base': True})
        self.assertEqual([logic.END_TOP, logic.END_BASE],
                         [entry['end'] for entry in result['rows'][0]['ends']])

    def test_a_wall_is_flagged_if_either_end_has_a_problem(self):
        slabs = [slab(1, bottom_z=3000.0, top_z=3200.0),
                 slab(2, bottom_z=-200.0, top_z=0.0)]
        # Top attached and flush; base floating 150 above its slab.
        record = wall(top_attached=True, bottom_z=150.0)
        result = logic.analyze([record], slabs, {'check_base': True})
        item = result['rows'][0]
        self.assertEqual(logic.STATE_OK, item['ends'][0]['state'])
        self.assertEqual(logic.STATE_GAP, item['ends'][1]['state'])
        self.assertTrue(item['problem'])
        self.assertEqual([1], result['flagged_ids'])

    def test_a_wall_whose_flag_cannot_be_read_is_reported_not_accused(self):
        result = logic.analyze([wall(top_attached=None)], [slab()])
        self.assertEqual(logic.STATE_UNKNOWN,
                         result['rows'][0]['ends'][0]['state'])
        self.assertEqual([], result['flagged_ids'])

    def test_a_clean_wall_is_not_flagged(self):
        result = logic.analyze([wall(top_attached=True)], [slab()])
        self.assertFalse(result['rows'][0]['problem'])
        self.assertEqual([], result['flagged_ids'])
        self.assertFalse(logic.has_problem(result))

    def test_walls_with_no_slab_are_not_treated_as_defects(self):
        result = logic.analyze([wall()], [slab(min_x=50000.0,
                                               max_x=60000.0)])
        self.assertEqual([], result['flagged_ids'])

    def test_rows_come_back_worst_first(self):
        slabs = [slab()]
        records = [
            wall(1, top_attached=True),                    # OK
            wall(2, top_z=2800.0),                         # GAP
            wall(3),                                       # FLUSH_ONLY
        ]
        result = logic.analyze(records, slabs)
        self.assertEqual([2, 3, 1], [item['id'] for item in result['rows']])

    def test_counts_are_per_end_not_per_wall(self):
        result = logic.analyze(
            [wall(top_attached=True, bottom_attached=True, bottom_z=0.0)],
            [slab(1, bottom_z=3000.0, top_z=3200.0),
             slab(2, bottom_z=-200.0, top_z=0.0)],
            {'check_base': True})
        self.assertEqual(2, result['counts'][logic.STATE_OK])

    def test_headline_state_takes_the_worse_of_two_ends(self):
        item = {'states': [logic.STATE_OK, logic.STATE_GAP]}
        self.assertEqual(logic.STATE_GAP, logic.headline_state(item))

    def test_empty_input_is_a_clean_empty_result(self):
        result = logic.analyze([], [])
        self.assertEqual(0, result['total'])
        self.assertFalse(logic.has_problem(result))

    def test_options_are_not_mutated_for_the_caller(self):
        options = {'check_base': True}
        logic.analyze([wall()], [slab()], options)
        self.assertEqual({'check_base': True}, options)


class ReportTests(unittest.TestCase):
    def test_a_clean_run_says_so(self):
        text = logic.report_lines(
            logic.analyze([wall(top_attached=True)], [slab()]))
        self.assertIn(u'沒有發現貼附問題', text)

    def test_a_gap_is_named_with_its_size(self):
        text = logic.report_lines(logic.analyze([wall(top_z=2800.0)],
                                                [slab()]))
        self.assertIn(logic.STATE_GAP, text)
        self.assertIn(u'+200 mm', text)

    def test_the_report_states_the_bounding_box_limitation(self):
        text = logic.report_lines(logic.analyze([wall()], [slab()]))
        self.assertIn(u'最高點', text)

    def test_the_report_explains_why_attached_can_still_be_off(self):
        text = logic.report_lines(logic.analyze([wall()], [slab()]))
        self.assertIn(u'不記錄「貼到什麼」', text)

    def test_skipped_walls_are_counted_in_the_summary(self):
        text = logic.report_lines(
            logic.analyze([wall(1, is_curtain=True)], [slab()]))
        self.assertIn(u'略過 1 面', text)


if __name__ == '__main__':
    unittest.main()
