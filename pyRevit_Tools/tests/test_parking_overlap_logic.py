# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import math
import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import parking_overlap_logic as logic


WIDTH = 2500.0
LENGTH = 5500.0


def bay(element_id, x, y, angle_deg=0.0, level_id=1, level=u'B1F',
        mark=u'', in_group=False, width=WIDTH, length=LENGTH):
    return {
        'id': element_id,
        'level_id': level_id,
        'level': level,
        'mark': mark or u'P{}'.format(element_id),
        'type_name': u'停車位',
        'family_name': u'停車位',
        'in_group': in_group,
        'rect': logic.rect_from_size(
            (x, y), width, length, math.radians(angle_deg)),
    }


class OverlapDepthTests(unittest.TestCase):
    def test_far_apart_is_zero(self):
        first = logic.rect_from_size((0, 0), WIDTH, LENGTH)
        second = logic.rect_from_size((10000, 0), WIDTH, LENGTH)
        self.assertEqual(0.0, logic.overlap_depth(first, second))

    def test_edge_to_edge_neighbours_do_not_overlap(self):
        """Adjacent bays share an edge; that must read as 0, not as contact."""
        first = logic.rect_from_size((0, 0), WIDTH, LENGTH)
        second = logic.rect_from_size((WIDTH, 0), WIDTH, LENGTH)
        self.assertAlmostEqual(0.0, logic.overlap_depth(first, second), 6)

    def test_penetration_depth_is_the_shortfall(self):
        first = logic.rect_from_size((0, 0), WIDTH, LENGTH)
        second = logic.rect_from_size((WIDTH - 300.0, 0), WIDTH, LENGTH)
        self.assertAlmostEqual(300.0, logic.overlap_depth(first, second), 6)

    def test_exact_duplicate_penetrates_by_the_short_side(self):
        first = logic.rect_from_size((0, 0), WIDTH, LENGTH)
        second = logic.rect_from_size((0, 0), WIDTH, LENGTH)
        self.assertAlmostEqual(WIDTH, logic.overlap_depth(first, second), 6)

    def test_rotated_neighbours_are_not_false_positives(self):
        """The case an axis-aligned box would get wrong.

        Two 45-degree bays sitting side by side along their own width axis
        touch but do not overlap; their AABBs, however, intersect heavily.
        """
        angle = math.radians(45.0)
        offset = (WIDTH * math.cos(angle), WIDTH * math.sin(angle))
        first = logic.rect_from_size((0, 0), WIDTH, LENGTH, angle)
        second = logic.rect_from_size(offset, WIDTH, LENGTH, angle)
        self.assertAlmostEqual(0.0, logic.overlap_depth(first, second), 6)
        first_box = logic.aabb(first)
        second_box = logic.aabb(second)
        self.assertTrue(first_box[2] > second_box[0]
                        and first_box[3] > second_box[1])

    def test_rotated_true_overlap_is_still_found(self):
        angle = math.radians(30.0)
        first = logic.rect_from_size((0, 0), WIDTH, LENGTH, angle)
        second = logic.rect_from_size((500.0, 0), WIDTH, LENGTH, angle)
        self.assertTrue(logic.overlap_depth(first, second) > 0.0)

    def test_non_unit_axes_are_normalized(self):
        scaled = logic.make_rect((0, 0), (3.0, 0.0), (0.0, 3.0),
                                 (WIDTH / 2.0, LENGTH / 2.0))
        plain = logic.rect_from_size((0, 0), WIDTH, LENGTH)
        self.assertAlmostEqual(WIDTH, logic.overlap_depth(scaled, plain), 6)


class FindPairsTests(unittest.TestCase):
    def test_neighbouring_row_reports_nothing(self):
        bays = [bay(1, 0, 0), bay(2, WIDTH, 0), bay(3, WIDTH * 2, 0)]
        self.assertEqual([], logic.find_pairs(bays))

    def test_duplicate_is_reported(self):
        bays = [bay(1, 0, 0), bay(2, 0, 0)]
        pairs = logic.find_pairs(bays)
        self.assertEqual(1, len(pairs))
        self.assertAlmostEqual(WIDTH, pairs[0]['depth'], 6)

    def test_tolerance_suppresses_a_small_encroachment(self):
        bays = [bay(1, 0, 0), bay(2, WIDTH - 30.0, 0)]
        self.assertEqual([], logic.find_pairs(bays, tolerance_mm=50.0))
        self.assertEqual(1, len(logic.find_pairs(bays, tolerance_mm=10.0)))

    def test_different_levels_are_never_compared(self):
        bays = [bay(1, 0, 0, level_id=1, level=u'B1F'),
                bay(2, 0, 0, level_id=2, level=u'B2F')]
        self.assertEqual([], logic.find_pairs(bays))

    def test_pairs_sort_worst_first(self):
        bays = [bay(1, 0, 0), bay(2, WIDTH - 200.0, 0),
                bay(3, 20000, 0), bay(4, 20000, 0)]
        pairs = logic.find_pairs(bays)
        self.assertEqual(2, len(pairs))
        self.assertTrue(pairs[0]['depth'] > pairs[1]['depth'])


class ClusterTests(unittest.TestCase):
    def test_three_stacked_bays_are_one_cluster(self):
        bays = [bay(1, 0, 0), bay(2, 0, 0), bay(3, 0, 0)]
        report = logic.analyze(bays)
        self.assertEqual(1, len(report['clusters']))
        self.assertEqual(3, len(report['clusters'][0]['members']))
        self.assertEqual(3, report['clusters'][0]['pairs'])

    def test_two_separate_problems_stay_separate(self):
        bays = [bay(1, 0, 0), bay(2, 0, 0),
                bay(3, 50000, 0), bay(4, 50000, 0)]
        report = logic.analyze(bays)
        self.assertEqual(2, len(report['clusters']))

    def test_flagged_ids_cover_every_member(self):
        bays = [bay(1, 0, 0), bay(2, 0, 0), bay(3, 50000, 0)]
        report = logic.analyze(bays)
        self.assertEqual([1, 2], report['flagged_ids'])


class ReportTests(unittest.TestCase):
    def test_clean_layout_says_so(self):
        report = logic.analyze([bay(1, 0, 0), bay(2, WIDTH, 0)])
        self.assertIn(u'沒有重疊車位', logic.report_lines(report))

    def test_counts_grouped_and_geometryless_bays(self):
        bays = [
            bay(1, 0, 0, in_group=True),
            bay(2, WIDTH, 0),
            {'id': 3, 'level_id': 1, 'level': u'B1F', 'rect': None,
             'in_group': False},
        ]
        report = logic.analyze(bays)
        self.assertEqual([], report['clusters'])
        text = logic.report_lines(report)
        self.assertIn(u'位於群組內：1 個', text)
        self.assertIn(u'無法取得幾何、已略過：1 個', text)

    def test_overlap_summary_reports_depth(self):
        report = logic.analyze([bay(1, 0, 0), bay(2, 0, 0)])
        text = logic.report_lines(report)
        self.assertIn(u'重疊 1 處，涉及 2 個車位', text)
        self.assertIn(u'2500 mm', text)


if __name__ == '__main__':
    unittest.main()
