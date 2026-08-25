# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import area_purge_logic as logic


def area(area_id, number=u'', name=u''):
    return {'id': area_id, 'number': number, 'name': name,
            'level': u'1F', 'scheme': u'法定面積'}


def view(view_id, lines=None, areas=None, label=None, is_area_plan=True):
    ids = [a['id'] for a in (areas or [])]
    return {
        'view_id': view_id,
        'view_label': label or u'面積平面 {}'.format(view_id),
        'scheme': u'法定面積',
        'level': u'1F',
        'is_area_plan': is_area_plan,
        'line_ids': list(lines or []),
        'area_ids': ids,
        'areas': list(areas or []),
    }


class TargetTests(unittest.TestCase):
    def _views(self):
        return [view(1, lines=[10, 11], areas=[area(20), area(21)])]

    def test_both_takes_everything(self):
        plan = logic.build_plan(self._views(), logic.TARGET_BOTH)
        self.assertEqual(2, plan['line_count'])
        self.assertEqual(2, plan['area_count'])

    def test_lines_only_leaves_areas_alone(self):
        plan = logic.build_plan(self._views(), logic.TARGET_LINES)
        self.assertEqual(2, plan['line_count'])
        self.assertEqual(0, plan['area_count'])

    def test_areas_only_leaves_lines_alone(self):
        plan = logic.build_plan(self._views(), logic.TARGET_AREAS)
        self.assertEqual(0, plan['line_count'])
        self.assertEqual(2, plan['area_count'])

    def test_unknown_target_rejected(self):
        self.assertRaises(ValueError, logic.build_plan, [], 'sideways')


class DeduplicationTests(unittest.TestCase):
    """Two plans over the same scheme and level show the same elements."""

    def test_the_same_elements_seen_twice_are_deleted_once(self):
        shared_areas = [area(20), area(21)]
        plan = logic.build_plan([
            view(1, lines=[10, 11], areas=shared_areas),
            view(2, lines=[10, 11], areas=shared_areas)])
        self.assertEqual(2, plan['line_count'])
        self.assertEqual(2, plan['area_count'])
        self.assertTrue(plan['has_overlap'])

    def test_each_view_reports_what_it_shows_and_what_it_adds(self):
        shared = [area(20)]
        plan = logic.build_plan([
            view(1, lines=[10], areas=shared),
            view(2, lines=[10], areas=shared)])
        first, second = plan['views']
        self.assertEqual(1, first['shows_lines'])
        self.assertEqual(1, first['adds_lines'])
        self.assertEqual(1, second['shows_lines'])
        self.assertEqual(0, second['adds_lines'])

    def test_distinct_views_do_not_flag_an_overlap(self):
        plan = logic.build_plan([
            view(1, lines=[10], areas=[area(20)]),
            view(2, lines=[11], areas=[area(21)])])
        self.assertEqual(2, plan['line_count'])
        self.assertFalse(plan['has_overlap'])

    def test_repeated_ids_inside_one_view_collapse(self):
        plan = logic.build_plan([view(1, lines=[10, 10, 11])])
        self.assertEqual(2, plan['line_count'])

    def test_area_records_are_collected_once(self):
        shared = [area(20, u'A1')]
        plan = logic.build_plan([view(1, areas=shared),
                                 view(2, areas=shared)])
        self.assertEqual(1, len(plan['areas']))

    def test_area_records_only_come_from_areas_being_deleted(self):
        plan = logic.build_plan([view(1, lines=[10], areas=[area(20, u'A1')])],
                                logic.TARGET_LINES)
        self.assertEqual([], plan['areas'])


class BlockingTests(unittest.TestCase):
    def test_non_area_plan_is_skipped(self):
        plan = logic.build_plan([view(1, lines=[10], is_area_plan=False)])
        self.assertEqual([], plan['line_ids'])
        self.assertEqual(logic.BLOCK_NOT_AREA_PLAN,
                         plan['blocked'][0]['reason'])

    def test_empty_view_is_skipped(self):
        plan = logic.build_plan([view(1)])
        self.assertEqual(logic.BLOCK_EMPTY, plan['blocked'][0]['reason'])
        self.assertFalse(logic.has_work(plan))

    def test_a_view_empty_for_this_target_is_skipped(self):
        plan = logic.build_plan([view(1, areas=[area(20)])],
                                logic.TARGET_LINES)
        self.assertEqual(logic.BLOCK_EMPTY, plan['blocked'][0]['reason'])


class DeleteOrderTests(unittest.TestCase):
    def test_areas_are_deleted_before_their_boundary_lines(self):
        """A line still bounding an area is what Revit warns about."""
        plan = logic.build_plan([view(1, lines=[10], areas=[area(20)])])
        order = logic.delete_ids(plan)
        self.assertEqual([20, 10], order)

    def test_delete_ids_covers_everything_once(self):
        shared = [area(20)]
        plan = logic.build_plan([view(1, lines=[10], areas=shared),
                                 view(2, lines=[10], areas=shared)])
        order = logic.delete_ids(plan)
        self.assertEqual(2, len(order))
        self.assertEqual(len(order), len(set(order)))


class NamedAreaTests(unittest.TestCase):
    def test_areas_with_a_number_or_name_are_singled_out(self):
        plan = logic.build_plan([view(1, areas=[
            area(20, u'A1', u'客廳'), area(21), area(22, name=u'陽台')])])
        named = logic.numbered_areas(plan)
        self.assertEqual([20, 22], sorted(a['id'] for a in named))

    def test_blank_fields_are_not_counted_as_data(self):
        plan = logic.build_plan([view(1, areas=[area(20, u'  ', u'')])])
        self.assertEqual([], logic.numbered_areas(plan))


class ReportTests(unittest.TestCase):
    def test_nothing_to_do_says_so(self):
        self.assertIn(u'沒有可清除的項目',
                      logic.plan_lines(logic.build_plan([view(1)])))

    def test_counts_are_reported_as_deduplicated(self):
        plan = logic.build_plan([view(1, lines=[10], areas=[area(20)]),
                                 view(2, lines=[10], areas=[area(20)])])
        text = logic.plan_lines(plan)
        self.assertIn(u'區域線 1 條、面積 1 個', text)
        self.assertIn(u'不是各視圖相加', text)

    def test_no_overlap_note_when_views_are_distinct(self):
        plan = logic.build_plan([view(1, lines=[10]), view(2, lines=[11])])
        self.assertNotIn(u'不是各視圖相加', logic.plan_lines(plan))

    def test_named_areas_are_called_out_before_deletion(self):
        plan = logic.build_plan([view(1, areas=[area(20, u'A1', u'客廳')])])
        text = logic.plan_lines(plan)
        self.assertIn(u'帶有編號或名稱', text)
        self.assertIn(u'A1', text)

    def test_blocked_views_are_summarised(self):
        plan = logic.build_plan([view(1, lines=[10]),
                                 view(2, is_area_plan=False)])
        self.assertIn(logic.BLOCK_NOT_AREA_PLAN, logic.plan_lines(plan))


if __name__ == '__main__':
    unittest.main()
