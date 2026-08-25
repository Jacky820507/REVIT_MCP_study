# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import project_parameter_logic as logic


def param(param_id=u'g1', name=u'棟別', guid=u'g1', is_shared=True,
          binding_kind=logic.BINDING_INSTANCE, categories=None,
          group=u'資料'):
    return {
        'id': param_id,
        'name': name,
        'guid': guid,
        'is_shared': is_shared,
        'binding_kind': binding_kind,
        'categories': [u'牆'] if categories is None else categories,
        'group': group,
    }


class KeywordTests(unittest.TestCase):
    def test_an_empty_keyword_matches_everything(self):
        self.assertTrue(logic.matches_keyword(param(), u''))

    def test_the_name_is_searchable(self):
        self.assertTrue(logic.matches_keyword(param(name=u'棟別'), u'棟'))

    def test_the_category_is_searchable(self):
        record = param(name=u'X', categories=[u'牆', u'樓板'])
        self.assertTrue(logic.matches_keyword(record, u'樓板'))

    def test_the_group_is_searchable(self):
        self.assertTrue(logic.matches_keyword(param(group=u'資料'), u'資料'))

    def test_every_term_must_appear(self):
        record = param(name=u'棟別', categories=[u'牆'])
        self.assertTrue(logic.matches_keyword(record, u'棟 牆'))
        self.assertFalse(logic.matches_keyword(record, u'棟 樓板'))

    def test_matching_ignores_case(self):
        self.assertTrue(logic.matches_keyword(param(name=u'Phase'), u'PHASE'))

    def test_a_non_match_is_rejected(self):
        self.assertFalse(logic.matches_keyword(param(name=u'棟別'), u'防火'))


class FilterTests(unittest.TestCase):
    def _records(self):
        return [
            param(u'a', name=u'棟別', categories=[u'牆'],
                  binding_kind=logic.BINDING_INSTANCE),
            param(u'b', name=u'防火時效', categories=[u'牆', u'門'],
                  binding_kind=logic.BINDING_TYPE),
            param(u'c', name=u'樓層用途', categories=[u'樓板'],
                  binding_kind=logic.BINDING_INSTANCE),
        ]

    def test_no_filter_returns_everything(self):
        self.assertEqual(3, len(logic.filter_parameters(self._records())))

    def test_filter_by_keyword(self):
        found = logic.filter_parameters(self._records(), keyword=u'防火')
        self.assertEqual([u'b'], [item['id'] for item in found])

    def test_filter_by_binding_kind(self):
        found = logic.filter_parameters(self._records(),
                                        binding_kind=logic.BINDING_TYPE)
        self.assertEqual([u'b'], [item['id'] for item in found])

    def test_filter_by_category_matches_any_of_the_bound_categories(self):
        found = logic.filter_parameters(self._records(), categories=[u'門'])
        self.assertEqual([u'b'], [item['id'] for item in found])

    def test_filters_combine_with_and(self):
        found = logic.filter_parameters(self._records(), keyword=u'棟',
                                        categories=[u'樓板'])
        self.assertEqual([], found)

    def test_a_category_filter_matching_nothing_returns_nothing(self):
        self.assertEqual([], logic.filter_parameters(self._records(),
                                                     categories=[u'天花板']))

    def test_all_categories_lists_every_bound_category_once(self):
        """Set equality, not a hand-guessed collation: sorted() orders CJK by
        codepoint, which is not an order anyone would predict."""
        found = logic.all_categories(self._records())
        self.assertEqual(set([u'門', u'牆', u'樓板']), set(found))
        self.assertEqual(len(found), len(set(found)))

    def test_all_categories_is_deterministic(self):
        records = self._records()
        self.assertEqual(logic.all_categories(records),
                         logic.all_categories(records))


class GroupTests(unittest.TestCase):
    def test_instance_and_type_are_separate_groups(self):
        records = [param(u'a', binding_kind=logic.BINDING_INSTANCE),
                   param(u'b', name=u'B', binding_kind=logic.BINDING_TYPE)]
        groups = logic.group_by_binding(records)
        self.assertEqual([logic.BINDING_INSTANCE, logic.BINDING_TYPE],
                         [g['binding_kind'] for g in groups])

    def test_an_empty_group_is_not_listed(self):
        records = [param(u'a', binding_kind=logic.BINDING_INSTANCE)]
        self.assertEqual(1, len(logic.group_by_binding(records)))

    def test_records_inside_a_group_are_ordered_by_name(self):
        records = [param(u'a', name=u'Z'), param(u'b', name=u'A')]
        group = logic.group_by_binding(records)[0]
        self.assertEqual([u'A', u'Z'],
                         [item['name'] for item in group['records']])

    def test_an_unknown_binding_still_appears(self):
        groups = logic.group_by_binding([param(u'a', binding_kind=u'')])
        self.assertEqual(1, len(groups))


class PlanTests(unittest.TestCase):
    def test_a_shared_parameter_transfers(self):
        plan = logic.build_plan([param(u'a')], [u'a'], [], [])
        self.assertEqual(1, plan['count'])
        self.assertTrue(logic.has_work(plan))

    def test_a_non_shared_parameter_is_blocked_not_converted(self):
        """Recreating it as shared would silently change what it is."""
        plan = logic.build_plan([param(u'a', is_shared=False)], [u'a'], [], [])
        self.assertEqual(0, plan['count'])
        self.assertEqual(logic.BLOCK_NOT_SHARED, plan['blocked'][0]['reason'])

    def test_a_guid_already_bound_in_the_target_is_blocked(self):
        plan = logic.build_plan([param(u'a', guid=u'G-1')], [u'a'],
                                [u'G-1'], [])
        self.assertEqual(logic.BLOCK_ALREADY_BOUND,
                         plan['blocked'][0]['reason'])

    def test_a_name_taken_by_a_different_guid_is_blocked(self):
        """Two same-named parameters are indistinguishable in every dialog."""
        plan = logic.build_plan([param(u'a', name=u'棟別', guid=u'G-1')],
                                [u'a'], [u'G-2'], [u'棟別'])
        self.assertEqual(logic.BLOCK_NAME_TAKEN, plan['blocked'][0]['reason'])

    def test_not_shared_outranks_the_other_reasons(self):
        record = param(u'a', name=u'棟別', guid=u'G-1', is_shared=False)
        plan = logic.build_plan([record], [u'a'], [u'G-1'], [u'棟別'])
        self.assertEqual(logic.BLOCK_NOT_SHARED, plan['blocked'][0]['reason'])

    def test_guid_matching_ignores_case(self):
        plan = logic.build_plan([param(u'a', guid=u'AbC')], [u'a'],
                                [u'abc'], [])
        self.assertEqual(logic.BLOCK_ALREADY_BOUND,
                         plan['blocked'][0]['reason'])

    def test_only_selected_parameters_are_considered(self):
        records = [param(u'a'), param(u'b', name=u'B', guid=u'b')]
        plan = logic.build_plan(records, [u'a'], [], [])
        self.assertEqual([u'a'], plan['ids'])

    def test_nothing_selected_is_no_work(self):
        plan = logic.build_plan([param(u'a')], [], [], [])
        self.assertFalse(logic.has_work(plan))

    def test_the_transfer_list_is_ordered_by_binding_then_name(self):
        records = [param(u'a', name=u'Z', binding_kind=logic.BINDING_INSTANCE),
                   param(u'b', name=u'A', binding_kind=logic.BINDING_TYPE),
                   param(u'c', name=u'A', binding_kind=logic.BINDING_INSTANCE)]
        plan = logic.build_plan(records, [u'a', u'b', u'c'], [], [])
        self.assertEqual([u'c', u'a', u'b'], plan['ids'])

    def test_block_reasons_are_counted(self):
        records = [param(u'a', is_shared=False),
                   param(u'b', name=u'B', guid=u'b', is_shared=False)]
        plan = logic.build_plan(records, [u'a', u'b'], [], [])
        self.assertEqual(2, plan['block_counts'][logic.BLOCK_NOT_SHARED])


class ReportTests(unittest.TestCase):
    def test_source_and_destination_are_named(self):
        text = logic.plan_lines(logic.build_plan([param(u'a')], [u'a'], [], []),
                                u'標準.rvt', u'案子.rvt')
        self.assertIn(u'標準.rvt', text)
        self.assertIn(u'案子.rvt', text)

    def test_the_count_and_binding_breakdown_appear(self):
        text = logic.plan_lines(logic.build_plan([param(u'a')], [u'a'], [], []))
        self.assertIn(u'1 個', text)
        self.assertIn(logic.BINDING_LABELS[logic.BINDING_INSTANCE], text)

    def test_blocked_reasons_are_listed_with_counts(self):
        plan = logic.build_plan([param(u'a', is_shared=False)], [u'a'], [], [])
        text = logic.plan_lines(plan)
        self.assertIn(logic.BLOCK_NOT_SHARED, text)

    def test_the_shared_only_limitation_is_always_stated(self):
        text = logic.plan_lines(logic.build_plan([param(u'a')], [u'a'], [], []))
        self.assertIn(u'只有共用參數能跨檔移轉', text)
        self.assertIn(u'不代為轉換', text)

    def test_an_empty_plan_says_the_model_is_untouched(self):
        self.assertIn(u'模型不會變更',
                      logic.plan_lines(logic.build_plan([], [], [], [])))


if __name__ == '__main__':
    unittest.main()
