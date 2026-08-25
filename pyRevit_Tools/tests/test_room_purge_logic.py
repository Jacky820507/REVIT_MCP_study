# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import room_purge_logic as logic


def room(room_id=1, **overrides):
    """A healthy placed room, so each test breaks exactly one thing."""
    record = {
        'id': room_id,
        'number': u'101',
        'name': u'辦公室',
        'level': u'1F',
        'area_m2': 24.5,
        'perimeter_m': 20.0,
        'is_placed': True,
        'warning_kinds': [],
    }
    record.update(overrides)
    return record


class ClassifyTests(unittest.TestCase):
    def test_a_healthy_room_is_normal(self):
        self.assertEqual(logic.STATE_OK, logic.classify(room()))

    def test_an_unplaced_room(self):
        self.assertEqual(logic.STATE_NOT_PLACED,
                         logic.classify(room(is_placed=False, area_m2=0.0)))

    def test_a_placed_room_with_no_area_is_unenclosed(self):
        self.assertEqual(logic.STATE_NOT_ENCLOSED,
                         logic.classify(room(area_m2=0.0)))

    def test_unplaced_outranks_unenclosed(self):
        """An unplaced room also has no area; calling it 未封閉 sends someone
        hunting for a wall that never existed."""
        record = room(is_placed=False, area_m2=0.0,
                      warning_kinds=[logic.KIND_NOT_ENCLOSED])
        self.assertEqual(logic.STATE_NOT_PLACED, logic.classify(record))

    def test_the_unplace_warning_alone_is_enough(self):
        record = room(is_placed=True, warning_kinds=[logic.KIND_NOT_PLACED])
        self.assertEqual(logic.STATE_NOT_PLACED, logic.classify(record))

    def test_the_not_enclosed_warning_wins_over_a_nonzero_area(self):
        record = room(area_m2=12.0,
                      warning_kinds=[logic.KIND_NOT_ENCLOSED])
        self.assertEqual(logic.STATE_NOT_ENCLOSED, logic.classify(record))

    def test_a_redundant_room_keeps_its_area(self):
        record = room(warning_kinds=[logic.KIND_REDUNDANT])
        self.assertEqual(logic.STATE_REDUNDANT, logic.classify(record))

    def test_a_tiny_positive_area_still_counts_as_enclosed(self):
        self.assertEqual(logic.STATE_OK, logic.classify(room(area_m2=0.01)))

    def test_a_negative_area_is_treated_as_unenclosed(self):
        self.assertEqual(logic.STATE_NOT_ENCLOSED,
                         logic.classify(room(area_m2=-1.0)))


class DescribeTests(unittest.TestCase):
    def test_describe_does_not_mutate_the_caller(self):
        record = room()
        logic.describe([record])
        self.assertNotIn('state', record)

    def test_a_room_with_a_number_carries_data(self):
        self.assertTrue(logic.describe([room()])[0]['carries_data'])

    def test_a_room_with_neither_number_nor_name_does_not(self):
        item = logic.describe([room(number=u'', name=u'')])[0]
        self.assertFalse(item['carries_data'])

    def test_a_name_alone_is_enough_to_carry_data(self):
        item = logic.describe([room(number=u'', name=u'茶水間')])[0]
        self.assertTrue(item['carries_data'])


class DefaultSelectionTests(unittest.TestCase):
    def test_uncovered_rooms_are_selected_by_default(self):
        records = [room(1, is_placed=False), room(2, area_m2=0.0), room(3)]
        self.assertEqual([1, 2], logic.default_selected_ids(records))

    def test_redundant_rooms_are_never_pre_selected(self):
        """Which of the pair is the keeper is a question about intent."""
        records = [room(1, warning_kinds=[logic.KIND_REDUNDANT])]
        self.assertEqual([], logic.default_selected_ids(records))

    def test_healthy_rooms_are_never_pre_selected(self):
        self.assertEqual([], logic.default_selected_ids([room()]))

    def test_an_empty_model_selects_nothing(self):
        self.assertEqual([], logic.default_selected_ids([]))


class FilterTests(unittest.TestCase):
    def _records(self):
        return [
            room(1, number=u'101', name=u'辦公室'),
            room(2, number=u'102', name=u'茶水間', area_m2=0.0),
            room(3, number=u'B01', name=u'機房', is_placed=False),
        ]

    def test_no_filter_returns_everything(self):
        self.assertEqual(3, len(logic.filter_rooms(self._records())))

    def test_filtering_by_one_state(self):
        found = logic.filter_rooms(self._records(),
                                   states=[logic.STATE_NOT_PLACED])
        self.assertEqual([3], [item['id'] for item in found])

    def test_filtering_by_the_uncovered_pair(self):
        found = logic.filter_rooms(self._records(),
                                   states=logic.UNCOVERED_STATES)
        self.assertEqual([2, 3], sorted(item['id'] for item in found))

    def test_query_matches_the_number(self):
        found = logic.filter_rooms(self._records(), query=u'B0')
        self.assertEqual([3], [item['id'] for item in found])

    def test_query_matches_the_name(self):
        found = logic.filter_rooms(self._records(), query=u'茶水')
        self.assertEqual([2], [item['id'] for item in found])

    def test_query_ignores_case(self):
        found = logic.filter_rooms(self._records(), query=u'b01')
        self.assertEqual([3], [item['id'] for item in found])

    def test_query_ignores_spacing(self):
        records = [room(1, number=u'A 101', name=u'')]
        self.assertEqual(1, len(logic.filter_rooms(records, query=u'a101')))

    def test_state_and_query_both_apply(self):
        found = logic.filter_rooms(self._records(),
                                   states=[logic.STATE_NOT_ENCLOSED],
                                   query=u'茶水')
        self.assertEqual([2], [item['id'] for item in found])

    def test_a_query_matching_nothing_returns_nothing(self):
        self.assertEqual([], logic.filter_rooms(self._records(),
                                                query=u'zzz'))


class PlanTests(unittest.TestCase):
    def test_only_the_selected_ids_are_deleted(self):
        records = [room(1), room(2), room(3)]
        plan = logic.build_plan(records, [1, 3])
        self.assertEqual([1, 3], plan['ids'])

    def test_an_id_that_is_not_in_the_model_is_ignored(self):
        plan = logic.build_plan([room(1)], [1, 99])
        self.assertEqual([1], plan['ids'])

    def test_nothing_selected_is_no_work(self):
        plan = logic.build_plan([room(1)], [])
        self.assertFalse(logic.has_work(plan))
        self.assertIn(u'沒有選到任何房間', logic.plan_lines(plan))

    def test_rooms_group_by_state_worst_first(self):
        records = [room(1), room(2, area_m2=0.0), room(3, is_placed=False)]
        plan = logic.build_plan(records, [1, 2, 3])
        self.assertEqual([logic.STATE_NOT_PLACED, logic.STATE_NOT_ENCLOSED,
                          logic.STATE_OK],
                         [group['state'] for group in plan['groups']])

    def test_deleting_a_healthy_room_is_called_out(self):
        """The one case where the user is destroying something that works."""
        plan = logic.build_plan([room(1)], [1])
        self.assertEqual(1, len(plan['normal']))
        self.assertIn(u'「正常」房間', logic.plan_lines(plan))

    def test_a_purely_uncovered_batch_raises_no_alarm(self):
        records = [room(1, is_placed=False), room(2, area_m2=0.0)]
        text = logic.plan_lines(logic.build_plan(records, [1, 2]))
        self.assertNotIn(u'「正常」房間', text)

    def test_rooms_carrying_data_are_counted(self):
        records = [room(1, number=u'101'), room(2, number=u'', name=u'')]
        plan = logic.build_plan(records, [1, 2])
        self.assertEqual(1, len(plan['named']))
        self.assertIn(u'一併消失', logic.plan_lines(plan))

    def test_total_available_reports_the_whole_model(self):
        plan = logic.build_plan([room(1), room(2), room(3)], [1])
        self.assertEqual(3, plan['total_available'])
        self.assertIn(u'共 3 個', logic.plan_lines(plan))


class BackupTests(unittest.TestCase):
    def test_the_header_row_comes_first(self):
        rows = logic.backup_rows(logic.build_plan([room(1)], [1]))
        self.assertEqual(list(logic.BACKUP_COLUMNS), rows[0])

    def test_one_row_per_deleted_room(self):
        records = [room(1), room(2), room(3)]
        rows = logic.backup_rows(logic.build_plan(records, [1, 2]))
        self.assertEqual(3, len(rows))

    def test_the_row_records_identity_geometry_and_state(self):
        rows = logic.backup_rows(logic.build_plan(
            [room(1, number=u'101', name=u'辦公室', area_m2=24.5)], [1]))
        self.assertEqual(u'101', rows[1][1])
        self.assertEqual(u'辦公室', rows[1][2])
        self.assertAlmostEqual(24.5, rows[1][4], 6)
        self.assertEqual(logic.STATE_OK, rows[1][6])

    def test_the_column_count_matches_the_width_spec(self):
        """A short widths list silently leaves the last columns unsized."""
        self.assertEqual(len(logic.BACKUP_COLUMNS),
                         len(logic.backup_spec()['widths']))

    def test_an_empty_plan_still_produces_a_header(self):
        rows = logic.backup_rows(logic.build_plan([room(1)], []))
        self.assertEqual(1, len(rows))


if __name__ == '__main__':
    unittest.main()
