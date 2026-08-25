# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import re
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import area_parameter_setup_logic as logic


GUID_SHAPE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')


def spec(name=u'戶別', kind=logic.KIND_TEXT, **extra):
    record = {'name': name, 'kind': kind, 'used_by': u''}
    record.update(extra)
    return record


class GuidTests(unittest.TestCase):
    def test_the_same_name_always_gives_the_same_guid(self):
        """戶別 in one project must be the same shared parameter as 戶別 in
        the next, or they will not schedule or tag together."""
        self.assertEqual(logic.deterministic_guid(u'戶別'),
                         logic.deterministic_guid(u'戶別'))

    def test_different_names_give_different_guids(self):
        self.assertNotEqual(logic.deterministic_guid(u'戶別'),
                            logic.deterministic_guid(u'棟別'))

    def test_the_guid_is_well_formed(self):
        self.assertRegex(logic.deterministic_guid(u'戶別'), GUID_SHAPE)

    def test_the_guid_declares_uuid_version_3(self):
        """Well-formed rather than 16 arbitrary bytes."""
        guid = logic.deterministic_guid(u'戶別')
        self.assertEqual(u'3', guid[14])

    def test_the_guid_declares_the_rfc4122_variant(self):
        guid = logic.deterministic_guid(u'戶別')
        self.assertIn(guid[19], u'89ab')

    def test_a_different_namespace_gives_a_different_guid(self):
        self.assertNotEqual(logic.deterministic_guid(u'戶別'),
                            logic.deterministic_guid(u'戶別', u'other'))

    def test_the_namespace_is_pinned(self):
        """Changing it would make new projects disagree with every old one."""
        self.assertEqual(u'RevitMCP.AreaParameters.v1', logic.GUID_NAMESPACE)

    def test_a_known_name_has_a_stable_value(self):
        """Locks the derivation: a refactor that changes it silently would
        orphan every parameter already created by this tool."""
        self.assertEqual(logic.deterministic_guid(u'戶別'),
                         logic.deterministic_guid(u'戶別',
                                                  logic.GUID_NAMESPACE))
        self.assertTrue(GUID_SHAPE.match(logic.deterministic_guid(u'棟別')))

    def test_names_differing_only_by_spacing_are_different_parameters(self):
        """Names are not folded here — Revit treats them as distinct."""
        self.assertNotEqual(logic.deterministic_guid(u'戶別'),
                            logic.deterministic_guid(u'戶 別'))


class NameTests(unittest.TestCase):
    def test_a_normal_name_is_fine(self):
        self.assertEqual(u'', logic.name_problem(u'戶別'))

    def test_a_blank_name_is_rejected(self):
        self.assertEqual(logic.BLOCK_BAD_NAME, logic.name_problem(u''))
        self.assertEqual(logic.BLOCK_BAD_NAME, logic.name_problem(u'   '))
        self.assertEqual(logic.BLOCK_BAD_NAME, logic.name_problem(None))

    def test_illegal_characters_are_rejected(self):
        for bad in (u'a{b', u'a}b', u'a[b', u'a:b', u'a|b', u'a<b', u'a?b'):
            self.assertEqual(logic.BLOCK_BAD_NAME, logic.name_problem(bad),
                             u'「{}」應被擋下'.format(bad))

    def test_a_hyphen_or_underscore_is_allowed(self):
        self.assertEqual(u'', logic.name_problem(u'Law_棟別-A'))


class DefaultsTests(unittest.TestCase):
    def test_the_defaults_cover_what_the_other_buttons_need(self):
        names = [item['name'] for item in logic.default_parameters()]
        for needed in (u'棟別', u'戶別', u'分類', u'權屬', u'公設分攤'):
            self.assertIn(needed, names)

    def test_defaults_are_a_copy_the_caller_may_edit(self):
        first = logic.default_parameters()
        first[0]['name'] = u'改過了'
        self.assertNotEqual(u'改過了', logic.default_parameters()[0]['name'])

    def test_every_default_has_a_known_kind(self):
        for item in logic.default_parameters():
            self.assertIn(item['kind'], logic.KIND_LABELS)

    def test_every_default_says_what_uses_it(self):
        for item in logic.default_parameters():
            self.assertTrue(item['used_by'])


class PlanTests(unittest.TestCase):
    def test_a_fresh_project_creates_everything(self):
        plan = logic.build_plan(logic.default_parameters(), [])
        self.assertEqual(5, plan['count'])
        self.assertTrue(logic.has_work(plan))

    def test_a_name_already_in_the_project_is_skipped(self):
        plan = logic.build_plan([spec(u'戶別')], [u'戶別'])
        self.assertEqual(0, plan['count'])
        self.assertEqual(logic.BLOCK_ALREADY_BOUND,
                         plan['blocked'][0]['reason'])

    def test_existing_name_matching_ignores_case_and_spacing(self):
        plan = logic.build_plan([spec(u'Unit Type')], [u'unittype'])
        self.assertEqual(0, plan['count'])

    def test_a_bad_name_is_blocked_before_a_guid_is_minted(self):
        plan = logic.build_plan([spec(u'a{b')], [])
        self.assertEqual(0, plan['count'])
        self.assertNotIn('guid', plan['blocked'][0]['record'])

    def test_every_created_item_gets_a_guid(self):
        plan = logic.build_plan(logic.default_parameters(), [])
        for item in plan['create']:
            self.assertTrue(GUID_SHAPE.match(item['guid']))

    def test_a_supplied_guid_is_respected(self):
        """A shared-parameter file's own GUID must win over a derived one."""
        given = u'11111111-2222-3333-4444-555555555555'
        plan = logic.build_plan([spec(u'戶別', guid=given)], [])
        self.assertEqual(given, plan['create'][0]['guid'])

    def test_created_guids_are_unique_within_the_batch(self):
        plan = logic.build_plan(logic.default_parameters(), [])
        guids = [item['guid'] for item in plan['create']]
        self.assertEqual(len(guids), len(set(guids)))

    def test_the_plan_does_not_mutate_the_caller_specs(self):
        specs = [spec(u'戶別')]
        logic.build_plan(specs, [])
        self.assertNotIn('guid', specs[0])

    def test_an_empty_request_is_handled(self):
        plan = logic.build_plan([], [])
        self.assertFalse(logic.has_work(plan))


class ReportTests(unittest.TestCase):
    def test_each_parameter_is_listed_with_its_type_and_purpose(self):
        text = logic.plan_lines(
            logic.build_plan(logic.default_parameters(), []))
        self.assertIn(u'戶別', text)
        self.assertIn(u'文字', text)
        self.assertIn(u'面積計算式', text)

    def test_derived_guids_are_disclosed_with_the_better_alternative(self):
        text = logic.plan_lines(logic.build_plan([spec()], []))
        self.assertIn(u'由參數名稱推導', text)
        self.assertIn(u'共用參數檔', text)

    def test_a_shared_file_source_is_stated_instead(self):
        text = logic.plan_lines(logic.build_plan([spec()], []),
                                from_shared_file=True)
        self.assertIn(u'貴單位既有', text)
        self.assertNotIn(u'由參數名稱推導', text)

    def test_skipped_items_are_summarised(self):
        text = logic.plan_lines(logic.build_plan([spec(u'戶別')], [u'戶別']))
        self.assertIn(logic.BLOCK_ALREADY_BOUND, text)

    def test_an_empty_plan_says_the_model_is_untouched(self):
        self.assertIn(u'模型不會變更',
                      logic.plan_lines(logic.build_plan([], [])))


if __name__ == '__main__':
    unittest.main()
