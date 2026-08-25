# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import cad_boundary_logic as logic


def curve(index=1, layer=u'WALL', kind=logic.KIND_LINE,
          start=(0.0, 0.0), end=(1000.0, 0.0), mid=None, length_mm=None):
    if mid is None:
        mid = ((start[0] + end[0]) * 0.5, (start[1] + end[1]) * 0.5)
    if length_mm is None:
        length_mm = ((end[0] - start[0]) ** 2
                     + (end[1] - start[1]) ** 2) ** 0.5
    return {
        'index': index,
        'layer': layer,
        'kind': kind,
        'start': start,
        'end': end,
        'mid': mid,
        'length_mm': length_mm,
    }


class CurveKeyTests(unittest.TestCase):
    def test_the_same_curve_matches_itself(self):
        self.assertEqual(logic.curve_key(curve(1)), logic.curve_key(curve(2)))

    def test_direction_does_not_matter(self):
        """The same wall drawn right-to-left is still the same wall."""
        forward = curve(1, start=(0.0, 0.0), end=(1000.0, 0.0))
        backward = curve(2, start=(1000.0, 0.0), end=(0.0, 0.0))
        self.assertEqual(logic.curve_key(forward), logic.curve_key(backward))

    def test_float_noise_under_the_tolerance_still_matches(self):
        a = curve(1, start=(0.0, 0.0), end=(1000.0, 0.0))
        b = curve(2, start=(0.3, 0.2), end=(1000.4, 0.1))
        self.assertEqual(logic.curve_key(a), logic.curve_key(b))

    def test_a_genuinely_different_curve_does_not_match(self):
        a = curve(1, end=(1000.0, 0.0))
        b = curve(2, end=(1000.0, 500.0))
        self.assertNotEqual(logic.curve_key(a), logic.curve_key(b))

    def test_an_arc_does_not_collide_with_its_own_chord(self):
        """Without the midpoint in the key, one of the pair would vanish."""
        chord = curve(1, kind=logic.KIND_LINE, start=(0.0, 0.0),
                      end=(1000.0, 0.0), mid=(500.0, 0.0))
        arc = curve(2, kind=logic.KIND_ARC, start=(0.0, 0.0),
                    end=(1000.0, 0.0), mid=(500.0, 300.0))
        self.assertNotEqual(logic.curve_key(chord), logic.curve_key(arc))

    def test_two_arcs_bulging_opposite_ways_are_different(self):
        up = curve(1, kind=logic.KIND_ARC, mid=(500.0, 300.0))
        down = curve(2, kind=logic.KIND_ARC, mid=(500.0, -300.0))
        self.assertNotEqual(logic.curve_key(up), logic.curve_key(down))

    def test_a_missing_point_does_not_crash(self):
        broken = curve(1)
        broken['mid'] = None
        self.assertIsNotNone(logic.curve_key(broken))


class LayerSummaryTests(unittest.TestCase):
    def test_curves_group_by_layer_with_counts(self):
        records = [curve(1, layer=u'WALL'), curve(2, layer=u'WALL'),
                   curve(3, layer=u'TEXT')]
        summary = logic.layer_summary(records)
        counts = dict((item['layer'], item['count']) for item in summary)
        self.assertEqual(2, counts[u'WALL'])
        self.assertEqual(1, counts[u'TEXT'])

    def test_layers_are_listed_alphabetically(self):
        records = [curve(1, layer=u'WALL'), curve(2, layer=u'AXIS')]
        self.assertEqual([u'AXIS', u'WALL'],
                         [item['layer'] for item in logic.layer_summary(records)])

    def test_total_length_accumulates(self):
        records = [curve(1, end=(1000.0, 0.0)), curve(2, end=(2000.0, 0.0))]
        self.assertAlmostEqual(3000.0,
                               logic.layer_summary(records)[0]['total_length_mm'],
                               6)

    def test_a_curve_with_no_layer_gets_a_placeholder(self):
        summary = logic.layer_summary([curve(1, layer=u'')])
        self.assertEqual(u'(無圖層)', summary[0]['layer'])

    def test_no_curves_means_no_layers(self):
        self.assertEqual([], logic.layer_summary([]))


class BlockTests(unittest.TestCase):
    def test_a_good_line_is_not_blocked(self):
        self.assertEqual(u'', logic.block_reason(curve(), 10.0))

    def test_a_short_curve_is_blocked(self):
        """A 0.4mm 'line' is a leftover from a trim, not a wall."""
        record = curve(1, end=(0.4, 0.0))
        self.assertEqual(logic.BLOCK_TOO_SHORT,
                         logic.block_reason(record, 10.0))

    def test_exactly_on_the_threshold_passes(self):
        record = curve(1, end=(10.0, 0.0))
        self.assertEqual(u'', logic.block_reason(record, 10.0))

    def test_a_spline_is_blocked_as_unsupported(self):
        self.assertEqual(logic.BLOCK_UNSUPPORTED,
                         logic.block_reason(curve(kind=logic.KIND_OTHER),
                                            10.0))

    def test_unsupported_outranks_too_short(self):
        record = curve(1, kind=logic.KIND_OTHER, end=(0.1, 0.0))
        self.assertEqual(logic.BLOCK_UNSUPPORTED,
                         logic.block_reason(record, 10.0))

    def test_an_arc_is_supported(self):
        self.assertEqual(u'', logic.block_reason(curve(kind=logic.KIND_ARC),
                                                 10.0))


class PlanTests(unittest.TestCase):
    def test_a_clean_batch_draws_everything(self):
        records = [curve(1, end=(1000.0, 0.0)), curve(2, start=(0.0, 500.0),
                                                      end=(1000.0, 500.0))]
        plan = logic.build_plan(records)
        self.assertEqual(2, plan['count'])
        self.assertTrue(logic.has_work(plan))

    def test_only_the_chosen_layers_are_considered(self):
        records = [curve(1, layer=u'WALL'), curve(2, layer=u'TEXT')]
        plan = logic.build_plan(records, layers=[u'WALL'])
        self.assertEqual(1, plan['count'])
        # The unpicked layer is filtered out entirely, not reported as blocked.
        self.assertEqual([], plan['blocked'])
        self.assertEqual(1, plan['considered'])

    def test_no_layer_filter_means_every_layer(self):
        records = [curve(1, layer=u'WALL'),
                   curve(2, layer=u'TEXT', start=(0.0, 500.0),
                         end=(1000.0, 500.0))]
        self.assertEqual(2, logic.build_plan(records)['count'])

    def test_dedup_spans_layers_rather_than_running_per_layer(self):
        """The same line on two picked layers is still one boundary line."""
        records = [curve(1, layer=u'WALL'), curve(2, layer=u'TEXT')]
        plan = logic.build_plan(records)
        self.assertEqual(1, plan['count'])
        self.assertEqual(logic.BLOCK_DUPLICATE, plan['blocked'][0]['reason'])

    def test_a_duplicate_is_drawn_once(self):
        records = [curve(1), curve(2)]
        plan = logic.build_plan(records)
        self.assertEqual(1, plan['count'])
        self.assertEqual(logic.BLOCK_DUPLICATE, plan['blocked'][0]['reason'])

    def test_the_first_of_a_duplicate_pair_is_the_one_kept(self):
        plan = logic.build_plan([curve(7), curve(9)])
        self.assertEqual(7, plan['draw'][0]['index'])
        self.assertEqual(7, plan['blocked'][0]['duplicate_of'])

    def test_a_reversed_duplicate_is_still_a_duplicate(self):
        records = [curve(1, start=(0.0, 0.0), end=(1000.0, 0.0)),
                   curve(2, start=(1000.0, 0.0), end=(0.0, 0.0))]
        self.assertEqual(1, logic.build_plan(records)['count'])

    def test_short_and_duplicate_and_unsupported_are_counted_separately(self):
        records = [
            curve(1, end=(1000.0, 0.0)),
            curve(2, end=(1000.0, 0.0)),            # duplicate
            curve(3, end=(0.2, 0.0)),               # too short
            curve(4, kind=logic.KIND_OTHER, start=(0.0, 900.0),
                  end=(1000.0, 900.0)),             # unsupported
        ]
        plan = logic.build_plan(records)
        self.assertEqual(1, plan['count'])
        self.assertEqual(1, plan['block_counts'][logic.BLOCK_DUPLICATE])
        self.assertEqual(1, plan['block_counts'][logic.BLOCK_TOO_SHORT])
        self.assertEqual(1, plan['block_counts'][logic.BLOCK_UNSUPPORTED])

    def test_raising_the_length_floor_drops_more(self):
        records = [curve(1, end=(50.0, 0.0))]
        self.assertEqual(1, logic.build_plan(records, min_length_mm=10.0)['count'])
        self.assertEqual(0, logic.build_plan(records, min_length_mm=100.0)['count'])

    def test_exact_duplicates_merge_at_any_tolerance(self):
        """The guarantee the dedup actually makes."""
        records = [curve(1), curve(2)]
        for tolerance in (0.01, 0.5, 1.0, 5.0, 50.0):
            self.assertEqual(
                1, logic.build_plan(records, tolerance_mm=tolerance)['count'],
                u'容差 {} 時未合併完全相同的曲線'.format(tolerance))

    def test_a_tighter_tolerance_never_merges_more_than_a_looser_one(self):
        records = [curve(1, start=(0.0, 0.0), end=(1000.0, 0.0)),
                   curve(2, start=(0.0, 3.0), end=(1000.0, 3.0)),
                   curve(3, start=(0.0, 6.0), end=(1000.0, 6.0))]
        loose = logic.build_plan(records, tolerance_mm=20.0)['count']
        tight = logic.build_plan(records, tolerance_mm=0.1)['count']
        self.assertLessEqual(loose, tight)
        self.assertEqual(3, tight)

    def test_grid_snapping_is_a_hint_not_a_distance_guarantee(self):
        """Records the known limitation rather than pretending precision.

        0 and 3 straddle a grid line at a tolerance of 5, so these two stay
        separate despite being closer together than the tolerance. Erring
        toward drawing both is the safe direction to be wrong in.
        """
        records = [curve(1, start=(0.0, 0.0), end=(1000.0, 0.0)),
                   curve(2, start=(0.0, 3.0), end=(1000.0, 3.0))]
        self.assertEqual(2, logic.build_plan(records,
                                             tolerance_mm=5.0)['count'])

    def test_the_layer_summary_covers_only_what_will_be_drawn(self):
        records = [curve(1, layer=u'WALL'), curve(2, layer=u'WALL')]
        plan = logic.build_plan(records)
        self.assertEqual(1, plan['layers'][0]['count'])

    def test_an_empty_source_is_handled(self):
        plan = logic.build_plan([])
        self.assertFalse(logic.has_work(plan))
        self.assertEqual(0, plan['considered'])


class ReportTests(unittest.TestCase):
    def test_the_count_and_layer_breakdown_are_stated(self):
        text = logic.plan_lines(logic.build_plan([curve(1, layer=u'WALL')]))
        self.assertIn(u'1 條', text)
        self.assertIn(u'WALL', text)

    def test_each_skip_reason_is_named_with_its_count(self):
        records = [curve(1), curve(2), curve(3, end=(0.2, 0.0))]
        text = logic.plan_lines(logic.build_plan(records))
        self.assertIn(logic.BLOCK_DUPLICATE, text)
        self.assertIn(logic.BLOCK_TOO_SHORT, text)

    def test_the_thresholds_used_are_printed(self):
        text = logic.plan_lines(logic.build_plan([curve(1)],
                                                 min_length_mm=25.0))
        self.assertIn(u'25.0 mm', text)

    def test_pending_deletions_are_announced(self):
        text = logic.plan_lines(logic.build_plan([curve(1)]), delete_count=12)
        self.assertIn(u'12 條區域線', text)

    def test_no_deletion_line_when_nothing_is_deleted(self):
        text = logic.plan_lines(logic.build_plan([curve(1)]))
        self.assertNotIn(u'既有的', text)

    def test_an_empty_plan_says_the_model_is_untouched(self):
        self.assertIn(u'模型不會變更', logic.plan_lines(logic.build_plan([])))


if __name__ == '__main__':
    unittest.main()
