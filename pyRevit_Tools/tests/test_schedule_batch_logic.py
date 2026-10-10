# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import schedule_batch_logic as logic


class NameTests(unittest.TestCase):
    def test_sanitize_replaces_forbidden_chars(self):
        self.assertEqual(logic.sanitize_name(u'A:B|C?'), u'A-B-C-')

    def test_sanitize_empty_falls_back(self):
        self.assertEqual(logic.sanitize_name(u'  '), u'明細表')

    def test_render_replaces_placeholder(self):
        self.assertEqual(logic.render_name(u'{category}明細表', u'牆'),
                         u'牆明細表')

    def test_render_default_template(self):
        self.assertEqual(logic.render_name(u'', u'門'), u'門明細表')

    def test_render_without_placeholder_appends_category(self):
        self.assertEqual(logic.render_name(u'數量-', u'窗'), u'數量-窗')

    def test_render_placeholder_in_middle(self):
        self.assertEqual(logic.render_name(u'A_{category}_v1', u'牆'),
                         u'A_牆_v1')


class PlanTests(unittest.TestCase):
    def test_plain_create(self):
        plans = logic.plan_creations([u'牆', u'門'], u'{category}明細表',
                                     [], logic.CONFLICT_SKIP)
        self.assertEqual([p['status'] for p in plans], ['create', 'create'])
        self.assertEqual([p['name'] for p in plans], [u'牆明細表', u'門明細表'])

    def test_skip_on_conflict(self):
        plans = logic.plan_creations([u'牆'], u'{category}明細表',
                                     [u'牆明細表'], logic.CONFLICT_SKIP)
        self.assertEqual(plans[0]['status'], 'skip')

    def test_conflict_is_case_insensitive(self):
        plans = logic.plan_creations([u'Walls'], u'{category}-S',
                                     [u'walls-s'], logic.CONFLICT_SKIP)
        self.assertEqual(plans[0]['status'], 'skip')

    def test_suffix_numbers_past_taken(self):
        plans = logic.plan_creations(
            [u'牆'], u'{category}明細表', [u'牆明細表', u'牆明細表 (2)'],
            logic.CONFLICT_SUFFIX)
        self.assertEqual(plans[0]['status'], 'create')
        self.assertEqual(plans[0]['name'], u'牆明細表 (3)')

    def test_batch_internal_collision_is_handled(self):
        # 樣板沒有 {category}、又碰到相同品類名兩次
        plans = logic.plan_creations([u'牆', u'牆'], u'{category}明細表', [],
                                     logic.CONFLICT_SUFFIX)
        self.assertEqual([p['name'] for p in plans],
                         [u'牆明細表', u'牆明細表 (2)'])

    def test_batch_internal_collision_skip(self):
        plans = logic.plan_creations([u'牆', u'牆'], u'{category}明細表', [],
                                     logic.CONFLICT_SKIP)
        self.assertEqual([p['status'] for p in plans], ['create', 'skip'])

    def test_summarize(self):
        plans = [{'status': 'create'}, {'status': 'skip'},
                 {'status': 'create'}]
        self.assertEqual(logic.summarize(plans), {'create': 2, 'skip': 1})


class FieldTests(unittest.TestCase):
    def test_union_keeps_first_case_and_owners(self):
        union = logic.field_union([(u'牆', [u'Mark', u'面積']),
                                   (u'門', [u'mark', u'寬度'])])
        self.assertEqual([n for n, unused in union],
                         sorted([u'Mark', u'面積', u'寬度'],
                                key=lambda s: s.lower()))
        owners = dict(union)
        self.assertEqual(owners[u'Mark'], [u'牆', u'門'])
        self.assertEqual(owners[u'寬度'], [u'門'])

    def test_union_ignores_blank_and_duplicate_within_group(self):
        union = logic.field_union([(u'牆', [u'A', u'a', u' ', u''])])
        self.assertEqual(union, [(u'A', [u'牆'])])

    def test_resolve_found_and_missing(self):
        found, missing = logic.resolve_fields(
            [u'mark', u'不存在', u'面積', u'MARK'], [u'Mark', u'面積'])
        self.assertEqual(found, [u'Mark', u'面積'])
        self.assertEqual(missing, [u'不存在'])

    def test_split_by_presence(self):
        to_add, already = logic.split_by_presence(
            [u'Mark', u'面積'], [u'mark'])
        self.assertEqual(to_add, [u'面積'])
        self.assertEqual(already, [u'Mark'])


if __name__ == '__main__':
    unittest.main()
