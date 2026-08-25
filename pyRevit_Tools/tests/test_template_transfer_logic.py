# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import template_transfer_logic as logic


def template(template_id=1, name=u'A-平面-一般', view_type=u'FloorPlan',
             doc_title=u'標準檔.rvt'):
    return {
        'id': template_id,
        'name': name,
        'view_type': view_type,
        'doc_title': doc_title,
    }


class KeywordTests(unittest.TestCase):
    def test_an_empty_keyword_matches_everything(self):
        self.assertTrue(logic.matches_keyword(template(), u''))
        self.assertTrue(logic.matches_keyword(template(), u'   '))

    def test_a_substring_of_the_name_matches(self):
        self.assertTrue(logic.matches_keyword(template(name=u'A-平面-一般'),
                                              u'平面'))

    def test_a_non_matching_keyword_does_not(self):
        self.assertFalse(logic.matches_keyword(template(name=u'A-平面-一般'),
                                               u'剖面'))

    def test_matching_ignores_case(self):
        record = template(name=u'Elevation Colour')
        self.assertTrue(logic.matches_keyword(record, u'COLOUR'))

    def test_matching_ignores_spacing(self):
        record = template(name=u'A 平面 一般')
        self.assertTrue(logic.matches_keyword(record, u'平面一般'))

    def test_punctuation_is_not_folded_away(self):
        """Hyphens carry meaning in 「A-平面-一般」 style naming, so a search
        for 平面一般 must not silently jump across them."""
        record = template(name=u'A-平面-一般')
        self.assertFalse(logic.matches_keyword(record, u'平面一般'))
        self.assertTrue(logic.matches_keyword(record, u'平面 一般'))

    def test_every_term_must_appear(self):
        """Two hundred templates need narrowing, not widening."""
        record = template(name=u'立面-彩現')
        self.assertTrue(logic.matches_keyword(record, u'立面 彩現'))
        self.assertFalse(logic.matches_keyword(record, u'立面 剖面'))

    def test_the_view_type_is_searchable_too(self):
        record = template(name=u'A-01', view_type=u'Section')
        self.assertTrue(logic.matches_keyword(record, u'section'))

    def test_filter_returns_only_matches(self):
        records = [template(1, name=u'A-平面'), template(2, name=u'B-剖面')]
        found = logic.filter_templates(records, u'剖面')
        self.assertEqual([2], [item['id'] for item in found])

    def test_filter_with_no_keyword_returns_all(self):
        records = [template(1), template(2, name=u'B')]
        self.assertEqual(2, len(logic.filter_templates(records)))


class GroupTests(unittest.TestCase):
    def test_templates_group_by_view_type(self):
        records = [template(1, view_type=u'FloorPlan'),
                   template(2, name=u'B', view_type=u'Section'),
                   template(3, name=u'C', view_type=u'FloorPlan')]
        groups = logic.group_by_view_type(records)
        counts = dict((g['view_type'], len(g['records'])) for g in groups)
        self.assertEqual(2, counts[u'FloorPlan'])
        self.assertEqual(1, counts[u'Section'])

    def test_groups_are_ordered_by_type_name(self):
        records = [template(1, view_type=u'Section'),
                   template(2, name=u'B', view_type=u'FloorPlan')]
        self.assertEqual([u'FloorPlan', u'Section'],
                         [g['view_type']
                          for g in logic.group_by_view_type(records)])

    def test_records_within_a_group_are_ordered_by_name(self):
        records = [template(1, name=u'Z'), template(2, name=u'A')]
        group = logic.group_by_view_type(records)[0]
        self.assertEqual([u'A', u'Z'],
                         [item['name'] for item in group['records']])

    def test_a_missing_view_type_gets_a_placeholder(self):
        groups = logic.group_by_view_type([template(1, view_type=u'')])
        self.assertEqual(logic.NO_TYPE, groups[0]['view_type'])

    def test_grouping_nothing_gives_nothing(self):
        self.assertEqual([], logic.group_by_view_type([]))


class PlanTests(unittest.TestCase):
    def test_only_the_selected_templates_are_copied(self):
        records = [template(1), template(2, name=u'B')]
        plan = logic.build_plan(records, [1], [])
        self.assertEqual([1], plan['ids'])

    def test_a_name_that_already_exists_is_skipped_by_default(self):
        """There is no overwrite, so the safe default is not to try."""
        records = [template(1, name=u'A-平面-一般')]
        plan = logic.build_plan(records, [1], [u'A-平面-一般'])
        self.assertEqual(0, plan['count'])
        self.assertEqual(logic.BLOCK_NAME_EXISTS, plan['blocked'][0]['reason'])

    def test_collision_matching_ignores_case_and_spacing(self):
        records = [template(1, name=u'A - Plan')]
        plan = logic.build_plan(records, [1], [u'a-plan'])
        self.assertEqual(0, plan['count'])

    def test_copying_anyway_puts_it_in_renamed_not_blocked(self):
        records = [template(1, name=u'A-平面-一般')]
        plan = logic.build_plan(records, [1], [u'A-平面-一般'],
                                skip_existing=False)
        self.assertEqual(1, plan['count'])
        self.assertEqual([], plan['blocked'])
        self.assertEqual(1, len(plan['renamed']))

    def test_a_clean_name_is_never_listed_as_renamed(self):
        plan = logic.build_plan([template(1, name=u'新樣板')], [1],
                                [u'別的樣板'], skip_existing=False)
        self.assertEqual(1, plan['count'])
        self.assertEqual([], plan['renamed'])

    def test_nothing_selected_is_no_work(self):
        plan = logic.build_plan([template(1)], [], [])
        self.assertFalse(logic.has_work(plan))
        self.assertIn(u'模型不會變更', logic.plan_lines(plan))

    def test_the_copy_list_is_ordered_by_type_then_name(self):
        records = [template(1, name=u'Z', view_type=u'FloorPlan'),
                   template(2, name=u'A', view_type=u'Section'),
                   template(3, name=u'A', view_type=u'FloorPlan')]
        plan = logic.build_plan(records, [1, 2, 3], [])
        self.assertEqual([3, 1, 2], plan['ids'])

    def test_an_empty_destination_blocks_nothing(self):
        plan = logic.build_plan([template(1), template(2, name=u'B')],
                                [1, 2], [])
        self.assertEqual(2, plan['count'])
        self.assertEqual([], plan['blocked'])


class ReportTests(unittest.TestCase):
    def test_the_source_and_destination_are_named(self):
        text = logic.plan_lines(logic.build_plan([template(1)], [1], []),
                                u'標準檔.rvt', u'案子.rvt')
        self.assertIn(u'標準檔.rvt', text)
        self.assertIn(u'案子.rvt', text)

    def test_the_count_and_view_type_breakdown_appear(self):
        text = logic.plan_lines(logic.build_plan([template(1)], [1], []))
        self.assertIn(u'1 個', text)
        self.assertIn(u'FloorPlan', text)

    def test_skipped_collisions_are_listed_by_name(self):
        records = [template(1, name=u'A-平面-一般')]
        text = logic.plan_lines(logic.build_plan(records, [1],
                                                 [u'A-平面-一般']))
        self.assertIn(u'A-平面-一般', text)
        self.assertIn(u'略過', text)

    def test_copy_anyway_warns_that_revit_picks_the_name(self):
        records = [template(1, name=u'A-平面-一般')]
        text = logic.plan_lines(logic.build_plan(records, [1],
                                                 [u'A-平面-一般'],
                                                 skip_existing=False))
        self.assertIn(u'名稱由 Revit 決定', text)

    def test_the_no_overwrite_limitation_is_always_stated(self):
        text = logic.plan_lines(logic.build_plan([template(1)], [1], []))
        self.assertIn(u'無法被覆寫', text)


if __name__ == '__main__':
    unittest.main()
