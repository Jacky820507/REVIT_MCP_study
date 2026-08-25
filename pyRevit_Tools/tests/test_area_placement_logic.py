# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import area_placement_logic as logic


SQUARE = [(0.0, 0.0), (4000.0, 0.0), (4000.0, 4000.0), (0.0, 4000.0)]
# A ring: outer square with a square hole punched through the middle.
RING = [
    SQUARE,
    [(1500.0, 1500.0), (2500.0, 1500.0), (2500.0, 2500.0), (1500.0, 2500.0)],
]
# An L: the top-right quadrant is missing, so the centroid falls outside.
L_SHAPE = [[(0.0, 0.0), (4000.0, 0.0), (4000.0, 1500.0), (1500.0, 1500.0),
            (1500.0, 4000.0), (0.0, 4000.0)]]
CORRIDOR = [[(0.0, 0.0), (12000.0, 0.0), (12000.0, 900.0), (0.0, 900.0)]]


def room(room_id, point=(2000.0, 2000.0), loops=None, placed=True,
         number=u'', name=u'', elevation=0.0):
    return {
        'id': room_id,
        'room_number': number or u'R{}'.format(room_id),
        'room_name': name or u'房間{}'.format(room_id),
        'point_xy': point,
        'loops': loops if loops is not None else [SQUARE],
        'placed': placed,
        'level_elevation': elevation,
        'level': u'1F',
    }


def area(area_id, loops=None, number=u'A1', placed=True, area_sqft=100.0):
    return {
        'id': area_id,
        'number': number,
        'name': u'面積',
        'loops': loops if loops is not None else [SQUARE],
        'placed': placed,
        'area_sqft': area_sqft,
        'level_elevation': 0.0,
        'level': u'1F',
    }


class PolygonAreaTests(unittest.TestCase):
    def test_counter_clockwise_is_positive(self):
        self.assertAlmostEqual(16000000.0, logic.polygon_area(SQUARE), 3)

    def test_clockwise_is_negative(self):
        reversed_square = list(reversed(SQUARE))
        self.assertAlmostEqual(-16000000.0,
                               logic.polygon_area(reversed_square), 3)

    def test_degenerate_loop_is_zero(self):
        self.assertEqual(0.0, logic.polygon_area([]))
        self.assertEqual(0.0, logic.polygon_area([(0, 0), (1, 1)]))


class PointInLoopsTests(unittest.TestCase):
    def test_inside_and_outside_a_square(self):
        self.assertTrue(logic.point_in_loops((2000.0, 2000.0), [SQUARE]))
        self.assertFalse(logic.point_in_loops((9000.0, 2000.0), [SQUARE]))

    def test_hole_centre_reads_as_outside(self):
        """The donut case — a seed here would not be in the region at all."""
        self.assertTrue(logic.point_in_loops((500.0, 500.0), RING))
        self.assertFalse(logic.point_in_loops((2000.0, 2000.0), RING))

    def test_concave_notch_reads_as_outside(self):
        self.assertTrue(logic.point_in_loops((500.0, 500.0), L_SHAPE))
        self.assertFalse(logic.point_in_loops((3000.0, 3000.0), L_SHAPE))

    def test_ray_through_a_vertex_is_counted_once(self):
        """y exactly on a vertex is the classic double-count bug."""
        diamond = [[(0.0, 0.0), (1000.0, 1000.0), (0.0, 2000.0),
                    (-1000.0, 1000.0)]]
        self.assertTrue(logic.point_in_loops((0.0, 1000.0), diamond))
        self.assertFalse(logic.point_in_loops((5000.0, 1000.0), diamond))
        self.assertFalse(logic.point_in_loops((0.0, 3000.0), diamond))

    def test_empty_inputs(self):
        self.assertFalse(logic.point_in_loops(None, [SQUARE]))
        self.assertFalse(logic.point_in_loops((0.0, 0.0), None))
        self.assertFalse(logic.point_in_loops((0.0, 0.0), []))


class InteriorPointTests(unittest.TestCase):
    """point_in_loops is the oracle: whatever this returns must satisfy it."""

    def _assert_inside(self, loops):
        point = logic.interior_point(loops)
        self.assertIsNotNone(point)
        self.assertTrue(
            logic.point_in_loops(point, loops),
            u'interior_point 回傳 {} 不在區域內'.format(point))

    def test_square(self):
        self._assert_inside([SQUARE])

    def test_l_shape(self):
        self._assert_inside(L_SHAPE)

    def test_ring_avoids_the_hole(self):
        self._assert_inside(RING)

    def test_narrow_corridor(self):
        self._assert_inside(CORRIDOR)

    def test_degenerate_returns_none(self):
        self.assertIsNone(logic.interior_point([]))
        self.assertIsNone(logic.interior_point([[(0.0, 0.0), (1.0, 0.0)]]))


class SeedFromRoomTests(unittest.TestCase):
    def test_location_point_used_when_it_is_inside(self):
        point, note = logic.seed_from_room(room(1, point=(2000.0, 2000.0)))
        self.assertEqual((2000.0, 2000.0), point)
        self.assertEqual(u'', note)

    def test_location_point_outside_falls_back_to_interior(self):
        """After a boundary edit the point can end up in the next room."""
        point, note = logic.seed_from_room(
            room(1, point=(9000.0, 9000.0), loops=[SQUARE]))
        self.assertTrue(logic.point_in_loops(point, [SQUARE]))
        self.assertIn(u'不在房間內', note)

    def test_ring_room_with_point_in_the_hole(self):
        point, note = logic.seed_from_room(
            room(1, point=(2000.0, 2000.0), loops=RING))
        self.assertTrue(logic.point_in_loops(point, RING))
        self.assertIn(u'不在房間內', note)

    def test_unplaced_room_is_blocked(self):
        point, reason = logic.seed_from_room(room(1, placed=False))
        self.assertIsNone(point)
        self.assertEqual(logic.BLOCK_ROOM_NOT_PLACED, reason)

    def test_no_geometry_and_no_point_is_blocked(self):
        point, reason = logic.seed_from_room(
            room(1, point=None, loops=[]))
        self.assertIsNone(point)
        self.assertEqual(logic.BLOCK_NO_SEED_POINT, reason)

    def test_point_without_loops_is_used_with_a_note(self):
        point, note = logic.seed_from_room(
            room(1, point=(10.0, 20.0), loops=[]))
        self.assertEqual((10.0, 20.0), point)
        self.assertIn(u'沒有邊界資料', note)


def warning(kind):
    return {'kind': kind, 'label': logic.KIND_LABELS[kind], 'text': u'…'}


class AreaStatusTests(unittest.TestCase):
    def test_model_numbers_alone_decide_placed_and_enclosed(self):
        self.assertEqual(logic.AREA_NOT_PLACED, logic.area_status(
            area(1, placed=False, area_sqft=0.0)))
        self.assertEqual(logic.AREA_NOT_ENCLOSED, logic.area_status(
            area(1, area_sqft=0.0)))
        self.assertEqual(logic.AREA_OK, logic.area_status(area(1), []))

    def test_revit_warning_kinds_are_honoured(self):
        """A redundant area looks perfectly healthy from its own numbers."""
        self.assertEqual(logic.AREA_REDUNDANT, logic.area_status(
            area(1), [warning(logic.KIND_REDUNDANT)]))
        self.assertEqual(logic.AREA_NOT_ENCLOSED, logic.area_status(
            area(1), [warning(logic.KIND_NOT_ENCLOSED)]))
        self.assertEqual(logic.AREA_NOT_PLACED, logic.area_status(
            area(1), [warning(logic.KIND_NOT_PLACED)]))

    def test_priority_order_is_fixed(self):
        both = [warning(logic.KIND_NOT_PLACED), warning(logic.KIND_REDUNDANT)]
        self.assertEqual(logic.AREA_NOT_PLACED, logic.area_status(
            area(1), both))
        self.assertEqual(logic.AREA_NOT_ENCLOSED, logic.area_status(
            area(1, area_sqft=0.0), [warning(logic.KIND_REDUNDANT)]))

    def test_unrecognised_warning_falls_back_to_generic(self):
        self.assertEqual(logic.AREA_WARNING, logic.area_status(
            area(1), [warning(logic.KIND_BOUNDARY_OVERLAP)]))

    def test_plain_string_warnings_are_not_dropped(self):
        self.assertEqual(logic.AREA_WARNING,
                         logic.area_status(area(1), [u'某個警告']))

    def test_audit_counts_and_flags(self):
        areas = [area(1), area(2, area_sqft=0.0),
                 area(3, placed=False, area_sqft=0.0), area(4)]
        report = logic.build_audit(
            areas, warnings={4: [warning(logic.KIND_REDUNDANT)]})
        self.assertEqual(4, report['total'])
        self.assertEqual(1, report['counts'][logic.AREA_OK])
        self.assertEqual(1, report['counts'][logic.AREA_NOT_ENCLOSED])
        self.assertEqual(1, report['counts'][logic.AREA_NOT_PLACED])
        self.assertEqual(1, report['counts'][logic.AREA_REDUNDANT])
        self.assertEqual([2, 3, 4], sorted(report['flagged_ids']))
        self.assertIn(u'3 個面積需要處理', logic.audit_lines(report))

    def test_clean_audit_says_so(self):
        report = logic.build_audit([area(1), area(2)])
        self.assertIn(u'沒有異常', logic.audit_lines(report))


class SortKeyTests(unittest.TestCase):
    def test_natural_number_order(self):
        rows = [area(1, number=u'A10'), area(2, number=u'A2'),
                area(3, number=u'A1')]
        rows.sort(key=logic.sort_key)
        self.assertEqual([u'A1', u'A2', u'A10'],
                         [row['number'] for row in rows])

    def test_elevation_wins_over_number(self):
        low = area(1, number=u'Z9')
        low['level_elevation'] = -10.0
        high = area(2, number=u'A1')
        rows = sorted([high, low], key=logic.sort_key)
        self.assertEqual([1, 2], [row['id'] for row in rows])

    def test_repeatable(self):
        rows = [area(index, number=u'A{}'.format(index))
                for index in range(1, 6)]
        first = [row['id'] for row in sorted(rows, key=logic.sort_key)]
        second = [row['id'] for row in sorted(
            list(reversed(rows)), key=logic.sort_key)]
        self.assertEqual(first, second)


class AssignValuesTests(unittest.TestCase):
    def test_from_room(self):
        rows = logic.assign_values(
            [room(1, number=u'R101', name=u'辦公室')],
            logic.NUMBER_FROM_ROOM, logic.NAME_FROM_ROOM)
        self.assertEqual(u'R101', rows[0]['number'])
        self.assertEqual(u'辦公室', rows[0]['name'])

    def test_sequence_with_padding(self):
        rows = logic.assign_values(
            [room(index) for index in range(1, 4)],
            logic.NUMBER_SEQUENCE, logic.NAME_NONE,
            {'prefix': u'A', 'start': 9, 'pad': 3})
        self.assertEqual([u'A009', u'A010', u'A011'],
                         [row['number'] for row in rows])
        self.assertEqual([u'', u'', u''], [row['name'] for row in rows])

    def test_constant_name(self):
        rows = logic.assign_values(
            [room(1)], logic.NUMBER_NONE, logic.NAME_CONSTANT,
            {'constant': u'待定'})
        self.assertEqual(u'', rows[0]['number'])
        self.assertEqual(u'待定', rows[0]['name'])

    def test_unknown_sources_rejected(self):
        self.assertRaises(ValueError, logic.assign_values, [], 'magic',
                          logic.NAME_NONE)
        self.assertRaises(ValueError, logic.assign_values, [],
                          logic.NUMBER_NONE, 'magic')


class BuildPlanTests(unittest.TestCase):
    def test_rooms_become_seeds(self):
        plan = logic.build_plan([room(1), room(2)], [])
        self.assertEqual(2, len(plan['creates']))
        self.assertEqual([], plan['blocked'])

    def test_second_run_is_a_no_op(self):
        """Idempotence: a seed inside an existing area is never placed again."""
        existing = [area(9, loops=[SQUARE])]
        plan = logic.build_plan([room(1, point=(2000.0, 2000.0))], existing)
        self.assertEqual([], plan['creates'])
        self.assertEqual(logic.BLOCK_ALREADY_COVERED,
                         plan['blocked'][0]['reason'])

    def test_seed_outside_existing_area_still_placed(self):
        existing = [area(9, loops=[[(9000.0, 9000.0), (10000.0, 9000.0),
                                    (10000.0, 10000.0), (9000.0, 10000.0)]])]
        plan = logic.build_plan([room(1)], existing)
        self.assertEqual(1, len(plan['creates']))

    def test_number_collision_with_existing(self):
        existing = [area(9, number=u'R1', loops=[[(9000.0, 9000.0),
                                                  (9100.0, 9000.0),
                                                  (9100.0, 9100.0)]])]
        plan = logic.build_plan([room(1, number=u'R1')], existing)
        self.assertEqual([], plan['creates'])
        self.assertEqual(logic.BLOCK_NUMBER_COLLISION,
                         plan['blocked'][0]['reason'])

    def test_self_collision_between_two_new_numbers(self):
        plan = logic.build_plan(
            [room(1, number=u'R1'), room(2, number=u'R1')], [])
        self.assertEqual(1, len(plan['creates']))
        self.assertEqual(logic.BLOCK_SELF_COLLISION,
                         plan['blocked'][0]['reason'])

    def test_blank_numbers_never_collide(self):
        plan = logic.build_plan([room(1), room(2)], [],
                                number_source=logic.NUMBER_NONE)
        self.assertEqual(2, len(plan['creates']))

    def test_unplaced_room_blocked_before_anything_else(self):
        plan = logic.build_plan([room(1, placed=False)], [])
        self.assertEqual([], plan['creates'])
        self.assertEqual(logic.BLOCK_ROOM_NOT_PLACED,
                         plan['blocked'][0]['reason'])


class ApplyTrialResultTests(unittest.TestCase):
    def _plan(self):
        return logic.build_plan([room(1), room(2, point=(3000.0, 3000.0))], [])

    def test_all_enclosed_becomes_writes(self):
        plan = self._plan()
        trial = {1: {'enclosed': True, 'area_sqft': 100.0},
                 2: {'enclosed': True, 'area_sqft': 120.0}}
        result = logic.apply_trial_result(plan, trial)
        self.assertEqual(2, len(result['writes']))
        self.assertTrue(result['trialled'])

    def test_unenclosed_moves_to_blocked(self):
        plan = self._plan()
        trial = {1: {'enclosed': False, 'area_sqft': 0.0},
                 2: {'enclosed': True, 'area_sqft': 120.0}}
        result = logic.apply_trial_result(plan, trial)
        self.assertEqual(1, len(result['writes']))
        self.assertEqual(logic.BLOCK_NOT_ENCLOSED,
                         result['blocked'][0]['reason'])

    def test_self_covered_moves_to_blocked(self):
        plan = self._plan()
        trial = {1: {'enclosed': True, 'area_sqft': 100.0},
                 2: {'enclosed': True, 'self_covered': True}}
        result = logic.apply_trial_result(plan, trial)
        self.assertEqual(1, len(result['writes']))
        self.assertEqual(logic.BLOCK_SELF_COVERED,
                         result['blocked'][0]['reason'])

    def test_missing_trial_row_is_treated_as_failure(self):
        plan = self._plan()
        result = logic.apply_trial_result(plan, {1: {'enclosed': True}})
        self.assertEqual(1, len(result['writes']))
        self.assertEqual(logic.BLOCK_NOT_ENCLOSED,
                         result['blocked'][0]['reason'])


class SequenceGuardTests(unittest.TestCase):
    def test_sequence_with_a_blocked_row_is_gapped(self):
        plan = logic.build_plan(
            [room(1), room(2, placed=False)], [],
            number_source=logic.NUMBER_SEQUENCE,
            options={'prefix': u'A', 'start': 1, 'pad': 0})
        self.assertTrue(logic.sequence_is_gapped(plan))

    def test_clean_sequence_is_not_gapped(self):
        plan = logic.build_plan(
            [room(1), room(2, point=(3000.0, 3000.0))], [],
            number_source=logic.NUMBER_SEQUENCE,
            options={'prefix': u'A', 'start': 1, 'pad': 0})
        self.assertFalse(logic.sequence_is_gapped(plan))

    def test_room_number_source_is_never_gapped(self):
        plan = logic.build_plan([room(1), room(2, placed=False)], [])
        self.assertTrue(plan['blocked'])
        self.assertFalse(logic.sequence_is_gapped(plan))


class GrossSchemeHintTests(unittest.TestCase):
    def test_mostly_self_covered_triggers_the_hint(self):
        plan = {'blocked': [{'reason': logic.BLOCK_SELF_COVERED}
                            for unused in range(9)],
                'writes': [{}]}
        self.assertIn(u'一層一個大區', logic.gross_scheme_warning(plan))

    def test_a_few_collisions_do_not(self):
        plan = {'blocked': [{'reason': logic.BLOCK_SELF_COVERED}],
                'writes': [{} for unused in range(9)]}
        self.assertEqual(u'', logic.gross_scheme_warning(plan))

    def test_tiny_runs_do_not(self):
        plan = {'blocked': [{'reason': logic.BLOCK_SELF_COVERED}],
                'writes': []}
        self.assertEqual(u'', logic.gross_scheme_warning(plan))


class PlanLinesTests(unittest.TestCase):
    def test_before_trial_says_predicted(self):
        plan = logic.build_plan([room(1)], [])
        text = logic.plan_lines(plan, u'測試計畫', u'B1F 面積')
        self.assertIn(u'預計建立 1 個面積', text)

    def test_after_trial_says_will_create_and_lists_reasons(self):
        plan = logic.build_plan(
            [room(1), room(2, point=(3000.0, 3000.0))], [])
        result = logic.apply_trial_result(
            plan, {1: {'enclosed': True, 'area_sqft': 100.0},
                   2: {'enclosed': False}})
        text = logic.plan_lines(result, u'測試計畫', u'B1F 面積')
        self.assertIn(u'將建立 1 個面積', text)
        self.assertIn(logic.BLOCK_NOT_ENCLOSED, text)


if __name__ == '__main__':
    unittest.main()
