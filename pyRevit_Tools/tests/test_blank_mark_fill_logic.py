# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import blank_mark_fill_logic as logic


def record(element_id, current=u'', type_id=100, type_name=u'單開門',
           family_name=u'M_門', type_mark=u'', other=u'', curtain=False,
           category=u'門', level=u'1F', elevation=0.0,
           writable=logic.STATUS_OK):
    return {
        'id': element_id,
        'type_id': type_id,
        'current': current,
        'type_name': type_name,
        'family_name': family_name,
        'type_mark': type_mark,
        'other': other,
        'curtain': curtain,
        'category': category,
        'level': level,
        'level_elevation': elevation,
        'writable': writable,
    }


class BlankDetectionTests(unittest.TestCase):
    def test_whitespace_forms_are_blank(self):
        self.assertTrue(logic.is_blank(None))
        self.assertTrue(logic.is_blank(u''))
        self.assertTrue(logic.is_blank(u'   '))
        self.assertTrue(logic.is_blank(u'　'))

    def test_a_real_mark_is_not_blank(self):
        self.assertFalse(logic.is_blank(u'D1'))


class FillFromTypeTests(unittest.TestCase):
    def test_existing_marks_are_never_touched(self):
        records = [record(1, current=u'D1', type_mark=u'D9'),
                   record(2, current=u'', type_mark=u'D9')]
        plan = logic.build_plan(records, source=logic.SOURCE_TYPE_MARK)
        self.assertEqual(1, len(plan['writes']))
        self.assertEqual(2, plan['writes'][0]['record']['id'])
        self.assertEqual(1, plan['already_filled'])

    def test_blank_source_is_blocked_not_written(self):
        plan = logic.build_plan([record(1, type_mark=u'')],
                                source=logic.SOURCE_TYPE_MARK)
        self.assertEqual([], plan['writes'])
        self.assertEqual(logic.BLOCK_EMPTY_SOURCE,
                         plan['blocked'][0]['reason'])

    def test_unwritable_parameter_is_blocked(self):
        plan = logic.build_plan(
            [record(1, type_mark=u'D9', writable=u'唯讀')],
            source=logic.SOURCE_TYPE_MARK)
        self.assertEqual([], plan['writes'])
        self.assertIn(logic.BLOCK_NOT_WRITABLE, plan['blocked'][0]['reason'])

    def test_curtain_openings_are_excluded_by_default(self):
        records = [record(1, type_mark=u'D9', curtain=True)]
        self.assertEqual(
            [], logic.build_plan(records,
                                 source=logic.SOURCE_TYPE_MARK)['writes'])
        self.assertEqual(
            1, len(logic.build_plan(records, source=logic.SOURCE_TYPE_MARK,
                                    exclude_curtain=False)['writes']))

    def test_type_name_source(self):
        plan = logic.build_plan([record(1, type_name=u'W-1')],
                                source=logic.SOURCE_TYPE_NAME)
        self.assertEqual(u'W-1', plan['writes'][0]['value'])

    def test_other_parameter_source(self):
        plan = logic.build_plan([record(1, other=u'AD-3')],
                                source=logic.SOURCE_OTHER)
        self.assertEqual(u'AD-3', plan['writes'][0]['value'])

    def test_constant_source(self):
        plan = logic.build_plan([record(1)], source=logic.SOURCE_CONSTANT,
                                options={'constant': u'TBD'})
        self.assertEqual(u'TBD', plan['writes'][0]['value'])


class CollisionTests(unittest.TestCase):
    """Filling must not manufacture the defect 10.08 reports."""

    def test_value_matching_an_existing_mark_is_refused(self):
        records = [record(1, current=u'D1', type_id=100),
                   record(2, current=u'', type_id=200, type_mark=u'D1')]
        plan = logic.build_plan(records, source=logic.SOURCE_TYPE_MARK)
        self.assertEqual([], plan['writes'])
        self.assertEqual(logic.BLOCK_COLLISION, plan['blocked'][0]['reason'])

    def test_collision_check_folds_case_and_width(self):
        records = [record(1, current=u'Ｄ１', type_id=100),
                   record(2, current=u'', type_id=200, type_mark=u'd1')]
        plan = logic.build_plan(records, source=logic.SOURCE_TYPE_MARK)
        self.assertEqual(logic.BLOCK_COLLISION, plan['blocked'][0]['reason'])

    def test_two_generated_values_colliding_with_each_other_is_refused(self):
        records = [record(1, type_id=100, type_name=u'A', type_mark=u'D5'),
                   record(2, type_id=200, type_name=u'B', type_mark=u'D5')]
        plan = logic.build_plan(records, source=logic.SOURCE_TYPE_MARK)
        self.assertEqual(1, len(plan['writes']))
        self.assertEqual(logic.BLOCK_SELF_COLLISION,
                         plan['blocked'][0]['reason'])


class TypeScopeTests(unittest.TestCase):
    """A type parameter is written once, not once per opening."""

    def test_openings_sharing_a_type_collapse_to_one_write(self):
        records = [record(1, type_id=100, type_mark=u'D1'),
                   record(2, type_id=100, type_mark=u'D1'),
                   record(3, type_id=100, type_mark=u'D1')]
        plan = logic.build_plan(records, target_scope=logic.TARGET_TYPE,
                                source=logic.SOURCE_TYPE_MARK)
        self.assertEqual(1, len(plan['writes']))
        self.assertEqual(3, plan['writes'][0]['instance_count'])
        self.assertEqual(3, plan['affected_instances'])

    def test_instance_scope_keeps_them_separate(self):
        records = [record(1, type_id=100, type_mark=u'D1'),
                   record(2, type_id=100, type_mark=u'D1')]
        plan = logic.build_plan(records, target_scope=logic.TARGET_INSTANCE,
                                source=logic.SOURCE_TYPE_MARK)
        # Instance scope means two separate cells, so the shared source value
        # is a genuine self-collision rather than one write.
        self.assertEqual(1, len(plan['writes']))
        self.assertEqual(logic.BLOCK_SELF_COLLISION,
                         plan['blocked'][0]['reason'])


class SequenceTests(unittest.TestCase):
    def test_numbers_follow_the_sort_order(self):
        records = [record(3, category=u'窗', elevation=0.0, type_name=u'W'),
                   record(1, category=u'門', elevation=0.0, type_name=u'D'),
                   record(2, category=u'門', elevation=-10.0, type_name=u'D')]
        plan = logic.build_plan(
            records, source=logic.SOURCE_SEQUENCE,
            options={'prefix': u'N', 'start': 1, 'pad': 0})
        pairs = [(row['record']['id'], row['value'])
                 for row in plan['writes']]
        self.assertEqual([(2, u'N1'), (1, u'N2'), (3, u'N3')], pairs)

    def test_doors_number_before_windows(self):
        """Not codepoint order — 窗 (U+7A97) would otherwise beat 門 (U+9580)."""
        records = [record(1, category=u'窗', type_name=u'W'),
                   record(2, category=u'門', type_name=u'D')]
        plan = logic.build_plan(
            records, source=logic.SOURCE_SEQUENCE,
            options={'prefix': u'N', 'start': 1, 'pad': 0})
        self.assertEqual([(2, u'N1'), (1, u'N2')],
                         [(row['record']['id'], row['value'])
                          for row in plan['writes']])

    def test_zero_padding(self):
        records = [record(index) for index in range(1, 4)]
        plan = logic.build_plan(
            records, source=logic.SOURCE_SEQUENCE,
            options={'prefix': u'D', 'start': 9, 'pad': 3})
        self.assertEqual([u'D009', u'D010', u'D011'],
                         [row['value'] for row in plan['writes']])

    def test_sequence_skipping_an_existing_mark_is_reported_as_gapped(self):
        records = [record(1, current=u'D2'), record(2), record(3)]
        plan = logic.build_plan(
            records, source=logic.SOURCE_SEQUENCE,
            options={'prefix': u'D', 'start': 1, 'pad': 0})
        self.assertTrue(logic.sequence_is_gapped(plan))
        self.assertEqual(logic.BLOCK_COLLISION, plan['blocked'][0]['reason'])

    def test_clean_sequence_is_not_gapped(self):
        plan = logic.build_plan(
            [record(1), record(2)], source=logic.SOURCE_SEQUENCE,
            options={'prefix': u'X', 'start': 1, 'pad': 0})
        self.assertFalse(logic.sequence_is_gapped(plan))

    def test_copy_sources_are_never_gapped(self):
        records = [record(1, type_mark=u''), record(2, type_mark=u'D2')]
        plan = logic.build_plan(records, source=logic.SOURCE_TYPE_MARK)
        self.assertTrue(plan['blocked'])
        self.assertFalse(logic.sequence_is_gapped(plan))


class GuardTests(unittest.TestCase):
    def test_unknown_scope_and_source_rejected(self):
        self.assertRaises(ValueError, logic.build_plan, [], 'sideways')
        self.assertRaises(
            ValueError, logic.build_plan, [], logic.TARGET_INSTANCE, 'magic')

    def test_summary_reports_both_directions(self):
        records = [record(1, current=u'D1'), record(2, type_mark=u'D2'),
                   record(3, type_mark=u'')]
        plan = logic.build_plan(records, source=logic.SOURCE_TYPE_MARK)
        text = logic.plan_lines(plan, u'註記 Mark')
        self.assertIn(u'已有編號、不動：1 樘', text)
        self.assertIn(u'將寫入 1 樘', text)
        self.assertIn(logic.BLOCK_EMPTY_SOURCE, text)


if __name__ == '__main__':
    unittest.main()
