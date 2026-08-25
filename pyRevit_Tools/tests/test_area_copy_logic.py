# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import area_copy_logic as logic


SQUARE = [(0.0, 0.0), (4000.0, 0.0), (4000.0, 4000.0), (0.0, 4000.0)]


def line(line_id, points):
    return {'id': line_id, 'points': points}


def straight(x1, y1, x2, y2, steps=2):
    if steps <= 2:
        return [(x1, y1), (x2, y2)]
    out = []
    for index in range(steps):
        ratio = float(index) / (steps - 1)
        out.append((x1 + (x2 - x1) * ratio, y1 + (y2 - y1) * ratio))
    return out


def area(area_id, number=u'A1', point=(2000.0, 2000.0), loops=None,
         placed=True, name=u'空間'):
    return {
        'id': area_id,
        'number': number,
        'name': name,
        'point_xy': point,
        'loops': loops if loops is not None else [SQUARE],
        'placed': placed,
        'level_elevation': 0.0,
        'level': u'1F',
        'area_sqft': 100.0,
    }


class CurveKeyTests(unittest.TestCase):
    def test_same_line_same_key(self):
        first = logic.curve_key(straight(0, 0, 1000, 0))
        second = logic.curve_key(straight(0, 0, 1000, 0))
        self.assertEqual(first, second)

    def test_direction_does_not_matter(self):
        forward = logic.curve_key(straight(0, 0, 1000, 0))
        backward = logic.curve_key(straight(1000, 0, 0, 0))
        self.assertEqual(forward, backward)

    def test_sub_tolerance_jitter_matches(self):
        first = logic.curve_key(straight(0, 0, 1000, 0))
        second = logic.curve_key(straight(0.2, 0.1, 1000.3, 0.2))
        self.assertEqual(first, second)

    def test_real_displacement_does_not_match(self):
        first = logic.curve_key(straight(0, 0, 1000, 0))
        second = logic.curve_key(straight(0, 500, 1000, 500))
        self.assertNotEqual(first, second)

    def test_direction_symmetry_holds_for_every_tessellation_length(self):
        """Index-based sampling broke on 2 points and on even counts.

        A straight boundary arrives as two points and an arc as an arbitrary
        number, so both shapes have to survive being walked backwards or the
        second run copies the whole layout again.
        """
        for steps in range(2, 9):
            points = straight(0, 0, 1000, 500, steps=steps)
            self.assertEqual(
                logic.curve_key(points),
                logic.curve_key(list(reversed(points))),
                u'{} 點的線反向後 key 不一致'.format(steps))

    def test_arcs_sharing_endpoints_are_distinguished(self):
        """Endpoints alone would call these one line and drop one of them."""
        bulge_up = [(0.0, 0.0), (500.0, 300.0), (1000.0, 0.0)]
        bulge_down = [(0.0, 0.0), (500.0, -300.0), (1000.0, 0.0)]
        self.assertNotEqual(logic.curve_key(bulge_up),
                            logic.curve_key(bulge_down))

    def test_degenerate_input_returns_none(self):
        self.assertIsNone(logic.curve_key([]))
        self.assertIsNone(logic.curve_key([(0.0, 0.0)]))
        self.assertIsNone(logic.curve_key(None))


class PlanLinesTests(unittest.TestCase):
    def test_fresh_target_copies_everything(self):
        source = [line(1, straight(0, 0, 1000, 0)),
                  line(2, straight(1000, 0, 1000, 1000))]
        plan = logic.plan_lines_to_copy(source, [])
        self.assertEqual(2, len(plan['writes']))
        self.assertEqual([], plan['skipped'])

    def test_second_run_copies_nothing(self):
        """Idempotence: the target already holds these lines."""
        source = [line(1, straight(0, 0, 1000, 0))]
        target = [line(9, straight(0, 0, 1000, 0))]
        plan = logic.plan_lines_to_copy(source, target)
        self.assertEqual([], plan['writes'])
        self.assertEqual(logic.SKIP_LINE_EXISTS, plan['skipped'][0]['reason'])

    def test_reversed_existing_line_still_counts_as_present(self):
        source = [line(1, straight(0, 0, 1000, 0))]
        target = [line(9, straight(1000, 0, 0, 0))]
        self.assertEqual([], logic.plan_lines_to_copy(source,
                                                      target)['writes'])

    def test_duplicate_inside_the_source_is_copied_once(self):
        source = [line(1, straight(0, 0, 1000, 0)),
                  line(2, straight(1000, 0, 0, 0))]
        plan = logic.plan_lines_to_copy(source, [])
        self.assertEqual(1, len(plan['writes']))
        self.assertEqual(logic.SKIP_LINE_DUPLICATE,
                         plan['skipped'][0]['reason'])

    def test_unreadable_geometry_is_blocked(self):
        plan = logic.plan_lines_to_copy([line(1, [])], [])
        self.assertEqual([], plan['writes'])
        self.assertEqual(logic.BLOCK_LINE_NO_GEOMETRY,
                         plan['blocked'][0]['reason'])

    def test_tolerance_is_configurable(self):
        source = [line(1, straight(0, 0, 1000, 0))]
        target = [line(9, straight(0, 40, 1000, 40))]
        self.assertEqual(1, len(logic.plan_lines_to_copy(
            source, target, tolerance_mm=1.0)['writes']))
        self.assertEqual(0, len(logic.plan_lines_to_copy(
            source, target, tolerance_mm=100.0)['writes']))


class PlanAreasTests(unittest.TestCase):
    def test_fresh_target_copies_everything(self):
        plan = logic.plan_areas_to_copy([area(1), area(2, u'A2')], [])
        self.assertEqual(2, len(plan['writes']))

    def test_seed_inside_existing_target_area_is_skipped(self):
        target = [area(9, u'X1', loops=[SQUARE])]
        plan = logic.plan_areas_to_copy(
            [area(1, u'A1', point=(2000.0, 2000.0))], target)
        self.assertEqual([], plan['writes'])
        self.assertEqual(logic.SKIP_AREA_COVERED, plan['skipped'][0]['reason'])

    def test_seed_outside_existing_target_area_is_copied(self):
        target = [area(9, u'X1', loops=[SQUARE])]
        plan = logic.plan_areas_to_copy(
            [area(1, u'A1', point=(9000.0, 9000.0))], target)
        self.assertEqual(1, len(plan['writes']))

    def test_unplaced_source_area_is_blocked(self):
        plan = logic.plan_areas_to_copy(
            [area(1, placed=False, point=None)], [])
        self.assertEqual([], plan['writes'])
        self.assertEqual(logic.BLOCK_AREA_UNPLACED,
                         plan['blocked'][0]['reason'])

    def test_number_collision_with_target_is_blocked(self):
        target = [area(9, u'A1', loops=[[(9000.0, 9000.0), (9100.0, 9000.0),
                                         (9100.0, 9100.0)]])]
        plan = logic.plan_areas_to_copy([area(1, u'A1')], target)
        self.assertEqual([], plan['writes'])
        self.assertEqual(logic.BLOCK_NUMBER_COLLISION,
                         plan['blocked'][0]['reason'])

    def test_number_collision_folds_case_and_width(self):
        target = [area(9, u'Ａ１', loops=[[(9000.0, 9000.0), (9100.0, 9000.0),
                                          (9100.0, 9100.0)]])]
        plan = logic.plan_areas_to_copy([area(1, u'a1')], target)
        self.assertEqual([], plan['writes'])

    def test_two_source_areas_sharing_a_number_only_one_survives(self):
        plan = logic.plan_areas_to_copy(
            [area(1, u'A1', point=(1000.0, 1000.0)),
             area(2, u'A1', point=(9000.0, 9000.0))], [])
        self.assertEqual(1, len(plan['writes']))
        self.assertEqual(logic.BLOCK_NUMBER_COLLISION,
                         plan['blocked'][0]['reason'])

    def test_blank_numbers_never_collide(self):
        plan = logic.plan_areas_to_copy(
            [area(1, u'', point=(1000.0, 1000.0)),
             area(2, u'', point=(9000.0, 9000.0))], [])
        self.assertEqual(2, len(plan['writes']))

    def test_number_and_name_are_carried_over(self):
        plan = logic.plan_areas_to_copy([area(1, u'A7', name=u'機房')], [])
        self.assertEqual(u'A7', plan['writes'][0]['target_number'])
        self.assertEqual(u'機房', plan['writes'][0]['target_name'])


class BuildPlanTests(unittest.TestCase):
    def _plan(self, **kwargs):
        return logic.build_plan(
            [line(1, straight(0, 0, 1000, 0))], [],
            [area(1, u'A1')], [], **kwargs)

    def test_both_halves_by_default(self):
        plan = self._plan()
        self.assertEqual(1, len(plan['lines']['writes']))
        self.assertEqual(1, len(plan['areas']['writes']))
        self.assertTrue(logic.has_work(plan))

    def test_lines_only(self):
        plan = self._plan(copy_areas=False)
        self.assertEqual(1, len(plan['lines']['writes']))
        self.assertEqual([], plan['areas']['writes'])

    def test_areas_only(self):
        plan = self._plan(copy_lines=False)
        self.assertEqual([], plan['lines']['writes'])
        self.assertEqual(1, len(plan['areas']['writes']))

    def test_nothing_to_do(self):
        plan = logic.build_plan([], [], [], [])
        self.assertFalse(logic.has_work(plan))


class ApplyTrialResultTests(unittest.TestCase):
    def _plan(self):
        return logic.build_plan(
            [], [],
            [area(1, u'A1', point=(1000.0, 1000.0)),
             area(2, u'A2', point=(9000.0, 9000.0))], [],
            copy_lines=False)

    def test_enclosed_areas_survive(self):
        result = logic.apply_trial_result(
            self._plan(), {1: {'enclosed': True, 'area_sqft': 90.0},
                           2: {'enclosed': True, 'area_sqft': 80.0}})
        self.assertEqual(2, len(result['areas']['writes']))
        self.assertTrue(result['trialled'])

    def test_unenclosed_area_moves_to_blocked(self):
        result = logic.apply_trial_result(
            self._plan(), {1: {'enclosed': True, 'area_sqft': 90.0},
                           2: {'enclosed': False}})
        self.assertEqual(1, len(result['areas']['writes']))
        self.assertEqual(logic.BLOCK_NOT_ENCLOSED,
                         result['areas']['blocked'][0]['reason'])

    def test_missing_trial_row_is_treated_as_failure(self):
        result = logic.apply_trial_result(self._plan(), {})
        self.assertEqual([], result['areas']['writes'])
        self.assertEqual(2, len(result['areas']['blocked']))


class SummaryTests(unittest.TestCase):
    def test_counts_and_reasons_are_reported(self):
        plan = logic.build_plan(
            [line(1, straight(0, 0, 1000, 0)), line(2, [])],
            [], [area(1, u'A1')], [])
        text = logic.plan_summary(plan, u'法定面積 B1F', u'銷售面積 B1F')
        self.assertIn(u'將複製 1 條', text)
        self.assertIn(logic.BLOCK_LINE_NO_GEOMETRY, text)
        self.assertIn(u'預計建立 1 個', text)

    def test_after_trial_says_will_create(self):
        plan = logic.build_plan([], [], [area(1, u'A1')], [],
                                copy_lines=False)
        result = logic.apply_trial_result(
            plan, {1: {'enclosed': True, 'area_sqft': 90.0}})
        self.assertIn(u'將建立 1 個',
                      logic.plan_summary(result, u'a', u'b'))

    def test_areas_without_lines_carries_a_warning(self):
        plan = logic.build_plan([], [], [area(1)], [], copy_lines=False)
        self.assertIn(u'沒有複製邊界線',
                      logic.plan_summary(plan, u'a', u'b'))

    def test_copying_lines_suppresses_that_warning(self):
        plan = logic.build_plan([line(1, straight(0, 0, 1, 0))], [],
                                [area(1)], [])
        self.assertNotIn(u'沒有複製邊界線',
                         logic.plan_summary(plan, u'a', u'b'))


if __name__ == '__main__':
    unittest.main()
