# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import dimension_merge_logic as logic


def dim(dim_id, x0=0.0, x1=1000.0, y=0.0, z=0.0, view_id=5, type_id=7,
        refs=None, shape=logic.SHAPE_LINEAR, available=True, locked=False,
        **overrides):
    """One dimension as the button hands it over; horizontal unless moved."""
    record = {
        'id': dim_id,
        'view_id': view_id,
        'type_id': type_id,
        'type_name': u'標註型式A',
        'shape': shape,
        'references_available': available,
        'is_locked': locked,
        'start': (x0, y, z),
        'end': (x1, y, z),
        'reference_keys': refs if refs is not None
        else [u'r{}a'.format(dim_id), u'r{}b'.format(dim_id)],
        'segments': [],
    }
    record.update(overrides)
    return record


class DirectionTests(unittest.TestCase):
    def test_unit_direction(self):
        d = logic.direction_of(dim(1, 0.0, 1000.0))
        self.assertAlmostEqual(1.0, d[0], 6)
        self.assertAlmostEqual(0.0, d[1], 6)

    def test_zero_length_has_no_direction(self):
        self.assertIsNone(logic.direction_of(dim(1, 0.0, 0.0)))

    def test_missing_points(self):
        self.assertIsNone(logic.direction_of({'start': None, 'end': None}))


class CollinearTests(unittest.TestCase):
    def test_same_line_end_to_end(self):
        self.assertTrue(logic.are_collinear(dim(1, 0.0, 1000.0),
                                            dim(2, 1000.0, 2000.0)))

    def test_reversed_direction_still_collinear(self):
        self.assertTrue(logic.are_collinear(dim(1, 0.0, 1000.0),
                                            dim(2, 2000.0, 1000.0)))

    def test_parallel_but_offset_is_not_collinear(self):
        """Two dimension strings 300 mm apart are two runs, not one."""
        self.assertFalse(logic.are_collinear(dim(1, 0.0, 1000.0, y=0.0),
                                             dim(2, 0.0, 1000.0, y=300.0)))

    def test_offset_within_tolerance_is_collinear(self):
        self.assertTrue(logic.are_collinear(dim(1, 0.0, 1000.0, y=0.0),
                                            dim(2, 0.0, 1000.0, y=2.0)))

    def test_perpendicular_is_not_collinear(self):
        vertical = dim(2)
        vertical['start'] = (0.0, 0.0, 0.0)
        vertical['end'] = (0.0, 1000.0, 0.0)
        self.assertFalse(logic.are_collinear(dim(1, 0.0, 1000.0), vertical))

    def test_slightly_rotated_within_tolerance(self):
        skew = dim(2)
        skew['start'] = (0.0, 0.0, 0.0)
        skew['end'] = (1000.0, 5.0, 0.0)     # ~0.29 degrees
        self.assertTrue(logic.are_collinear(dim(1, 0.0, 1000.0), skew))


class BlockingTests(unittest.TestCase):
    def test_linear_and_clean_is_not_blocked(self):
        self.assertEqual(u'', logic.block_reason(dim(1)))

    def test_radial_dimension_is_blocked(self):
        self.assertEqual(logic.BLOCK_NOT_LINEAR,
                         logic.block_reason(dim(1, shape='Radial')))

    def test_unavailable_references_are_blocked(self):
        self.assertEqual(logic.BLOCK_NO_REFERENCES,
                         logic.block_reason(dim(1, available=False)))

    def test_locked_dimension_is_blocked(self):
        self.assertEqual(logic.BLOCK_LOCKED,
                         logic.block_reason(dim(1, locked=True)))

    def test_zero_length_is_blocked(self):
        self.assertEqual(logic.BLOCK_NO_GEOMETRY,
                         logic.block_reason(dim(1, 0.0, 0.0)))

    def test_value_override_is_blocked(self):
        """Someone typed that text; rebuilding would silently delete it."""
        self.assertEqual(logic.BLOCK_HAS_OVERRIDE,
                         logic.block_reason(dim(1, value_override=u'約 3000')))

    def test_every_override_field_blocks(self):
        for field in logic.OVERRIDE_FIELDS:
            record = dim(1)
            record[field] = u'x'
            self.assertEqual(logic.BLOCK_HAS_OVERRIDE,
                             logic.block_reason(record),
                             u'{} 沒有擋下'.format(field))

    def test_segment_override_blocks_too(self):
        record = dim(1)
        record['segments'] = [{}, {'suffix': u'(淨)'}]
        self.assertEqual(logic.BLOCK_HAS_OVERRIDE, logic.block_reason(record))

    def test_blank_override_fields_do_not_block(self):
        record = dim(1, value_override=u'', prefix=u'   ')
        record['segments'] = [{'above': u''}]
        self.assertEqual(u'', logic.block_reason(record))


class BuildRunsTests(unittest.TestCase):
    def test_two_adjacent_dimensions_merge(self):
        plan = logic.build_runs([dim(1, 0.0, 1000.0), dim(2, 1000.0, 2000.0)])
        self.assertEqual(1, len(plan['runs']))
        self.assertEqual(2, len(plan['runs'][0]['members']))
        self.assertAlmostEqual(2000.0, plan['runs'][0]['length_mm'], 3)

    def test_a_lone_dimension_is_not_a_run(self):
        plan = logic.build_runs([dim(1)])
        self.assertEqual([], plan['runs'])
        self.assertEqual(logic.SKIP_ALONE, plan['singles'][0]['reason'])
        self.assertFalse(logic.has_work(plan))

    def test_different_views_never_merge(self):
        plan = logic.build_runs([dim(1, 0.0, 1000.0, view_id=5),
                                 dim(2, 1000.0, 2000.0, view_id=6)])
        self.assertEqual([], plan['runs'])
        self.assertEqual(2, len(plan['singles']))

    def test_different_types_never_merge(self):
        """Merging across types would silently restyle one of them."""
        plan = logic.build_runs([dim(1, 0.0, 1000.0, type_id=7),
                                 dim(2, 1000.0, 2000.0, type_id=8)])
        self.assertEqual([], plan['runs'])

    def test_parallel_offset_rows_form_two_runs(self):
        plan = logic.build_runs([
            dim(1, 0.0, 1000.0, y=0.0), dim(2, 1000.0, 2000.0, y=0.0),
            dim(3, 0.0, 1000.0, y=500.0), dim(4, 1000.0, 2000.0, y=500.0)])
        self.assertEqual(2, len(plan['runs']))
        for run in plan['runs']:
            self.assertEqual(2, len(run['members']))

    def test_a_wide_gap_splits_the_run(self):
        plan = logic.build_runs(
            [dim(1, 0.0, 1000.0), dim(2, 1000.0, 2000.0),
             dim(3, 50000.0, 51000.0), dim(4, 51000.0, 52000.0)],
            max_gap_mm=3000.0)
        self.assertEqual(2, len(plan['runs']))

    def test_a_generous_gap_keeps_them_together(self):
        plan = logic.build_runs(
            [dim(1, 0.0, 1000.0), dim(2, 1000.0, 2000.0),
             dim(3, 50000.0, 51000.0), dim(4, 51000.0, 52000.0)],
            max_gap_mm=100000.0)
        self.assertEqual(1, len(plan['runs']))
        self.assertEqual(4, len(plan['runs'][0]['members']))

    def test_a_short_dimension_inside_a_long_one_does_not_split_the_run(self):
        """The chunk's reach, not the last item's end, decides the gap."""
        plan = logic.build_runs(
            [dim(1, 0.0, 10000.0), dim(2, 1000.0, 2000.0),
             dim(3, 10000.0, 11000.0)],
            max_gap_mm=1000.0)
        self.assertEqual(1, len(plan['runs']))
        self.assertEqual(3, len(plan['runs'][0]['members']))

    def test_blocked_dimensions_are_kept_out_of_runs(self):
        plan = logic.build_runs([
            dim(1, 0.0, 1000.0), dim(2, 1000.0, 2000.0),
            dim(3, 2000.0, 3000.0, value_override=u'約 1000')])
        self.assertEqual(1, len(plan['runs']))
        self.assertEqual(2, len(plan['runs'][0]['members']))
        self.assertEqual(logic.BLOCK_HAS_OVERRIDE,
                         plan['blocked'][0]['reason'])

    def test_run_geometry_spans_the_members(self):
        plan = logic.build_runs([dim(1, 500.0, 1500.0),
                                 dim(2, 1500.0, 4000.0)])
        run = plan['runs'][0]
        self.assertAlmostEqual(500.0, run['start'][0], 3)
        self.assertAlmostEqual(4000.0, run['end'][0], 3)

    def test_empty_input(self):
        plan = logic.build_runs([])
        self.assertEqual([], plan['runs'])
        self.assertFalse(logic.has_work(plan))


class ReferenceTests(unittest.TestCase):
    def test_shared_references_are_counted_once(self):
        """Adjacent strings share the witness line between them."""
        plan = logic.build_runs([
            dim(1, 0.0, 1000.0, refs=[u'a', u'b']),
            dim(2, 1000.0, 2000.0, refs=[u'b', u'c'])])
        run = plan['runs'][0]
        self.assertEqual([u'a', u'b', u'c'], run['reference_keys'])
        self.assertEqual(3, run['reference_count'])
        self.assertEqual(1, run['dropped_duplicates'])

    def test_disjoint_references_are_all_kept(self):
        plan = logic.build_runs([
            dim(1, 0.0, 1000.0, refs=[u'a', u'b']),
            dim(2, 1000.0, 2000.0, refs=[u'c', u'd'])])
        self.assertEqual(4, plan['runs'][0]['reference_count'])
        self.assertEqual(0, plan['runs'][0]['dropped_duplicates'])


class ReportTests(unittest.TestCase):
    def test_nothing_to_do_says_so(self):
        self.assertIn(u'沒有可以合併的標註',
                      logic.plan_lines(logic.build_runs([dim(1)])))

    def test_summary_counts_merges(self):
        plan = logic.build_runs([dim(1, 0.0, 1000.0), dim(2, 1000.0, 2000.0)])
        text = logic.plan_lines(plan)
        self.assertIn(u'將把 2 個標註合併成 1 條', text)

    def test_blocked_reasons_are_grouped(self):
        plan = logic.build_runs([dim(1, value_override=u'x'),
                                 dim(2, shape='Radial')])
        text = logic.plan_lines(plan)
        self.assertIn(logic.BLOCK_HAS_OVERRIDE, text)
        self.assertIn(logic.BLOCK_NOT_LINEAR, text)


if __name__ == '__main__':
    unittest.main()
