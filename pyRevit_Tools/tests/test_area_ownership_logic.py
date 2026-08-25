# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import area_ownership_logic as logic


def area(area_id=1, name=u'客廳', number=u'A-1', current=u''):
    return {
        'id': area_id,
        'name': name,
        'number': number,
        'current': current,
    }


class ClassifyTests(unittest.TestCase):
    def test_a_dwelling_space_is_suggested_exclusive(self):
        ownership, scope, reason = logic.classify(area(name=u'客廳'))
        self.assertEqual(logic.OWNERSHIP_EXCLUSIVE, ownership)
        self.assertEqual(logic.SCOPE_NONE, scope)
        self.assertIn(u'客廳', reason)

    def test_a_whole_building_service_space_is_shared_and_大公(self):
        ownership, scope, unused = logic.classify(area(name=u'發電機房'))
        self.assertEqual(logic.OWNERSHIP_SHARED, ownership)
        self.assertEqual(logic.SCOPE_WHOLE, scope)

    def test_a_floor_circulation_space_is_shared_and_小公(self):
        ownership, scope, unused = logic.classify(area(name=u'電梯梯廳'))
        self.assertEqual(logic.OWNERSHIP_SHARED, ownership)
        self.assertEqual(logic.SCOPE_FLOOR, scope)

    def test_an_unmatched_name_is_undecided_not_shared(self):
        """§3 makes 共用 the complement of 專有, but a keyword miss is not
        evidence — calling it 共用 would dress a miss as a finding."""
        ownership, scope, reason = logic.classify(area(name=u'某某空間'))
        self.assertEqual(logic.OWNERSHIP_UNDECIDED, ownership)
        self.assertIn(u'人工判定', reason)

    def test_a_blank_name_is_undecided(self):
        ownership, unused, reason = logic.classify(area(name=u''))
        self.assertEqual(logic.OWNERSHIP_UNDECIDED, ownership)
        self.assertIn(u'沒有名稱', reason)

    def test_exclusive_wins_over_shared_when_both_appear(self):
        """「住戶儲藏室」 is a unit's own store, not a shared one."""
        ownership, unused, unused2 = logic.classify(area(name=u'住戶儲藏室'))
        self.assertEqual(logic.OWNERSHIP_EXCLUSIVE, ownership)

    def test_matching_ignores_case_and_spacing(self):
        ownership, unused, unused2 = logic.classify(area(name=u'M A C H I N E'))
        self.assertEqual(logic.OWNERSHIP_SHARED, ownership)

    def test_custom_keywords_replace_the_defaults(self):
        ownership, unused, unused2 = logic.classify(
            area(name=u'客廳'), exclusive_keywords=[u'完全不同的詞'])
        self.assertEqual(logic.OWNERSHIP_UNDECIDED, ownership)

    def test_agreed_values_are_never_produced(self):
        """Both definitions contain 「經約定」; agreement is not in the model."""
        names = [u'客廳', u'機房', u'電梯', u'某某空間', u'', u'約定專用空間']
        for name in names:
            ownership, unused, unused2 = logic.classify(area(name=name))
            self.assertNotIn(ownership, (logic.OWNERSHIP_AGREED_EXCLUSIVE,
                                         logic.OWNERSHIP_AGREED_SHARED),
                             u'「{}」被自動判成約定類'.format(name))

    def test_the_reason_names_a_keyword_actually_in_the_name(self):
        """The reason has to be checkable against the name it explains."""
        for name in (u'主臥室', u'工作陽台', u'發電機房', u'電梯梯廳'):
            unused, unused2, reason = logic.classify(area(name=name))
            hit = reason.split(u'「')[1].split(u'」')[0]
            self.assertIn(hit, name,
                          u'「{}」的理由引用了不存在的關鍵字 {}'.format(name, hit))

    def test_the_longest_matching_keyword_wins(self):
        """「工作陽台」 contains 陽台 too; the specific one is the useful
        answer, and length beats list position so the result does not depend
        on how the user ordered their own keyword list."""
        self.assertEqual(u'工作陽台',
                         logic.matched_keyword(u'工作陽台',
                                               [u'陽台', u'工作陽台']))
        self.assertEqual(u'工作陽台',
                         logic.matched_keyword(u'工作陽台',
                                               [u'工作陽台', u'陽台']))

    def test_equal_length_overlaps_still_agree_on_the_class(self):
        """「主臥室」 matches both 臥室 and 主臥, which are the same length,
        so which one gets *reported* follows list order. That is cosmetic:
        both are genuinely present and both mean 專有, and this records that
        the classification itself is what stays stable."""
        forward = logic.classify(area(name=u'主臥室'),
                                 exclusive_keywords=[u'臥室', u'主臥'])
        backward = logic.classify(area(name=u'主臥室'),
                                  exclusive_keywords=[u'主臥', u'臥室'])
        self.assertEqual(forward[0], backward[0])
        self.assertEqual(logic.OWNERSHIP_EXCLUSIVE, forward[0])

    def test_reordering_does_not_change_the_class_across_lists(self):
        record = area(name=u'電梯機房')
        first = logic.classify(record)
        second = logic.classify(record)
        self.assertEqual(first, second)


class DescribeTests(unittest.TestCase):
    def test_describe_does_not_mutate_the_caller(self):
        record = area()
        logic.describe([record])
        self.assertNotIn('suggested', record)

    def test_an_existing_value_is_detected(self):
        item = logic.describe([area(current=u'專有')])[0]
        self.assertTrue(item['has_existing'])

    def test_whitespace_only_is_not_an_existing_value(self):
        item = logic.describe([area(current=u'   ')])[0]
        self.assertFalse(item['has_existing'])


class PlanTests(unittest.TestCase):
    def test_a_clean_batch_writes_everything(self):
        records = [area(1, name=u'客廳'), area(2, name=u'樓梯間')]
        plan = logic.build_plan(records)
        self.assertEqual(2, plan['count'])
        self.assertTrue(logic.has_work(plan))

    def test_existing_values_are_kept_by_default(self):
        """A filled-in value is usually a human's decision."""
        plan = logic.build_plan([area(1, name=u'客廳', current=u'共用')])
        self.assertEqual(0, plan['count'])
        self.assertEqual(1, len(plan['kept']))

    def test_overwrite_replaces_an_existing_value(self):
        plan = logic.build_plan([area(1, name=u'客廳', current=u'共用')],
                                overwrite=True)
        self.assertEqual(1, plan['count'])
        self.assertEqual(logic.OWNERSHIP_EXCLUSIVE,
                         plan['write'][0]['suggested'])

    def test_a_value_that_already_matches_is_kept_even_when_overwriting(self):
        plan = logic.build_plan([area(1, name=u'客廳', current=u'專有')],
                                overwrite=True)
        self.assertEqual(0, plan['count'])
        self.assertEqual(1, len(plan['kept']))

    def test_undecided_areas_are_never_written(self):
        plan = logic.build_plan([area(1, name=u'某某空間')], overwrite=True)
        self.assertEqual(0, plan['count'])
        self.assertEqual(1, len(plan['undecided']))

    def test_counts_are_broken_down_by_value(self):
        records = [area(1, name=u'客廳'), area(2, name=u'臥室'),
                   area(3, name=u'樓梯間')]
        plan = logic.build_plan(records)
        self.assertEqual(2, plan['counts'][logic.OWNERSHIP_EXCLUSIVE])
        self.assertEqual(1, plan['counts'][logic.OWNERSHIP_SHARED])

    def test_scope_counts_split_大公_and_小公(self):
        records = [area(1, name=u'發電機房'), area(2, name=u'電梯梯廳')]
        plan = logic.build_plan(records)
        self.assertEqual(1, plan['scope_counts'][logic.SCOPE_WHOLE])
        self.assertEqual(1, plan['scope_counts'][logic.SCOPE_FLOOR])

    def test_total_counts_every_area_considered(self):
        plan = logic.build_plan([area(1), area(2, name=u'某某空間')])
        self.assertEqual(2, plan['total'])

    def test_an_empty_input_is_handled(self):
        plan = logic.build_plan([])
        self.assertFalse(logic.has_work(plan))
        self.assertEqual(0, plan['total'])


class ReportTests(unittest.TestCase):
    def test_the_parameter_being_written_is_named(self):
        text = logic.plan_lines(logic.build_plan([area(1)]), u'權屬')
        self.assertIn(u'權屬', text)

    def test_the_breakdown_by_value_appears(self):
        records = [area(1, name=u'客廳'), area(2, name=u'樓梯間')]
        text = logic.plan_lines(logic.build_plan(records))
        self.assertIn(logic.OWNERSHIP_EXCLUSIVE, text)
        self.assertIn(logic.OWNERSHIP_SHARED, text)

    def test_undecided_areas_are_listed_by_name(self):
        text = logic.plan_lines(logic.build_plan([area(1, name=u'某某空間')]))
        self.assertIn(u'某某空間', text)
        self.assertIn(u'需人工判定', text)

    def test_kept_values_explain_why(self):
        text = logic.plan_lines(
            logic.build_plan([area(1, name=u'客廳', current=u'共用')]))
        self.assertIn(u'保留原值', text)

    def test_the_disclaimer_is_always_present(self):
        """The classification must never read as a legal finding."""
        for plan in (logic.build_plan([]), logic.build_plan([area(1)])):
            self.assertIn(u'非法律認定', logic.plan_lines(plan))
            self.assertIn(u'無法由模型判定', logic.plan_lines(plan))


if __name__ == '__main__':
    unittest.main()
