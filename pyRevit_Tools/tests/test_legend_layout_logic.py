# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import legend_layout_logic as logic


def item(item_id=1, width=1000.0, height=2100.0, min_x=0.0, min_y=0.0,
         text=u''):
    return {'id': item_id, 'width_mm': width, 'height_mm': height,
            'min_x_mm': min_x, 'min_y_mm': min_y, 'text': text}


def record(record_id=1, label=u'D1', parameters=None, values=None):
    return {'id': record_id, 'label': label,
            'parameters': list(parameters or []),
            'values': dict(values or {})}


class ParameterUnionTests(unittest.TestCase):
    def test_the_union_keeps_first_appearance_order(self):
        """順序反映族群作者安排的閱讀順序，排序會把它打亂。"""
        records = [record(1, parameters=[u'寬度', u'高度']),
                   record(2, parameters=[u'高度', u'防火時效'])]
        self.assertEqual([u'寬度', u'高度', u'防火時效'],
                         logic.parameter_union(records))

    def test_a_parameter_only_the_second_type_has_still_appears(self):
        """取聯集才不會因為第一個類型剛好沒有就讓它從清單裡消失。"""
        records = [record(1, parameters=[u'寬度']),
                   record(2, parameters=[u'玻璃材料'])]
        self.assertIn(u'玻璃材料', logic.parameter_union(records))

    def test_no_records_give_no_parameters(self):
        self.assertEqual([], logic.parameter_union([]))
        self.assertEqual([], logic.parameter_union(None))


class ComposeTextTests(unittest.TestCase):
    def test_each_chosen_parameter_becomes_a_line(self):
        text, unused = logic.compose_text(
            record(values={u'寬度': u'900', u'高度': u'2100'}),
            [u'寬度', u'高度'])
        self.assertEqual(u'寬度：900\n高度：2100', text)

    def test_the_line_order_follows_the_chosen_list_not_the_values(self):
        text, unused = logic.compose_text(
            record(values={u'高度': u'2100', u'寬度': u'900'}),
            [u'寬度', u'高度'])
        self.assertTrue(text.startswith(u'寬度'))

    def test_a_missing_parameter_is_omitted_and_reported(self):
        text, missing = logic.compose_text(
            record(values={u'寬度': u'900'}), [u'寬度', u'防火時效'])
        self.assertEqual(u'寬度：900', text)
        self.assertEqual([u'防火時效'], missing)

    def test_a_missing_parameter_can_be_kept_as_a_blank_line(self):
        """留空讓每一格行數一致而對得齊；省略比較乾淨。兩者都有道理，
        所以是選項而不是內建決定。"""
        text, missing = logic.compose_text(
            record(values={u'寬度': u'900'}), [u'寬度', u'防火時效'],
            include_missing=True)
        self.assertEqual(u'寬度：900\n防火時效：', text)
        self.assertEqual([u'防火時效'], missing)

    def test_an_empty_string_value_is_not_treated_as_missing(self):
        """參數存在但沒填值，跟這個族群根本沒有這個參數是兩件事。"""
        text, missing = logic.compose_text(
            record(values={u'防火時效': u''}), [u'防火時效'])
        self.assertEqual(u'防火時效：', text)
        self.assertEqual([], missing)

    def test_choosing_no_parameters_gives_no_text(self):
        text, unused = logic.compose_text(record(), [])
        self.assertEqual(u'', text)


class ChunkTests(unittest.TestCase):
    def test_items_split_evenly(self):
        self.assertEqual([[1, 2], [3, 4], [5]], logic.chunk([1, 2, 3, 4, 5], 2))

    def test_a_full_last_row_is_not_padded(self):
        self.assertEqual([[1, 2], [3, 4]], logic.chunk([1, 2, 3, 4], 2))

    def test_zero_or_negative_means_one_row(self):
        self.assertEqual([[1, 2, 3]], logic.chunk([1, 2, 3], 0))
        self.assertEqual([[1, 2, 3]], logic.chunk([1, 2, 3], -5))

    def test_nothing_in_no_rows_out(self):
        """沒有東西就是沒有列。回一個空列會讓排版多跑一圈空迴圈。"""
        self.assertEqual([], logic.chunk([], 3))
        self.assertEqual([], logic.chunk([], 0))
        self.assertEqual([], logic.chunk(None, 3))


class HorizontalLayoutTests(unittest.TestCase):
    def test_bottoms_line_up_even_when_heights_differ(self):
        """一扇 3000 的窗和一扇 2100 的門並排，底緣必須同高——
        置中會讓窗台浮在不同高度，置頂會讓門懸空。"""
        items = [item(1, height=3000.0), item(2, height=2100.0)]
        moves = logic.plan_layout(items, 2, (0.0, 0.0))
        bottoms = [move['y_mm'] for move in moves]
        self.assertEqual(bottoms[0], bottoms[1])

    def test_the_row_hangs_below_the_origin_by_its_tallest_item(self):
        items = [item(1, height=3000.0), item(2, height=2100.0)]
        moves = logic.plan_layout(items, 2, (0.0, 0.0))
        self.assertAlmostEqual(-3000.0, moves[0]['y_mm'], 6)

    def test_gaps_between_boxes_are_equal_not_the_pitch(self):
        """等中心距會讓寬元件之間幾乎貼在一起、窄元件之間空一大片。"""
        items = [item(1, width=500.0), item(2, width=3000.0),
                 item(3, width=800.0)]
        moves = logic.plan_layout(items, 3, (0.0, 0.0), gap_x_mm=200.0)
        first_gap = moves[1]['x_mm'] - (moves[0]['x_mm'] + 500.0)
        second_gap = moves[2]['x_mm'] - (moves[1]['x_mm'] + 3000.0)
        self.assertAlmostEqual(200.0, first_gap, 6)
        self.assertAlmostEqual(200.0, second_gap, 6)

    def test_the_move_is_a_delta_from_where_the_element_is_now(self):
        """MoveElement 收的是位移量，不是絕對座標。"""
        items = [item(1, min_x=1234.0, min_y=-567.0, height=2100.0)]
        moves = logic.plan_layout(items, 1, (0.0, 0.0))
        self.assertAlmostEqual(-1234.0, moves[0]['dx_mm'], 6)
        self.assertAlmostEqual(-2100.0 + 567.0, moves[0]['dy_mm'], 6)

    def test_wrapping_starts_the_next_row_below_the_tallest_of_the_previous(self):
        items = [item(1, height=3000.0), item(2, height=2100.0),
                 item(3, height=2100.0)]
        moves = logic.plan_layout(items, 2, (0.0, 0.0), gap_y_mm=500.0,
                                  text_gap_mm=0.0)
        self.assertAlmostEqual(-3000.0 - 500.0 - 2100.0, moves[2]['y_mm'], 6)

    def test_a_wrapped_row_restarts_at_the_origin_x(self):
        items = [item(1), item(2), item(3)]
        moves = logic.plan_layout(items, 2, (100.0, 0.0))
        self.assertAlmostEqual(100.0, moves[0]['x_mm'], 6)
        self.assertAlmostEqual(100.0, moves[2]['x_mm'], 6)

    def test_the_text_sits_below_the_component_bottom(self):
        moves = logic.plan_layout([item(1, height=2100.0)], 1, (0.0, 0.0),
                                  text_gap_mm=150.0)
        self.assertAlmostEqual(-2100.0 - 150.0, moves[0]['text_y_mm'], 6)

    def test_left_aligned_text_starts_at_the_component_left_edge(self):
        moves = logic.plan_layout([item(1, width=1000.0)], 1, (50.0, 0.0),
                                  text_align=logic.TEXT_LEFT)
        self.assertAlmostEqual(50.0, moves[0]['text_x_mm'], 6)

    def test_centred_text_sits_at_the_component_centre(self):
        moves = logic.plan_layout([item(1, width=1000.0)], 1, (50.0, 0.0),
                                  text_align=logic.TEXT_CENTER)
        self.assertAlmostEqual(550.0, moves[0]['text_x_mm'], 6)

    def test_text_height_pushes_the_next_row_further_down(self):
        items = [item(1, height=2000.0), item(2, height=2000.0)]
        without = logic.plan_layout(items, 1, (0.0, 0.0), gap_y_mm=0.0,
                                    text_gap_mm=0.0, text_height_mm=0.0)
        with_text = logic.plan_layout(items, 1, (0.0, 0.0), gap_y_mm=0.0,
                                      text_gap_mm=0.0, text_height_mm=300.0)
        self.assertLess(with_text[1]['y_mm'], without[1]['y_mm'])

    def test_an_empty_list_lays_out_nothing(self):
        self.assertEqual([], logic.plan_layout([], 3, (0.0, 0.0)))


class VerticalLayoutTests(unittest.TestCase):
    def test_a_column_stacks_downward(self):
        items = [item(1, height=2000.0), item(2, height=2000.0)]
        moves = logic.plan_layout(items, 2, (0.0, 0.0),
                                  direction=logic.LAYOUT_VERTICAL,
                                  gap_y_mm=100.0, text_gap_mm=0.0)
        self.assertLess(moves[1]['y_mm'], moves[0]['y_mm'])

    def test_columns_share_the_same_left_edge(self):
        items = [item(1), item(2)]
        moves = logic.plan_layout(items, 2, (0.0, 0.0),
                                  direction=logic.LAYOUT_VERTICAL)
        self.assertAlmostEqual(moves[0]['x_mm'], moves[1]['x_mm'], 6)

    def test_the_next_column_clears_the_widest_of_the_previous(self):
        items = [item(1, width=500.0), item(2, width=3000.0), item(3)]
        moves = logic.plan_layout(items, 2, (0.0, 0.0),
                                  direction=logic.LAYOUT_VERTICAL,
                                  gap_x_mm=200.0)
        self.assertAlmostEqual(3000.0 + 200.0, moves[2]['x_mm'], 6)

    def test_every_column_starts_at_the_origin_top(self):
        items = [item(1, height=2000.0), item(2, height=2000.0),
                 item(3, height=2000.0)]
        moves = logic.plan_layout(items, 2, (0.0, 0.0),
                                  direction=logic.LAYOUT_VERTICAL)
        self.assertAlmostEqual(moves[0]['y_mm'], moves[2]['y_mm'], 6)


class BoundsTests(unittest.TestCase):
    def test_the_bounds_cover_every_component(self):
        items = [item(1, width=1000.0, height=2000.0),
                 item(2, width=500.0, height=3000.0)]
        moves = logic.plan_layout(items, 2, (0.0, 0.0), gap_x_mm=100.0)
        left, bottom, right, top = logic.bounds_of(moves, items)
        self.assertAlmostEqual(0.0, left, 6)
        self.assertAlmostEqual(1000.0 + 100.0 + 500.0, right, 6)
        self.assertAlmostEqual(-3000.0, bottom, 6)
        self.assertAlmostEqual(0.0, top, 6)

    def test_no_moves_have_no_bounds(self):
        self.assertIsNone(logic.bounds_of([]))


class PlanTests(unittest.TestCase):
    def test_a_clean_batch_produces_one_row_per_type(self):
        records = [record(1, u'D1', [u'寬度'], {u'寬度': u'900'}),
                   record(2, u'W1', [u'寬度'], {u'寬度': u'1200'})]
        plan = logic.build_plan(records, [u'寬度'], 4,
                                logic.LAYOUT_HORIZONTAL)
        self.assertEqual(2, len(plan['rows']))
        self.assertTrue(logic.has_work(plan))

    def test_a_record_without_an_id_is_blocked_and_named(self):
        plan = logic.build_plan([record(None, u'壞掉')], [], 4,
                                logic.LAYOUT_HORIZONTAL)
        self.assertEqual(0, len(plan['rows']))
        self.assertEqual(logic.BLOCK_NO_SYMBOL, plan['blocked'][0]['reason'])

    def test_missing_parameters_ride_along_on_the_row(self):
        records = [record(1, u'D1', [u'寬度'], {u'寬度': u'900'})]
        plan = logic.build_plan(records, [u'寬度', u'防火時效'], 4,
                                logic.LAYOUT_HORIZONTAL)
        self.assertEqual([u'防火時效'], plan['rows'][0]['missing'])

    def test_per_line_never_falls_below_one(self):
        """0 會讓 chunk 把全部塞成一列，那不是使用者要的「每列 0 個」。"""
        plan = logic.build_plan([], [], 0, logic.LAYOUT_HORIZONTAL)
        self.assertEqual(1, plan['per_line'])

    def test_an_empty_plan_has_no_work(self):
        self.assertFalse(logic.has_work(logic.build_plan([], [], 4,
                                                         logic.LAYOUT_HORIZONTAL)))


class SummaryTests(unittest.TestCase):
    def _plan(self):
        records = [record(1, u'D1', [u'寬度'], {u'寬度': u'900'}),
                   record(2, u'W1', [u'寬度'], {})]
        return logic.build_plan(records, [u'寬度', u'防火時效'], 3,
                                logic.LAYOUT_HORIZONTAL)

    def test_the_summary_states_the_count_and_the_parameters(self):
        text = logic.plan_lines(self._plan(), u'圖例 1')
        self.assertIn(u'2 個', text)
        self.assertIn(u'寬度', text)
        self.assertIn(u'圖例 1', text)

    def test_the_summary_warns_about_types_missing_parameters(self):
        """一個沒印出來的參數行，看圖的人不會知道它被略過了。"""
        self.assertIn(u'缺少部分參數', logic.plan_lines(self._plan()))

    def test_choosing_no_parameters_is_stated_rather_than_left_blank(self):
        plan = logic.build_plan([record(1)], [], 3, logic.LAYOUT_HORIZONTAL)
        self.assertIn(u'不列出參數文字', logic.plan_lines(plan))

    def test_the_summary_names_the_layout(self):
        plan = logic.build_plan([record(1)], [], 3, logic.LAYOUT_VERTICAL)
        text = logic.plan_lines(plan)
        self.assertIn(u'欄', text)
        self.assertIn(u'3', text)


if __name__ == '__main__':
    unittest.main()
