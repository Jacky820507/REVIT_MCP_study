# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import area_boundary_regen_logic as logic


def seg(seg_id, x1, y1, x2, y2, room_id=1, room_number=None):
    return {'id': seg_id, 'room_id': room_id,
            'room_number': (u'R{}'.format(room_id) if room_number is None
                            else room_number),
            'points': [(float(x1), float(y1)), (float(x2), float(y2))]}


def existing(line_id, x1, y1, x2, y2):
    return {'id': line_id,
            'points': [(float(x1), float(y1)), (float(x2), float(y2))]}


class PlanFromRoomsTests(unittest.TestCase):
    def test_empty_plan_draws_everything(self):
        rooms = [seg(1, 0, 0, 1000, 0), seg(2, 1000, 0, 1000, 1000)]
        plan = logic.plan_from_rooms(rooms, [])
        self.assertEqual(2, len(plan['draws']))
        self.assertEqual([], plan['deletes'])
        self.assertTrue(logic.has_work(plan))

    def test_shared_wall_between_two_rooms_becomes_one_line(self):
        """Both rooms report the wall between them; it is still one wall."""
        rooms = [seg(1, 0, 0, 1000, 0, room_id=1),
                 seg(2, 1000, 0, 0, 0, room_id=2)]
        plan = logic.plan_from_rooms(rooms, [])
        self.assertEqual(1, len(plan['draws']))
        self.assertEqual(logic.SKIP_SHARED_BOUNDARY,
                         plan['skipped'][0]['reason'])

    def test_line_already_drawn_is_skipped(self):
        plan = logic.plan_from_rooms([seg(1, 0, 0, 1000, 0)],
                                     [existing(9, 0, 0, 1000, 0)])
        self.assertEqual([], plan['draws'])
        self.assertEqual(logic.SKIP_ALREADY_PRESENT,
                         plan['skipped'][0]['reason'])

    def test_second_run_draws_nothing(self):
        """Idempotence: regenerating over its own output is a no-op."""
        rooms = [seg(1, 0, 0, 1000, 0), seg(2, 1000, 0, 1000, 1000)]
        first = logic.plan_from_rooms(rooms, [])
        produced = [{'id': 100 + index, 'points': row['points']}
                    for index, row in enumerate(first['draws'])]
        second = logic.plan_from_rooms(rooms, produced)
        self.assertEqual([], second['draws'])
        self.assertFalse(logic.has_work(second))

    def test_clearing_makes_existing_lines_stop_suppressing(self):
        """With everything going away, nothing is redundant any more."""
        rooms = [seg(1, 0, 0, 1000, 0)]
        target = [existing(9, 0, 0, 1000, 0)]
        kept = logic.plan_from_rooms(rooms, target, clear_existing=False)
        cleared = logic.plan_from_rooms(rooms, target, clear_existing=True)
        self.assertEqual([], kept['draws'])
        self.assertEqual(1, len(cleared['draws']))
        self.assertEqual([9], logic.delete_ids(cleared))

    def test_unreadable_geometry_is_blocked(self):
        plan = logic.plan_from_rooms([{'id': 1, 'points': []}], [])
        self.assertEqual([], plan['draws'])
        self.assertEqual(logic.BLOCK_NO_GEOMETRY,
                         plan['blocked'][0]['reason'])

    def test_tolerance_controls_what_counts_as_present(self):
        rooms = [seg(1, 0, 0, 1000, 0)]
        target = [existing(9, 0, 40, 1000, 40)]
        self.assertEqual(1, len(logic.plan_from_rooms(
            rooms, target, tolerance_mm=1.0)['draws']))
        self.assertEqual(0, len(logic.plan_from_rooms(
            rooms, target, tolerance_mm=100.0)['draws']))


class PlanDedupTests(unittest.TestCase):
    def test_exact_duplicates_collapse_to_one(self):
        lines = [existing(1, 0, 0, 1000, 0), existing(2, 0, 0, 1000, 0),
                 existing(3, 0, 0, 1000, 0)]
        plan = logic.plan_dedup(lines)
        self.assertEqual(1, len(plan['keeps']))
        self.assertEqual([2, 3], logic.delete_ids(plan))

    def test_reversed_duplicate_is_still_a_duplicate(self):
        lines = [existing(1, 0, 0, 1000, 0), existing(2, 1000, 0, 0, 0)]
        plan = logic.plan_dedup(lines)
        self.assertEqual([2], logic.delete_ids(plan))

    def test_distinct_lines_are_all_kept(self):
        lines = [existing(1, 0, 0, 1000, 0), existing(2, 0, 500, 1000, 500)]
        plan = logic.plan_dedup(lines)
        self.assertEqual(2, len(plan['keeps']))
        self.assertEqual([], logic.delete_ids(plan))
        self.assertFalse(logic.has_work(plan))

    def test_survivor_is_the_first_seen_so_reruns_settle(self):
        lines = [existing(7, 0, 0, 1000, 0), existing(3, 0, 0, 1000, 0)]
        plan = logic.plan_dedup(lines)
        self.assertEqual([7], [row['id'] for row in plan['keeps']])
        second = logic.plan_dedup(plan['keeps'])
        self.assertEqual([], logic.delete_ids(second))

    def test_records_point_at_what_they_duplicate(self):
        lines = [existing(1, 0, 0, 1000, 0), existing(2, 0, 0, 1000, 0)]
        plan = logic.plan_dedup(lines)
        self.assertEqual(1, plan['deletes'][0]['record']['duplicate_of'])

    def test_unreadable_geometry_is_blocked_not_deleted(self):
        plan = logic.plan_dedup([{'id': 1, 'points': []}])
        self.assertEqual([], logic.delete_ids(plan))
        self.assertEqual(logic.BLOCK_NO_GEOMETRY,
                         plan['blocked'][0]['reason'])


class SummaryTests(unittest.TestCase):
    def test_room_summary_reports_counts(self):
        rooms = [seg(1, 0, 0, 1000, 0), seg(2, 1000, 0, 0, 0)]
        text = logic.plan_summary(logic.plan_from_rooms(rooms, []),
                                  u'B1F 面積', u'牆中心線')
        self.assertIn(u'將新增區域線：1 條', text)
        self.assertIn(logic.SKIP_SHARED_BOUNDARY, text)
        self.assertIn(u'牆中心線', text)

    def test_clear_is_called_out(self):
        plan = logic.plan_from_rooms([seg(1, 0, 0, 1000, 0)],
                                     [existing(9, 5000, 0, 6000, 0)],
                                     clear_existing=True)
        self.assertIn(u'將先刪除既有區域線：1 條',
                      logic.plan_summary(plan, u'B1F 面積'))

    def test_dedup_summary_reports_keep_and_delete(self):
        plan = logic.plan_dedup([existing(1, 0, 0, 1000, 0),
                                 existing(2, 0, 0, 1000, 0)])
        self.assertIn(u'保留 1 條，刪除重複 1 條',
                      logic.plan_summary(plan, u'B1F 面積'))

    def test_clean_plan_says_nothing_to_do(self):
        plan = logic.plan_dedup([existing(1, 0, 0, 1000, 0)])
        self.assertIn(u'沒有需要變更', logic.plan_summary(plan, u'x'))


if __name__ == '__main__':
    unittest.main()


class RoomScopeTests(unittest.TestCase):
    """Picking rooms, added when 04.02 turned out to already live here."""

    def _rows(self):
        return [seg(1, 0, 0, 1000, 0, room_id=10),
                seg(2, 1000, 0, 1000, 1000, room_id=10),
                seg(3, 0, 2000, 1000, 2000, room_id=20)]

    def test_summary_folds_segments_back_into_rooms(self):
        """A room with twelve walls is twelve rows; the picker needs one."""
        summary = logic.room_summary(self._rows())
        self.assertEqual([10, 20], [item['room_id'] for item in summary])
        self.assertEqual(2, summary[0]['segments'])
        self.assertEqual(1, summary[1]['segments'])

    def test_summary_keeps_the_room_number_for_labelling(self):
        summary = logic.room_summary([seg(1, 0, 0, 1, 0, room_id=7,
                                          room_number=u'A-101')])
        self.assertEqual(u'A-101', summary[0]['room_number'])

    def test_summary_preserves_first_seen_order(self):
        rows = [seg(1, 0, 0, 1, 0, room_id=30),
                seg(2, 0, 0, 1, 0, room_id=10)]
        self.assertEqual([30, 10],
                         [item['room_id'] for item in logic.room_summary(rows)])

    def test_summary_of_nothing_is_empty(self):
        self.assertEqual([], logic.room_summary([]))
        self.assertEqual([], logic.room_summary(None))

    def test_filtering_keeps_every_segment_of_a_chosen_room(self):
        kept = logic.filter_rooms(self._rows(), [10])
        self.assertEqual([1, 2], [row['id'] for row in kept])

    def test_filtering_drops_rooms_that_were_not_chosen(self):
        kept = logic.filter_rooms(self._rows(), [20])
        self.assertEqual([3], [row['id'] for row in kept])

    def test_no_filter_means_the_whole_level(self):
        """The behaviour this button had before rooms could be picked."""
        self.assertEqual(3, len(logic.filter_rooms(self._rows(), None)))

    def test_an_empty_choice_selects_nothing(self):
        self.assertEqual([], logic.filter_rooms(self._rows(), []))

    def test_an_unknown_room_id_matches_nothing_rather_than_crashing(self):
        self.assertEqual([], logic.filter_rooms(self._rows(), [999]))

    def test_filtering_then_planning_only_draws_the_chosen_room(self):
        kept = logic.filter_rooms(self._rows(), [20])
        plan = logic.plan_from_rooms(kept, [])
        self.assertEqual(1, len(plan['draws']))
