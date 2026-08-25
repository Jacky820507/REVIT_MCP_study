# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import duplicate_mark_logic as logic


def record(element_id, mark, type_name=u'單開門', family_name=u'M_門',
           curtain=False, category=u'門', level=u'1F'):
    return {
        'id': element_id,
        'mark': mark,
        'type_name': type_name,
        'family_name': family_name,
        'curtain': curtain,
        'category': category,
        'level': level,
    }


class NormalizeMarkTests(unittest.TestCase):
    def test_case_and_space_fold(self):
        self.assertEqual(u'D1', logic.normalize_mark(u' d 1 '))

    def test_fullwidth_folds_to_ascii(self):
        self.assertEqual(u'D1', logic.normalize_mark(u'Ｄ１'))

    def test_fullwidth_space_removed(self):
        self.assertEqual(u'D1', logic.normalize_mark(u'D　1'))

    def test_blank_and_none(self):
        self.assertEqual(u'', logic.normalize_mark(None))
        self.assertEqual(u'', logic.normalize_mark(u'   '))


class SplitCurtainTests(unittest.TestCase):
    def test_curtain_separated_not_dropped(self):
        records = [record(1, u'D1'), record(2, u'D1', curtain=True)]
        kept, excluded = logic.split_curtain(records)
        self.assertEqual([1], [item['id'] for item in kept])
        self.assertEqual([2], [item['id'] for item in excluded])

    def test_disabled_keeps_everything(self):
        records = [record(1, u'D1'), record(2, u'D1', curtain=True)]
        kept, excluded = logic.split_curtain(records, exclude_curtain=False)
        self.assertEqual(2, len(kept))
        self.assertEqual([], excluded)


class AnalyzeByTypeTests(unittest.TestCase):
    """門窗表 reading: many instances may share 編號, two types may not."""

    def test_same_type_repeated_is_not_a_defect(self):
        records = [record(1, u'D1'), record(2, u'D1'), record(3, u'D1')]
        report = logic.analyze(records)
        self.assertEqual([], report['groups'])
        self.assertEqual(3, report['checked'])

    def test_two_types_sharing_a_mark_is_flagged(self):
        records = [record(1, u'D1', type_name=u'單開門'),
                   record(2, u'D1', type_name=u'雙開門')]
        report = logic.analyze(records)
        self.assertEqual(1, len(report['groups']))
        group = report['groups'][0]
        self.assertEqual(u'D1', group['key'])
        self.assertEqual(2, group['type_count'])
        self.assertEqual(2, group['instance_count'])

    def test_same_type_name_in_different_families_still_collides(self):
        records = [record(1, u'D1', type_name=u'單開', family_name=u'A'),
                   record(2, u'D1', type_name=u'單開', family_name=u'B')]
        report = logic.analyze(records)
        self.assertEqual(1, len(report['groups']))

    def test_case_variants_collapse_into_one_collision(self):
        records = [record(1, u'D1', type_name=u'單開門'),
                   record(2, u'd1', type_name=u'雙開門')]
        report = logic.analyze(records)
        self.assertEqual(1, len(report['groups']))
        self.assertEqual([u'D1', u'd1'], report['groups'][0]['variants'])

    def test_curtain_excluded_removes_the_collision(self):
        records = [record(1, u'D1', type_name=u'單開門'),
                   record(2, u'D1', type_name=u'帷幕門', curtain=True)]
        self.assertEqual([], logic.analyze(records)['groups'])
        self.assertEqual(
            1,
            len(logic.analyze(records, exclude_curtain=False)['groups']))


class AnalyzeByInstanceTests(unittest.TestCase):
    """Strict reading: every opening carries its own 編號."""

    def test_same_type_repeated_is_flagged(self):
        records = [record(1, u'D1'), record(2, u'D1')]
        report = logic.analyze(
            records, distinct_by=logic.DISTINCT_BY_INSTANCE)
        self.assertEqual(1, len(report['groups']))
        self.assertEqual(2, report['flagged_instances'])

    def test_unique_marks_pass(self):
        records = [record(1, u'D1'), record(2, u'D2')]
        report = logic.analyze(
            records, distinct_by=logic.DISTINCT_BY_INSTANCE)
        self.assertEqual([], report['groups'])


class BlankAndOrderingTests(unittest.TestCase):
    def test_blanks_are_bucketed_separately_not_as_one_collision(self):
        records = [record(1, u''), record(2, None), record(3, u'  ')]
        report = logic.analyze(
            records, distinct_by=logic.DISTINCT_BY_INSTANCE)
        self.assertEqual([], report['groups'])
        self.assertEqual(3, len(report['blank']))

    def test_groups_sort_naturally(self):
        records = []
        for index, mark in enumerate([u'D10', u'D2', u'D1'], start=1):
            records.append(record(index * 10, mark, type_name=u'A'))
            records.append(record(index * 10 + 1, mark, type_name=u'B'))
        report = logic.analyze(records)
        self.assertEqual([u'D1', u'D2', u'D10'],
                         [group['key'] for group in report['groups']])

    def test_flagged_ids_are_unique_and_ordered(self):
        records = [record(7, u'D1', type_name=u'A'),
                   record(8, u'D1', type_name=u'B'),
                   record(9, u'D2', type_name=u'A')]
        report = logic.analyze(records)
        self.assertEqual([7, 8], logic.flagged_ids(report))

    def test_unknown_mode_rejected(self):
        self.assertRaises(ValueError, logic.analyze, [], 'sideways')


class ReportTextTests(unittest.TestCase):
    def test_clean_model_says_so(self):
        report = logic.analyze([record(1, u'D1')])
        text = logic.report_lines(report, u'類型註記')
        self.assertIn(u'沒有重複編號', text)

    def test_collision_summary_names_the_mark(self):
        records = [record(1, u'D1', type_name=u'A'),
                   record(2, u'D1', type_name=u'B')]
        text = logic.report_lines(logic.analyze(records), u'類型註記')
        self.assertIn(u'D1', text)
        self.assertIn(u'重複編號 1 組', text)

    def test_variant_warning_only_when_writing_differs(self):
        same = [record(1, u'D1', type_name=u'A'),
                record(2, u'D1', type_name=u'B')]
        mixed = [record(1, u'D1', type_name=u'A'),
                 record(2, u'ｄ1', type_name=u'B')]
        self.assertNotIn(
            u'寫法不一致',
            logic.group_label(logic.analyze(same)['groups'][0]))
        self.assertIn(
            u'寫法不一致',
            logic.group_label(logic.analyze(mixed)['groups'][0]))


if __name__ == '__main__':
    unittest.main()
