# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import area_renumber_logic as logic


def area(area_id, number=u'', name=u'空間', point=None, area_sqft=100.0,
         elevation=0.0):
    return {
        'id': area_id,
        'number': number or u'A{}'.format(area_id),
        'name': name,
        'point_xy': point,
        'area_sqft': area_sqft,
        'level_elevation': elevation,
        'level': u'1F',
    }


class OrderByFieldTests(unittest.TestCase):
    def test_natural_number_order(self):
        rows = [area(1, u'A10'), area(2, u'A2'), area(3, u'A1')]
        ordered = logic.order_rows(rows, logic.ORDER_BY_NUMBER)
        self.assertEqual([u'A1', u'A2', u'A10'],
                         [row['number'] for row in ordered])

    def test_name_order(self):
        rows = [area(1, name=u'倉庫'), area(2, name=u'辦公室'),
                area(3, name=u'會議室')]
        ordered = logic.order_rows(rows, logic.ORDER_BY_NAME)
        self.assertEqual(3, len(ordered))
        self.assertEqual(sorted([row['name'] for row in rows]),
                         sorted([row['name'] for row in ordered]))

    def test_area_descending_and_ascending(self):
        rows = [area(1, area_sqft=50.0), area(2, area_sqft=300.0),
                area(3, area_sqft=100.0)]
        self.assertEqual(
            [2, 3, 1],
            [row['id'] for row in
             logic.order_rows(rows, logic.ORDER_BY_AREA_DESC)])
        self.assertEqual(
            [1, 3, 2],
            [row['id'] for row in
             logic.order_rows(rows, logic.ORDER_BY_AREA_ASC)])

    def test_level_beats_everything(self):
        low = area(1, u'Z9', area_sqft=1.0, elevation=-3000.0)
        high = area(2, u'A1', area_sqft=999.0, elevation=3000.0)
        for strategy in (logic.ORDER_BY_NUMBER, logic.ORDER_BY_AREA_DESC):
            ordered = logic.order_rows([high, low], strategy)
            self.assertEqual([1, 2], [row['id'] for row in ordered],
                             u'策略 {} 沒有先照樓層排'.format(strategy))

    def test_unknown_strategy_rejected(self):
        self.assertRaises(ValueError, logic.order_rows, [], 'sideways')


class PositionOrderTests(unittest.TestCase):
    """A 3x3 grid; ids are laid out so the expected reading order is obvious."""

    def _grid(self):
        rows = []
        element_id = 1
        for y in (2000.0, 1000.0, 0.0):
            for x in (0.0, 1000.0, 2000.0):
                rows.append(area(element_id, point=(x, y)))
                element_id += 1
        return rows

    def test_row_major_reads_left_to_right_top_to_bottom(self):
        ordered = logic.order_rows(self._grid(), logic.ORDER_BY_ROW,
                                   band_mm=200.0)
        self.assertEqual([1, 2, 3, 4, 5, 6, 7, 8, 9],
                         [row['id'] for row in ordered])

    def test_column_major_reads_top_to_bottom_left_to_right(self):
        ordered = logic.order_rows(self._grid(), logic.ORDER_BY_COLUMN,
                                   band_mm=200.0)
        self.assertEqual([1, 4, 7, 2, 5, 8, 3, 6, 9],
                         [row['id'] for row in ordered])

    def test_band_absorbs_small_vertical_scatter(self):
        """Real rooms never line up exactly; the band is what makes a row."""
        rows = [area(1, point=(0.0, 1005.0)), area(2, point=(1000.0, 995.0)),
                area(3, point=(0.0, 0.0))]
        ordered = logic.order_rows(rows, logic.ORDER_BY_ROW, band_mm=100.0)
        self.assertEqual([1, 2, 3], [row['id'] for row in ordered])

    def test_narrow_band_splits_the_scatter_into_separate_rows(self):
        rows = [area(1, point=(0.0, 1005.0)), area(2, point=(1000.0, 995.0))]
        ordered = logic.order_rows(rows, logic.ORDER_BY_ROW, band_mm=1.0)
        self.assertEqual([1, 2], [row['id'] for row in ordered])

    def test_unplaced_areas_go_last_not_dropped(self):
        rows = [area(1, u'A5'), area(2, point=(0.0, 0.0)), area(3, u'A1')]
        ordered = logic.order_rows(rows, logic.ORDER_BY_ROW)
        self.assertEqual(3, len(ordered))
        self.assertEqual(2, ordered[0]['id'])
        self.assertEqual([3, 1], [row['id'] for row in ordered[1:]])

    def test_levels_are_never_interleaved_by_position(self):
        upper = area(1, point=(0.0, 0.0), elevation=3000.0)
        lower = area(2, point=(9000.0, 9000.0), elevation=0.0)
        ordered = logic.order_rows([upper, lower], logic.ORDER_BY_ROW)
        self.assertEqual([2, 1], [row['id'] for row in ordered])


class AssignNumbersTests(unittest.TestCase):
    def test_continuous_numbering(self):
        rows = logic.assign_numbers(
            [area(index) for index in range(1, 4)], u'A', 1, 0)
        self.assertEqual([u'A1', u'A2', u'A3'],
                         [row['target'] for row in rows])

    def test_zero_padding(self):
        rows = logic.assign_numbers(
            [area(index) for index in range(1, 3)], u'B', 9, 3)
        self.assertEqual([u'B009', u'B010'],
                         [row['target'] for row in rows])

    def test_per_level_restarts(self):
        rows = [area(1, elevation=0.0), area(2, elevation=0.0),
                area(3, elevation=3000.0)]
        assigned = logic.assign_numbers(rows, u'A', 1, 0, per_level=True)
        self.assertEqual([u'A1', u'A2', u'A1'],
                         [row['target'] for row in assigned])

    def test_empty_prefix(self):
        rows = logic.assign_numbers([area(1)], u'', 7, 2)
        self.assertEqual(u'07', rows[0]['target'])


class TwoPhaseTests(unittest.TestCase):
    """The swap is the whole reason this module is not a one-liner."""

    def test_swap_needs_two_phase(self):
        rows = [{'id': 1, 'number': u'A1', 'target': u'A2'},
                {'id': 2, 'number': u'A2', 'target': u'A1'}]
        self.assertTrue(logic.needs_two_phase(rows))

    def test_shift_by_one_needs_two_phase(self):
        rows = [{'id': 1, 'number': u'A1', 'target': u'A2'},
                {'id': 2, 'number': u'A2', 'target': u'A3'},
                {'id': 3, 'number': u'A3', 'target': u'A4'}]
        self.assertTrue(logic.needs_two_phase(rows))

    def test_disjoint_targets_do_not(self):
        rows = [{'id': 1, 'number': u'A1', 'target': u'B1'},
                {'id': 2, 'number': u'A2', 'target': u'B2'}]
        self.assertFalse(logic.needs_two_phase(rows))

    def test_keeping_your_own_number_is_not_a_collision(self):
        rows = [{'id': 1, 'number': u'A1', 'target': u'A1'},
                {'id': 2, 'number': u'A2', 'target': u'B2'}]
        self.assertFalse(logic.needs_two_phase(rows))

    def test_case_and_width_folded_when_detecting(self):
        rows = [{'id': 1, 'number': u'a1', 'target': u'A2'},
                {'id': 2, 'number': u'Ａ２', 'target': u'A1'}]
        self.assertTrue(logic.needs_two_phase(rows))

    def test_temporary_numbers_collide_with_nothing(self):
        rows = [{'id': 1, 'number': u'~R1', 'target': u'~R2'},
                {'id': 2, 'number': u'~R2', 'target': u'~R1'}]
        temps = logic.temporary_numbers(rows, taken=[u'~R~1'])
        self.assertEqual(2, len(temps))
        existing = set([u'~R1', u'~R2', u'~R~1'])
        for value in temps:
            self.assertNotIn(value, existing)
        self.assertEqual(len(temps), len(set(temps)))


class BuildPlanTests(unittest.TestCase):
    def test_unchanged_rows_are_not_written(self):
        rows = [area(1, u'A1'), area(2, u'B9')]
        plan = logic.build_plan(rows, logic.ORDER_BY_NUMBER, u'A', 1, 0)
        self.assertEqual([1], [row['id'] for row in plan['unchanged']])
        self.assertEqual([2], [row['id'] for row in plan['writes']])
        self.assertEqual(u'A2', plan['writes'][0]['target'])

    def test_write_rows_are_plain_records_and_blocked_rows_are_wrapped(self):
        """The two lists have different shapes; the button relies on that."""
        plan = logic.build_plan([area(1, u'X1'), area(2, u'X2')],
                                logic.ORDER_BY_NUMBER, u'A', 1, 0,
                                outside_numbers=[u'A2'])
        self.assertIn('target', plan['writes'][0])
        self.assertIn('id', plan['writes'][0])
        self.assertIn('record', plan['blocked'][0])
        self.assertIn('reason', plan['blocked'][0])

    def test_outside_collision_is_blocked_not_swapped(self):
        """No write order frees a number held by an area nobody is touching."""
        rows = [area(1, u'X1')]
        plan = logic.build_plan(rows, logic.ORDER_BY_NUMBER, u'A', 1, 0,
                                outside_numbers=[u'A1'])
        self.assertEqual([], plan['writes'])
        self.assertEqual(logic.BLOCK_OUTSIDE_COLLISION,
                         plan['blocked'][0]['reason'])

    def test_outside_collision_folds_case(self):
        plan = logic.build_plan([area(1, u'X1')], logic.ORDER_BY_NUMBER,
                                u'a', 1, 0, outside_numbers=[u'Ａ１'])
        self.assertEqual([], plan['writes'])

    def test_per_level_duplicate_target_is_caught(self):
        rows = [area(1, u'X1', elevation=0.0),
                area(2, u'X2', elevation=3000.0)]
        plan = logic.build_plan(rows, logic.ORDER_BY_NUMBER, u'A', 1, 0,
                                per_level=True)
        self.assertEqual(1, len(plan['writes']))
        self.assertEqual(logic.BLOCK_DUPLICATE_TARGET,
                         plan['blocked'][0]['reason'])

    def test_plan_flags_two_phase_for_a_swap(self):
        rows = [area(1, u'A2', point=(0.0, 0.0)),
                area(2, u'A1', point=(1000.0, 0.0))]
        plan = logic.build_plan(rows, logic.ORDER_BY_ROW, u'A', 1, 0)
        self.assertEqual(2, len(plan['writes']))
        self.assertTrue(plan['two_phase'])

    def test_no_writes_means_no_two_phase(self):
        rows = [area(1, u'A1'), area(2, u'A2')]
        plan = logic.build_plan(rows, logic.ORDER_BY_NUMBER, u'A', 1, 0)
        self.assertEqual([], plan['writes'])
        self.assertFalse(plan['two_phase'])

    def test_a_row_that_keeps_its_number_is_left_alone(self):
        rows = [area(1, u'A1', area_sqft=300.0),
                area(2, u'A9', area_sqft=100.0)]
        plan = logic.build_plan(rows, logic.ORDER_BY_AREA_DESC, u'A', 1, 0)
        targets = dict((row['id'], row['target']) for row in plan['writes'])
        self.assertEqual(u'A2', targets[2])
        self.assertEqual([1], [row['id'] for row in plan['unchanged']])
        self.assertFalse(plan['two_phase'])

    def test_a_number_held_by_a_row_staying_put_cannot_be_taken(self):
        """Two floors both restart at A1, so the second one must be refused."""
        rows = [area(1, u'A1', elevation=0.0),
                area(2, u'B7', elevation=3000.0)]
        plan = logic.build_plan(rows, logic.ORDER_BY_NUMBER, u'A', 1, 0,
                                per_level=True)
        self.assertEqual([1], [row['id'] for row in plan['unchanged']])
        self.assertEqual([], plan['writes'])
        self.assertEqual(logic.BLOCK_DUPLICATE_TARGET,
                         plan['blocked'][0]['reason'])


class PlanLinesTests(unittest.TestCase):
    def test_summary_reports_counts_and_arrow(self):
        rows = [area(1, u'X1'), area(2, u'X2')]
        plan = logic.build_plan(rows, logic.ORDER_BY_NUMBER, u'A', 1, 0)
        text = logic.plan_lines(plan, u'測試計畫', u'B1F')
        self.assertIn(u'將重新編號 2 個', text)
        self.assertIn(u'X1 → A1', text)

    def test_two_phase_is_explained(self):
        rows = [area(1, u'A2', point=(0.0, 0.0)),
                area(2, u'A1', point=(1000.0, 0.0))]
        plan = logic.build_plan(rows, logic.ORDER_BY_ROW, u'A', 1, 0)
        self.assertIn(u'暫時編號', logic.plan_lines(plan, u'x', u'y'))

    def test_blocked_reasons_are_grouped(self):
        plan = logic.build_plan([area(1, u'X1')], logic.ORDER_BY_NUMBER,
                                u'A', 1, 0, outside_numbers=[u'A1'])
        self.assertIn(logic.BLOCK_OUTSIDE_COLLISION,
                      logic.plan_lines(plan, u'x', u'y'))


if __name__ == '__main__':
    unittest.main()
