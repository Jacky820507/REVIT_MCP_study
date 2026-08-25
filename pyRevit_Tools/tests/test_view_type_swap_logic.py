# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import view_type_swap_logic as logic


def section(item_id=1, type_id=10, type_name=u'建築剖面', valid=None,
            label=u'A-01 剖面', **overrides):
    record = {
        'id': item_id,
        'label': label,
        'sort_label': label,
        'type_id': type_id,
        'type_name': type_name,
        'valid_type_ids': [10, 11, 12] if valid is None else valid,
    }
    record.update(overrides)
    return record


class KindTests(unittest.TestCase):
    def test_every_kind_has_a_label(self):
        for kind in (logic.KIND_SECTION, logic.KIND_ELEV_MARKER,
                     logic.KIND_ELEV_VIEW):
            self.assertTrue(logic.kind_label(kind))

    def test_an_unknown_kind_falls_back_to_its_own_name(self):
        self.assertEqual(u'whatever', logic.kind_label('whatever'))


class IntersectionTests(unittest.TestCase):
    def test_one_element_offers_all_of_its_types(self):
        self.assertEqual([10, 11, 12],
                         logic.valid_type_intersection([section()]))

    def test_only_types_every_element_accepts_survive(self):
        """Offering the union means failing on element 27 of 40."""
        records = [section(1, valid=[10, 11, 12]),
                   section(2, valid=[11, 12, 13])]
        self.assertEqual([11, 12], logic.valid_type_intersection(records))

    def test_a_disjoint_selection_offers_nothing(self):
        records = [section(1, valid=[10]), section(2, valid=[99])]
        self.assertEqual([], logic.valid_type_intersection(records))

    def test_order_follows_the_first_element_not_the_id(self):
        """A stable picker: sorting by id reshuffles it as the model changes."""
        records = [section(1, valid=[12, 10, 11]),
                   section(2, valid=[10, 11, 12])]
        self.assertEqual([12, 10, 11], logic.valid_type_intersection(records))

    def test_duplicates_in_the_source_collapse(self):
        self.assertEqual([10, 11],
                         logic.valid_type_intersection(
                             [section(1, valid=[10, 10, 11, 11])]))

    def test_an_empty_selection_offers_nothing(self):
        self.assertEqual([], logic.valid_type_intersection([]))

    def test_an_element_with_no_valid_types_empties_the_result(self):
        records = [section(1, valid=[10, 11]), section(2, valid=[])]
        self.assertEqual([], logic.valid_type_intersection(records))


class GroupTests(unittest.TestCase):
    def test_records_group_by_their_current_type(self):
        records = [section(1, type_id=10, type_name=u'建築剖面'),
                   section(2, type_id=11, type_name=u'牆身大樣'),
                   section(3, type_id=10, type_name=u'建築剖面')]
        groups = logic.group_by_current_type(records)
        self.assertEqual(2, len(groups))
        counts = dict((group['type_name'], len(group['records']))
                      for group in groups)
        self.assertEqual(2, counts[u'建築剖面'])

    def test_groups_are_listed_by_type_name(self):
        records = [section(1, type_id=11, type_name=u'牆身大樣'),
                   section(2, type_id=10, type_name=u'建築剖面')]
        self.assertEqual([u'建築剖面', u'牆身大樣'],
                         [group['type_name']
                          for group in logic.group_by_current_type(records)])

    def test_a_missing_type_name_gets_a_placeholder(self):
        groups = logic.group_by_current_type([section(1, type_name=u'')])
        self.assertEqual(logic.NO_TYPE, groups[0]['type_name'])


class PlanTests(unittest.TestCase):
    def test_a_straightforward_swap(self):
        plan = logic.build_plan([section(1), section(2)], 11, u'牆身大樣')
        self.assertEqual(2, plan['count'])
        self.assertEqual([1, 2], plan['ids'])
        self.assertTrue(logic.has_work(plan))

    def test_elements_already_on_the_target_are_separated_not_counted(self):
        """Reporting 「已更改 2 個」 when one was already right overstates it."""
        records = [section(1, type_id=10), section(2, type_id=11)]
        plan = logic.build_plan(records, 11, u'牆身大樣')
        self.assertEqual([1], plan['ids'])
        self.assertEqual(logic.BLOCK_SAME_TYPE, plan['blocked'][0]['reason'])

    def test_an_element_that_would_refuse_the_type_is_blocked(self):
        records = [section(1, valid=[10, 11]), section(2, valid=[10])]
        plan = logic.build_plan(records, 11, u'牆身大樣')
        self.assertEqual([1], plan['ids'])
        self.assertEqual(logic.BLOCK_INVALID, plan['blocked'][0]['reason'])

    def test_same_type_outranks_invalid(self):
        """An element already on the target is not an error, whatever else."""
        plan = logic.build_plan([section(1, type_id=11, valid=[10])], 11)
        self.assertEqual(logic.BLOCK_SAME_TYPE, plan['blocked'][0]['reason'])

    def test_nothing_to_do_is_reported_plainly(self):
        plan = logic.build_plan([section(1, type_id=11)], 11, u'牆身大樣')
        self.assertFalse(logic.has_work(plan))
        self.assertIn(u'沒有需要更改的項目', logic.plan_lines(plan))

    def test_an_empty_selection_is_handled(self):
        plan = logic.build_plan([], 11, u'X')
        self.assertFalse(logic.has_work(plan))
        self.assertEqual([], plan['ids'])

    def test_the_preview_groups_only_what_will_change(self):
        records = [section(1, type_id=10, type_name=u'建築剖面'),
                   section(2, type_id=11, type_name=u'牆身大樣')]
        plan = logic.build_plan(records, 11, u'牆身大樣')
        self.assertEqual([u'建築剖面'],
                         [group['type_name'] for group in plan['groups']])


class ReportTests(unittest.TestCase):
    def test_the_target_type_is_named(self):
        text = logic.plan_lines(logic.build_plan([section(1)], 11, u'牆身大樣'))
        self.assertIn(u'牆身大樣', text)
        self.assertIn(u'1 個', text)

    def test_the_current_type_is_named_so_the_swap_is_readable(self):
        text = logic.plan_lines(logic.build_plan([section(1)], 11, u'牆身大樣'))
        self.assertIn(u'建築剖面', text)

    def test_a_long_group_is_truncated_with_a_total(self):
        records = [section(index, label=u'A-{}'.format(index))
                   for index in range(1, 16)]
        text = logic.plan_lines(logic.build_plan(records, 11, u'牆身大樣'))
        self.assertIn(u'等 15 個', text)

    def test_blocked_items_are_summarised_by_reason(self):
        records = [section(1, type_id=11), section(2, type_id=11)]
        text = logic.plan_lines(logic.build_plan(records, 11, u'牆身大樣'))
        self.assertIn(logic.BLOCK_SAME_TYPE, text)
        self.assertIn(u'2 個', text)

    def test_a_missing_target_name_does_not_print_empty_quotes(self):
        text = logic.plan_lines(logic.build_plan([section(1)], 11))
        self.assertIn(logic.NO_TYPE, text)


if __name__ == '__main__':
    unittest.main()
