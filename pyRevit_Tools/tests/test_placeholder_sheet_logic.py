# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import placeholder_sheet_logic as logic


def sheet(sheet_id=1, number=u'A-101', name=u'一層平面圖', **overrides):
    record = {
        'id': sheet_id,
        'number': number,
        'name': name,
        'is_sheet': True,
        'is_placeholder': True,
    }
    record.update(overrides)
    return record


class PrefixTests(unittest.TestCase):
    def test_a_dashed_number_splits_at_the_dash(self):
        self.assertEqual(u'A-', logic.sheet_prefix(u'A-101'))

    def test_a_run_together_number_still_splits(self):
        self.assertEqual(u'SK', logic.sheet_prefix(u'SK12'))

    def test_a_multi_letter_discipline_prefix(self):
        self.assertEqual(u'ST-', logic.sheet_prefix(u'ST-04'))

    def test_a_pure_number_has_no_prefix(self):
        self.assertEqual(logic.NO_PREFIX, logic.sheet_prefix(u'101'))

    def test_a_blank_number_has_no_prefix(self):
        self.assertEqual(logic.NO_PREFIX, logic.sheet_prefix(u''))
        self.assertEqual(logic.NO_PREFIX, logic.sheet_prefix(None))

    def test_a_number_with_no_digits_at_all(self):
        self.assertEqual(logic.NO_PREFIX, logic.sheet_prefix(u'封面'))

    def test_the_prefix_is_shown_as_typed_not_folded(self):
        """It goes in front of a person, so case must survive."""
        self.assertEqual(u'a-', logic.sheet_prefix(u'a-101'))


class SortTests(unittest.TestCase):
    def test_ten_sorts_after_two(self):
        """Text ordering would put A-10 first, which reads as a bug."""
        records = [sheet(1, u'A-10'), sheet(2, u'A-2'), sheet(3, u'A-1')]
        ordered = sorted(records, key=logic.sheet_sort_key)
        self.assertEqual([u'A-1', u'A-2', u'A-10'],
                         [item['number'] for item in ordered])

    def test_prefixes_group_before_numbers_decide(self):
        records = [sheet(1, u'S-1'), sheet(2, u'A-2'), sheet(3, u'A-1')]
        ordered = sorted(records, key=logic.sheet_sort_key)
        self.assertEqual([u'A-1', u'A-2', u'S-1'],
                         [item['number'] for item in ordered])

    def test_a_blank_number_does_not_crash_the_sort(self):
        records = [sheet(1, u'A-1'), sheet(2, u'')]
        self.assertEqual(2, len(sorted(records, key=logic.sheet_sort_key)))


class BlockTests(unittest.TestCase):
    def test_a_placeholder_is_convertible(self):
        self.assertEqual(u'', logic.block_reason(sheet()))

    def test_a_real_sheet_is_blocked(self):
        self.assertEqual(logic.BLOCK_NOT_PLACEHOLDER,
                         logic.block_reason(sheet(is_placeholder=False)))

    def test_a_non_sheet_element_is_blocked(self):
        """The selection path can hand us anything the user had highlighted."""
        self.assertEqual(logic.BLOCK_NOT_A_SHEET,
                         logic.block_reason(sheet(is_sheet=False)))

    def test_not_a_sheet_outranks_not_a_placeholder(self):
        record = sheet(is_sheet=False, is_placeholder=False)
        self.assertEqual(logic.BLOCK_NOT_A_SHEET, logic.block_reason(record))


class WarningTests(unittest.TestCase):
    def test_a_complete_sheet_warns_about_nothing(self):
        self.assertEqual([], logic.warnings_for(sheet()))

    def test_a_blank_number_warns(self):
        self.assertIn(logic.WARN_NO_NUMBER, logic.warnings_for(sheet(number=u'')))

    def test_a_blank_name_warns(self):
        self.assertIn(logic.WARN_NO_NAME, logic.warnings_for(sheet(name=u'')))

    def test_whitespace_only_counts_as_blank(self):
        self.assertIn(logic.WARN_NO_NUMBER,
                      logic.warnings_for(sheet(number=u'   ')))

    def test_a_warning_does_not_block(self):
        plan = logic.build_plan([sheet(number=u'')])
        self.assertEqual(1, plan['count'])
        self.assertEqual([], plan['blocked'])
        self.assertEqual(1, len(plan['warnings']))


class GroupTests(unittest.TestCase):
    def test_sheets_group_by_discipline_prefix(self):
        records = [sheet(1, u'A-1'), sheet(2, u'S-1'), sheet(3, u'A-2')]
        groups = logic.group_by_prefix(records)
        self.assertEqual([u'A-', u'S-'],
                         [group['prefix'] for group in groups])
        self.assertEqual(2, len(groups[0]['records']))

    def test_each_group_is_naturally_ordered(self):
        records = [sheet(1, u'A-10'), sheet(2, u'A-2')]
        group = logic.group_by_prefix(records)[0]
        self.assertEqual([u'A-2', u'A-10'],
                         [item['number'] for item in group['records']])

    def test_groups_are_listed_alphabetically(self):
        records = [sheet(1, u'M-1'), sheet(2, u'A-1'), sheet(3, u'E-1')]
        self.assertEqual([u'A-', u'E-', u'M-'],
                         [g['prefix'] for g in logic.group_by_prefix(records)])

    def test_numberless_sheets_land_in_their_own_group(self):
        groups = logic.group_by_prefix([sheet(1, u'A-1'), sheet(2, u'')])
        self.assertIn(logic.NO_PREFIX, [g['prefix'] for g in groups])


class PlanTests(unittest.TestCase):
    def test_a_clean_batch_converts_everything(self):
        plan = logic.build_plan([sheet(1, u'A-1'), sheet(2, u'A-2')])
        self.assertEqual(2, plan['count'])
        self.assertEqual([1, 2], plan['ids'])
        self.assertTrue(logic.has_work(plan))

    def test_real_sheets_are_separated_out_not_converted(self):
        plan = logic.build_plan([sheet(1, u'A-1'),
                                 sheet(2, u'A-2', is_placeholder=False)])
        self.assertEqual([1], plan['ids'])
        self.assertEqual(1, len(plan['blocked']))

    def test_the_convert_list_is_naturally_ordered(self):
        plan = logic.build_plan([sheet(1, u'A-10'), sheet(2, u'A-2')])
        self.assertEqual([2, 1], plan['ids'])

    def test_an_all_blocked_batch_has_no_work(self):
        plan = logic.build_plan([sheet(1, is_placeholder=False)])
        self.assertFalse(logic.has_work(plan))
        self.assertEqual([], plan['ids'])

    def test_an_empty_batch_is_handled(self):
        plan = logic.build_plan([])
        self.assertFalse(logic.has_work(plan))
        self.assertEqual([], plan['groups'])

    def test_groups_only_cover_what_will_actually_convert(self):
        """A blocked sheet in the preview groups would overstate the batch."""
        plan = logic.build_plan([sheet(1, u'A-1'),
                                 sheet(2, u'S-1', is_placeholder=False)])
        self.assertEqual([u'A-'], [g['prefix'] for g in plan['groups']])


class ReportTests(unittest.TestCase):
    def test_the_count_and_the_numbers_are_both_stated(self):
        text = logic.plan_lines(
            logic.build_plan([sheet(1, u'A-1'), sheet(2, u'A-2')]))
        self.assertIn(u'2 張', text)
        self.assertIn(u'A-1', text)

    def test_a_long_group_is_truncated_with_a_total(self):
        records = [sheet(index, u'A-{}'.format(index))
                   for index in range(1, 21)]
        text = logic.plan_lines(logic.build_plan(records))
        self.assertIn(u'等 20 張', text)

    def test_blocked_items_are_summarised_by_reason(self):
        plan = logic.build_plan([sheet(1, is_placeholder=False),
                                 sheet(2, is_placeholder=False)])
        text = logic.plan_lines(plan)
        self.assertIn(logic.BLOCK_NOT_PLACEHOLDER, text)
        self.assertIn(u'2 項', text)

    def test_warnings_are_surfaced_in_the_preview(self):
        text = logic.plan_lines(logic.build_plan([sheet(1, number=u'')]))
        self.assertIn(logic.WARN_NO_NUMBER, text)

    def test_an_empty_plan_says_so_plainly(self):
        self.assertIn(u'沒有可轉換的佔位圖紙',
                      logic.plan_lines(logic.build_plan([])))


if __name__ == '__main__':
    unittest.main()
