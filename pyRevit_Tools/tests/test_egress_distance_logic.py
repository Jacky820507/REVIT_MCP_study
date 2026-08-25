# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import math
import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import egress_distance_logic as logic


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


class LimitTests(unittest.TestCase):
    def test_the_default_use_group_is_the_fifty_metre_catch_all(self):
        limit, unused = logic.limit_for()
        self.assertEqual(logic.LIMIT_50_M, limit)

    def test_a_class_is_thirty_metres(self):
        limit, unused = logic.limit_for('A')
        self.assertEqual(logic.LIMIT_30_M, limit)

    def test_c_class_is_seventy_metres(self):
        limit, unused = logic.limit_for('C')
        self.assertEqual(logic.LIMIT_70_M, limit)

    def test_a_tv_studio_with_an_audience_is_thirty_not_seventy(self):
        """§93 二（一）但書：C 類唯一的例外。"""
        limit, unused = logic.limit_for('C-TV')
        self.assertEqual(logic.LIMIT_30_M, limit)

    def test_floor_fifteen_cuts_thirty_to_twenty(self):
        limit, unused = logic.limit_for('A', floor_15_or_above=True)
        self.assertEqual(logic.LIMIT_20_M, limit)

    def test_floor_fifteen_cuts_fifty_to_forty(self):
        limit, unused = logic.limit_for('OTHER', floor_15_or_above=True)
        self.assertEqual(logic.LIMIT_40_M, limit)

    def test_floor_fifteen_leaves_seventy_alone_and_says_why(self):
        """§93 二（三）只點名三十與五十。替法規補一條它沒寫的規定不是
        工具的權限，所以七十不動，但理由必須寫出來讓人自己判斷。"""
        limit, reasons = logic.limit_for('C', floor_15_or_above=True)
        self.assertEqual(logic.LIMIT_70_M, limit)
        self.assertTrue(any(u'未提及' in reason for reason in reasons))

    def test_a_duplex_floor_without_an_exit_is_capped_at_forty(self):
        limit, unused = logic.limit_for('OTHER', duplex_no_exit_floor=True)
        self.assertEqual(logic.LIMIT_40_M, limit)

    def test_the_duplex_cap_never_loosens_a_tighter_limit(self):
        limit, unused = logic.limit_for('A', duplex_no_exit_floor=True)
        self.assertEqual(logic.LIMIT_30_M, limit)

    def test_non_fire_resistant_construction_caps_everything_at_thirty(self):
        for code in ('A', 'C', 'OTHER'):
            limit, unused = logic.limit_for(code, non_fire_resistant=True)
            self.assertLessEqual(limit, logic.LIMIT_30_M,
                                 u'{} 未被 §93 二（五）壓到三十公尺'.format(code))

    def test_non_fire_resistant_does_not_raise_a_twenty_metre_limit(self):
        limit, unused = logic.limit_for('A', floor_15_or_above=True,
                                        non_fire_resistant=True)
        self.assertEqual(logic.LIMIT_20_M, limit)

    def test_an_unknown_use_group_falls_back_to_the_catch_all(self):
        limit, unused = logic.limit_for('Z-99')
        self.assertEqual(logic.LIMIT_50_M, limit)

    def test_every_reason_cites_an_article(self):
        unused, reasons = logic.limit_for('A', floor_15_or_above=True,
                                          non_fire_resistant=True)
        for reason in reasons:
            self.assertIn(u'§93', reason)

    def test_the_overlap_limit_is_half(self):
        self.assertEqual(15000.0, logic.overlap_limit_mm(logic.LIMIT_30_M))

    def test_a_bad_overlap_input_does_not_raise(self):
        self.assertEqual(0.0, logic.overlap_limit_mm(None))


class CellSizeTests(unittest.TestCase):
    def test_a_sane_size_is_left_alone(self):
        value, note = logic.clamp_cell(250.0)
        self.assertEqual(250.0, value)
        self.assertEqual(u'', note)

    def test_an_oversized_cell_is_pulled_back_because_it_seals_doorways(self):
        value, note = logic.clamp_cell(2000.0)
        self.assertEqual(logic.MAX_CELL_MM, value)
        self.assertIn(u'門洞', note)

    def test_a_tiny_cell_is_raised(self):
        value, note = logic.clamp_cell(1.0)
        self.assertEqual(logic.MIN_CELL_MM, value)
        self.assertNotEqual(u'', note)

    def test_junk_becomes_the_default(self):
        value, unused = logic.clamp_cell(None)
        self.assertEqual(logic.DEFAULT_CELL_MM, value)


class RasterTests(unittest.TestCase):
    def test_a_rectangle_yields_about_the_right_number_of_cells(self):
        cells = logic.rasterize([rect(0, 0, 1000, 1000)], (0.0, 0.0), 100.0)
        self.assertEqual(100, len(cells))

    def test_a_donut_hole_is_not_walkable(self):
        """中庭是洞，不是可走空間——偶奇規則必須讓它翻回外部。"""
        loops = [rect(0, 0, 3000, 3000), rect(1000, 1000, 2000, 2000)]
        cells = logic.rasterize(loops, (0.0, 0.0), 100.0)
        centre = (15, 15)
        self.assertNotIn(centre, cells)
        self.assertIn((2, 2), cells)

    def test_a_room_smaller_than_the_cell_can_sample_to_nothing(self):
        """這正是 VERDICT_NO_CELLS 存在的理由，不是可以忽略的邊角。"""
        cells = logic.rasterize([rect(0, 0, 30, 30)], (0.0, 0.0), 500.0)
        self.assertEqual(0, len(cells))

    def test_empty_loops_give_no_cells(self):
        self.assertEqual(set(), logic.rasterize([], (0.0, 0.0), 100.0))

    def test_a_shared_origin_makes_two_rooms_line_up(self):
        """兩個房間必須用同一個原點光柵化，否則格點對不齊，門也接不起來。"""
        left = logic.rasterize([rect(0, 0, 1000, 1000)], (0.0, 0.0), 100.0)
        right = logic.rasterize([rect(1000, 0, 2000, 1000)], (0.0, 0.0), 100.0)
        self.assertEqual(set(), left & right)
        self.assertIn((9, 0), left)
        self.assertIn((10, 0), right)


class DiscTests(unittest.TestCase):
    def test_a_disc_covers_its_centre(self):
        cells = logic.disc_cells((500.0, 500.0), 200.0, (0.0, 0.0), 100.0)
        self.assertIn((5, 5), cells)

    def test_a_zero_radius_opens_nothing(self):
        self.assertEqual(set(),
                         logic.disc_cells((500.0, 500.0), 0.0, (0.0, 0.0),
                                          100.0))

    def test_no_point_opens_nothing(self):
        self.assertEqual(set(),
                         logic.disc_cells(None, 500.0, (0.0, 0.0), 100.0))

    def test_a_bigger_radius_never_covers_less(self):
        small = logic.disc_cells((500.0, 500.0), 200.0, (0.0, 0.0), 100.0)
        large = logic.disc_cells((500.0, 500.0), 400.0, (0.0, 0.0), 100.0)
        self.assertTrue(small.issubset(large))


class DistanceFieldTests(unittest.TestCase):
    def _corridor(self, length):
        return set((col, 0) for col in range(length))

    def test_a_straight_run_measures_cell_times_steps(self):
        walkable = self._corridor(11)
        field = logic.distance_field(walkable, [(0, 0)], 100.0)
        self.assertAlmostEqual(1000.0, field[(10, 0)], 6)

    def test_the_source_itself_is_zero(self):
        field = logic.distance_field(self._corridor(3), [(0, 0)], 100.0)
        self.assertEqual(0.0, field[(0, 0)])

    def test_a_diagonal_costs_root_two(self):
        walkable = set([(0, 0), (1, 0), (0, 1), (1, 1)])
        field = logic.distance_field(walkable, [(0, 0)], 100.0)
        self.assertAlmostEqual(100.0 * math.sqrt(2.0), field[(1, 1)], 6)

    def test_a_diagonal_cannot_cut_a_wall_corner(self):
        """只有 (0,0) 與 (1,1) 可走時，斜走等於從兩道牆的交角穿過去，
        量出一條人走不了的捷徑——所以 (1,1) 必須是走不到的。"""
        walkable = set([(0, 0), (1, 1)])
        field = logic.distance_field(walkable, [(0, 0)], 100.0)
        self.assertNotIn((1, 1), field)

    def test_an_unreachable_island_is_absent_not_infinite(self):
        walkable = set([(0, 0), (5, 5)])
        field = logic.distance_field(walkable, [(0, 0)], 100.0)
        self.assertNotIn((5, 5), field)

    def test_a_wall_forces_the_detour_and_not_the_straight_line(self):
        """整個模組存在的理由：§93 要的是隔間後的可行距離。
        隔牆兩側各 500 mm，直線是 1000 mm，但唯一的路要繞過牆端。"""
        walkable = set()
        for col in range(11):
            for row in range(11):
                # 中間一道牆，只在最上緣留缺口
                if col == 5 and row < 10:
                    continue
                walkable.add((col, row))
        field = logic.distance_field(walkable, [(0, 0)], 100.0)
        straight = 10 * 100.0
        self.assertGreater(field[(10, 0)], straight * 1.5)

    def test_multiple_sources_take_the_nearest(self):
        walkable = self._corridor(11)
        field = logic.distance_field(walkable, [(0, 0), (10, 0)], 100.0)
        self.assertAlmostEqual(500.0, field[(5, 0)], 6)

    def test_a_source_outside_the_walkable_set_is_ignored(self):
        field = logic.distance_field(self._corridor(3), [(99, 99)], 100.0)
        self.assertEqual({}, field)

    def test_no_sources_reach_nothing(self):
        self.assertEqual({}, logic.distance_field(self._corridor(3), [], 100.0))

    def test_a_finer_grid_never_reports_a_longer_straight_path(self):
        """格點變細不應該讓同一條直廊變長——這鎖住成本乘以格點大小的換算。"""
        coarse = logic.distance_field(self._corridor(11), [(0, 0)], 100.0)
        fine = logic.distance_field(self._corridor(21), [(0, 0)], 50.0)
        self.assertAlmostEqual(coarse[(10, 0)], fine[(20, 0)], 6)


class EvaluateRoomTests(unittest.TestCase):
    def test_a_room_within_the_limit_passes(self):
        verdict, worst, unused, unused2 = logic.evaluate_room(
            set([(0, 0)]), {(0, 0): 1000.0}, 30000.0)
        self.assertEqual(logic.VERDICT_PASS, verdict)
        self.assertEqual(1000.0, worst)

    def test_the_worst_point_decides_not_the_average(self):
        """§93 說的是「自樓面居室之任一點」。"""
        cells = set([(0, 0), (1, 0)])
        distances = {(0, 0): 1000.0, (1, 0): 40000.0}
        verdict, worst, unused, unused2 = logic.evaluate_room(
            cells, distances, 30000.0)
        self.assertEqual(logic.VERDICT_FAIL, verdict)
        self.assertEqual(40000.0, worst)

    def test_exactly_on_the_limit_passes(self):
        verdict, unused, unused2, unused3 = logic.evaluate_room(
            set([(0, 0)]), {(0, 0): 30000.0}, 30000.0)
        self.assertEqual(logic.VERDICT_PASS, verdict)

    def test_one_unreachable_cell_blocks_a_pass(self):
        """走不到的取樣點可能是真的沒路，也可能是格點封了門洞。
        兩種都要人看，所以絕不能因為其他點都合格就放行。"""
        cells = set([(0, 0), (1, 0)])
        verdict, unused, unreached, unused2 = logic.evaluate_room(
            cells, {(0, 0): 1000.0}, 30000.0)
        self.assertEqual(logic.VERDICT_UNREACHABLE, verdict)
        self.assertEqual(1, unreached)

    def test_a_room_with_no_cells_is_reported_not_skipped(self):
        verdict, worst, unused, reason = logic.evaluate_room(
            set(), {}, 30000.0)
        self.assertEqual(logic.VERDICT_NO_CELLS, verdict)
        self.assertIsNone(worst)
        self.assertNotEqual(u'', reason)

    def test_no_verdict_other_than_pass_counts_as_compliant(self):
        self.assertNotIn(logic.VERDICT_PASS, logic.FAILING_VERDICTS)
        for verdict in (logic.VERDICT_FAIL, logic.VERDICT_UNREACHABLE,
                        logic.VERDICT_NO_CELLS):
            self.assertIn(verdict, logic.FAILING_VERDICTS)

    def test_a_failing_room_says_by_how_much(self):
        unused, unused2, unused3, reason = logic.evaluate_room(
            set([(0, 0)]), {(0, 0): 35000.0}, 30000.0)
        self.assertIn(u'5.00', reason)


class EvaluateTests(unittest.TestCase):
    def _rooms(self):
        return [
            {'id': 1, 'room_number': u'101', 'room_name': u'辦公室',
             'cells': set([(0, 0)])},
            {'id': 2, 'room_number': u'102', 'room_name': u'會議室',
             'cells': set([(1, 0)])},
        ]

    def test_counts_are_broken_down_by_verdict(self):
        result = logic.evaluate(self._rooms(),
                                {(0, 0): 1000.0, (1, 0): 90000.0}, 30000.0)
        self.assertEqual(1, result['counts'][logic.VERDICT_PASS])
        self.assertEqual(1, result['counts'][logic.VERDICT_FAIL])

    def test_failures_are_collected_separately(self):
        result = logic.evaluate(self._rooms(),
                                {(0, 0): 1000.0, (1, 0): 90000.0}, 30000.0)
        self.assertEqual(1, len(result['failed']))
        self.assertEqual(u'102', result['failed'][0]['room_number'])

    def test_evaluate_does_not_mutate_the_caller(self):
        rooms = self._rooms()
        logic.evaluate(rooms, {(0, 0): 1000.0}, 30000.0)
        self.assertIn('cells', rooms[0])
        self.assertNotIn('verdict', rooms[0])

    def test_the_cell_set_is_not_carried_into_the_report(self):
        result = logic.evaluate(self._rooms(), {(0, 0): 1000.0}, 30000.0)
        for row in result['rows']:
            self.assertNotIn('cells', row)
            self.assertIn('sample_count', row)

    def test_worst_offenders_sort_first(self):
        rooms = [
            {'id': 1, 'room_number': u'101', 'cells': set([(0, 0)])},
            {'id': 2, 'room_number': u'102', 'cells': set([(1, 0)])},
            {'id': 3, 'room_number': u'103', 'cells': set([(2, 0)])},
        ]
        distances = {(0, 0): 1000.0, (1, 0): 40000.0, (2, 0): 90000.0}
        result = logic.evaluate(rooms, distances, 30000.0)
        self.assertEqual([u'103', u'102', u'101'],
                         [row['room_number'] for row in result['rows']])

    def test_a_room_with_no_distance_sorts_ahead_of_one_with_a_number(self):
        rooms = [
            {'id': 1, 'room_number': u'101', 'cells': set([(0, 0), (9, 9)])},
            {'id': 2, 'room_number': u'102', 'cells': set()},
        ]
        result = logic.evaluate(rooms, {(0, 0): 1000.0}, 30000.0)
        self.assertEqual(logic.VERDICT_UNREACHABLE, result['rows'][0]['verdict'])

    def test_sorting_is_stable_across_runs(self):
        rooms = self._rooms()
        distances = {(0, 0): 1000.0, (1, 0): 2000.0}
        first = logic.evaluate(rooms, distances, 30000.0)
        second = logic.evaluate(rooms, distances, 30000.0)
        self.assertEqual([row['id'] for row in first['rows']],
                         [row['id'] for row in second['rows']])

    def test_the_overlap_threshold_rides_along(self):
        result = logic.evaluate([], {}, 30000.0)
        self.assertEqual(15000.0, result['overlap_limit_mm'])


class SummaryTests(unittest.TestCase):
    def test_the_summary_states_the_limit_and_its_reasons(self):
        limit, reasons = logic.limit_for('A')
        result = logic.evaluate([], {}, limit)
        lines = logic.summary_lines(result, reasons,
                                    logic.ENDPOINT_FIRST_STEP, 250.0)
        joined = u'\n'.join(lines)
        self.assertIn(u'30.0 公尺', joined)
        self.assertIn(u'§93', joined)

    def test_the_summary_never_hides_the_grid_approximation(self):
        result = logic.evaluate([], {}, 30000.0)
        joined = u'\n'.join(logic.summary_lines(result))
        self.assertIn(u'高估', joined)

    def test_the_summary_quotes_the_endpoint_rule(self):
        result = logic.evaluate([], {}, 30000.0)
        joined = u'\n'.join(
            logic.summary_lines(result, endpoint=logic.ENDPOINT_STAIR_DOOR))
        self.assertIn(u'第一階', joined)
        self.assertIn(u'防火門', joined)

    def test_the_summary_says_article_95_is_not_measured(self):
        """報一個沒有量的數字比不報更危險，所以必須寫明只給門檻。"""
        result = logic.evaluate([], {}, 30000.0)
        joined = u'\n'.join(logic.summary_lines(result))
        self.assertIn(u'§95', joined)
        self.assertIn(u'未量測', joined)


class EndToEndTests(unittest.TestCase):
    def test_two_rooms_joined_only_by_a_door(self):
        """整條管線一次跑完：兩個房間隔一道 200 mm 的牆，唯一的通路是門。
        沒有門就走不到，有門就走得到——而且路徑要穿過門的位置。"""
        cell = 100.0
        origin = (0.0, 0.0)
        left = logic.rasterize([rect(0, 0, 2000, 2000)], origin, cell)
        right = logic.rasterize([rect(2200, 0, 4200, 2000)], origin, cell)

        without_door = left | right
        field = logic.distance_field(without_door, sorted(left)[:1], cell)
        self.assertTrue(all(c not in field for c in right))

        door = logic.disc_cells((2100.0, 1000.0), 400.0, origin, cell)
        with_door = left | right | door
        stair = set([(41, 10)])
        field = logic.distance_field(with_door, stair & with_door, cell)
        reached = [c for c in left if c in field]
        self.assertTrue(reached, u'開了門之後左側仍然走不到')

        rooms = [{'id': 1, 'room_number': u'101', 'cells': left},
                 {'id': 2, 'room_number': u'102', 'cells': right}]
        result = logic.evaluate(rooms, field, logic.LIMIT_50_M)
        by_number = dict((row['room_number'], row) for row in result['rows'])
        self.assertEqual(logic.VERDICT_PASS, by_number[u'101']['verdict'])
        # 繞行必須比直線遠：左下角到門再到樓梯，不是一條斜線。
        self.assertGreater(by_number[u'101']['distance_mm'], 4000.0)


if __name__ == '__main__':
    unittest.main()
