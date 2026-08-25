# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import area_dedup_logic as logic


def area(area_id=1, number=u'', name=u''):
    return {'id': area_id, 'number': number, 'name': name}


class CarriesDataTests(unittest.TestCase):
    def test_a_number_counts(self):
        self.assertTrue(logic.carries_data(area(1, number=u'A-1')))

    def test_a_name_counts(self):
        self.assertTrue(logic.carries_data(area(1, name=u'客廳')))

    def test_blank_does_not(self):
        self.assertFalse(logic.carries_data(area(1)))

    def test_whitespace_only_does_not(self):
        self.assertFalse(logic.carries_data(area(1, number=u'  ',
                                                 name=u'\t')))


class ResolveGroupTests(unittest.TestCase):
    def test_the_only_one_with_data_is_kept(self):
        group = [area(1), area(2, number=u'A-1'), area(3)]
        keeper, deletes, reason = logic.resolve_group(group)
        self.assertEqual(2, keeper['id'])
        self.assertEqual([1, 3], sorted(item['id'] for item in deletes))
        self.assertEqual(logic.KEEP_ONLY_WITH_DATA, reason)

    def test_several_with_data_is_left_to_a_human(self):
        """Two records of the same space; deleting either loses something."""
        group = [area(1, number=u'A-1'), area(2, name=u'客廳')]
        keeper, deletes, reason = logic.resolve_group(group)
        self.assertIsNone(keeper)
        self.assertEqual([], deletes)
        self.assertEqual(logic.UNDECIDED_MANY_WITH_DATA, reason)

    def test_an_undecided_group_never_deletes_anything(self):
        group = [area(1, number=u'A-1'), area(2, number=u'A-2'), area(3)]
        keeper, deletes, unused = logic.resolve_group(group)
        self.assertIsNone(keeper)
        self.assertEqual([], deletes)

    def test_all_blank_keeps_the_lowest_id(self):
        keeper, deletes, reason = logic.resolve_group(
            [area(7), area(3), area(9)])
        self.assertEqual(3, keeper['id'])
        self.assertEqual([7, 9], sorted(item['id'] for item in deletes))
        self.assertEqual(logic.KEEP_LOWEST_ID, reason)

    def test_the_blank_keeper_is_stable_across_input_order(self):
        """Re-running must find nothing left to do, not churn a new survivor."""
        forward = logic.resolve_group([area(3), area(7), area(9)])
        backward = logic.resolve_group([area(9), area(7), area(3)])
        self.assertEqual(forward[0]['id'], backward[0]['id'])

    def test_a_group_of_one_is_not_a_duplicate(self):
        keeper, deletes, reason = logic.resolve_group([area(1)])
        self.assertIsNone(keeper)
        self.assertEqual([], deletes)
        self.assertEqual(logic.UNDECIDED_TOO_FEW, reason)

    def test_an_empty_group_is_handled(self):
        keeper, deletes, unused = logic.resolve_group([])
        self.assertIsNone(keeper)
        self.assertEqual([], deletes)

    def test_the_keeper_is_never_in_the_delete_list(self):
        for group in ([area(1), area(2, number=u'A')],
                      [area(1), area(2), area(3)]):
            keeper, deletes, unused = logic.resolve_group(group)
            if keeper is not None:
                self.assertNotIn(keeper['id'],
                                 [item['id'] for item in deletes])


class PlanTests(unittest.TestCase):
    def test_a_resolvable_group_contributes_deletions(self):
        plan = logic.build_plan([[area(1), area(2, number=u'A-1')]])
        self.assertEqual(1, plan['delete_count'])
        self.assertEqual([1], plan['delete_ids'])
        self.assertTrue(logic.has_work(plan))

    def test_an_undecided_group_contributes_none(self):
        plan = logic.build_plan([[area(1, number=u'A'), area(2, name=u'B')]])
        self.assertEqual(0, plan['delete_count'])
        self.assertFalse(logic.has_work(plan))
        self.assertEqual(1, len(plan['undecided']))

    def test_resolved_and_undecided_groups_coexist(self):
        groups = [
            [area(1), area(2, number=u'A-1')],
            [area(3, number=u'B'), area(4, name=u'C')],
        ]
        plan = logic.build_plan(groups)
        self.assertEqual(1, len(plan['resolved']))
        self.assertEqual(1, len(plan['undecided']))
        self.assertEqual(2, plan['group_count'])

    def test_delete_ids_span_every_resolved_group(self):
        groups = [[area(1), area(2, number=u'A')],
                  [area(3), area(4, number=u'B')]]
        plan = logic.build_plan(groups)
        self.assertEqual([1, 3], sorted(plan['delete_ids']))

    def test_no_groups_is_no_work(self):
        plan = logic.build_plan([])
        self.assertFalse(logic.has_work(plan))
        self.assertEqual(0, plan['group_count'])

    def test_a_keeper_is_never_scheduled_for_deletion(self):
        groups = [[area(1), area(2, number=u'A-1'), area(3)],
                  [area(4), area(5)]]
        plan = logic.build_plan(groups)
        keepers = [entry['keeper']['id'] for entry in plan['resolved']]
        for keeper in keepers:
            self.assertNotIn(keeper, plan['delete_ids'])


class ReportTests(unittest.TestCase):
    def test_a_clean_model_says_so(self):
        self.assertIn(u'沒有偵測到', logic.plan_lines(logic.build_plan([])))

    def test_the_keeper_and_its_reason_are_shown(self):
        text = logic.plan_lines(
            logic.build_plan([[area(1), area(2, number=u'A-1')]]))
        self.assertIn(u'A-1', text)
        self.assertIn(logic.KEEP_ONLY_WITH_DATA, text)

    def test_undecided_groups_say_nothing_will_be_deleted(self):
        text = logic.plan_lines(
            logic.build_plan([[area(1, number=u'A'), area(2, name=u'B')]]))
        self.assertIn(u'不會刪除', text)
        self.assertIn(logic.UNDECIDED_MANY_WITH_DATA, text)

    def test_line_deletions_are_announced_when_present(self):
        text = logic.plan_lines(logic.build_plan([]), line_delete_count=7)
        self.assertIn(u'7 條', text)

    def test_no_line_message_when_there_are_none(self):
        text = logic.plan_lines(logic.build_plan([]))
        self.assertNotIn(u'重複的區域線', text)

    def test_the_data_loss_warning_is_always_present(self):
        for plan in (logic.build_plan([]),
                     logic.build_plan([[area(1), area(2, number=u'A')]])):
            self.assertIn(u'一起消失', logic.plan_lines(plan))


if __name__ == '__main__':
    unittest.main()
