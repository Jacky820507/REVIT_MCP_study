# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import replace_titleblock_logic as logic


def block(block_id, type_id, label=u'A1圖框：標準'):
    return {'id': block_id, 'type_id': type_id, 'label': label}


def sheet(sheet_id, number, blocks, name=u'平面圖'):
    return {'id': sheet_id, 'number': number, 'name': name,
            'titleblocks': blocks}


TARGET = 900


class PlanTests(unittest.TestCase):
    def test_single_titleblock_is_changed(self):
        plan = logic.build_plan([sheet(1, u'A-101', [block(11, 5)])], TARGET)
        self.assertEqual(len(plan['change']), 1)
        self.assertEqual(plan['count'], 1)

    def test_every_titleblock_on_a_sheet_is_changed_and_flagged(self):
        plan = logic.build_plan(
            [sheet(1, u'A-101', [block(11, 5), block(12, 6)])], TARGET)
        self.assertEqual(plan['count'], 2)
        self.assertEqual(len(plan['multi']), 1)

    def test_sheet_without_titleblock_is_skipped_not_filled(self):
        plan = logic.build_plan([sheet(1, u'A-101', [])], TARGET)
        self.assertFalse(logic.has_work(plan))
        self.assertEqual(len(plan['skipped']), 1)

    def test_already_target_type_is_left_alone(self):
        plan = logic.build_plan(
            [sheet(1, u'A-101', [block(11, TARGET)])], TARGET)
        self.assertEqual(plan['count'], 0)
        self.assertEqual(len(plan['unchanged']), 1)

    def test_only_non_target_blocks_are_changed(self):
        plan = logic.build_plan(
            [sheet(1, u'A-101', [block(11, TARGET), block(12, 6)])], TARGET)
        record, todo = plan['change'][0]
        self.assertEqual([b['id'] for b in todo], [12])

    def test_natural_sheet_order(self):
        plan = logic.build_plan(
            [sheet(1, u'A-10', [block(1, 5)]), sheet(2, u'A-2', [block(2, 5)])],
            TARGET)
        self.assertEqual([r['number'] for r, unused in plan['change']],
                         [u'A-2', u'A-10'])


class LabelTests(unittest.TestCase):
    def test_label_shows_current_titleblock(self):
        label = logic.sheet_label(sheet(1, u'A-101', [block(1, 5, u'X：Y')]))
        self.assertIn(u'A-101', label)
        self.assertIn(u'X：Y', label)

    def test_label_marks_missing_titleblock(self):
        self.assertIn(u'(無圖框)', logic.sheet_label(sheet(1, u'A-1', [])))


class AlignTests(unittest.TestCase):
    def test_anchor_corners(self):
        lo, hi = (0.0, 0.0), (4.0, 2.0)
        self.assertEqual(logic.anchor_point(lo, hi, 'bottom-left'), (0.0, 0.0))
        self.assertEqual(logic.anchor_point(lo, hi, 'bottom-right'), (4.0, 0.0))
        self.assertEqual(logic.anchor_point(lo, hi, 'top-left'), (0.0, 2.0))
        self.assertEqual(logic.anchor_point(lo, hi, 'center'), (2.0, 1.0))
        self.assertIsNone(logic.anchor_point(lo, hi, logic.ANCHOR_NONE))

    def test_delta_moves_new_corner_back_to_old(self):
        self.assertEqual(logic.align_delta((1.0, 1.0), (3.0, 0.5)), (-2.0, 0.5))

    def test_delta_within_tolerance_is_none(self):
        tiny = logic.TOLERANCE_FT / 2.0
        self.assertIsNone(logic.align_delta((0.0, 0.0), (tiny, 0.0)))

    def test_missing_point_is_none(self):
        self.assertIsNone(logic.align_delta(None, (0.0, 0.0)))


if __name__ == '__main__':
    unittest.main()
