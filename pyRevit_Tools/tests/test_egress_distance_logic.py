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


def stair(stair_id=1, name=u'ST-1', base=0.0, top=3200.0, base_level=1,
          top_level=2, level_name=u'1F'):
    return {'id': stair_id, 'name': name, 'base_elevation_mm': base,
            'top_elevation_mm': top, 'base_level_id': base_level,
            'top_level_id': top_level, 'base_level': level_name}


LEVELS = [0.0, 3200.0, 6400.0, 9600.0]


class StairClassificationTests(unittest.TestCase):
    def test_a_storey_stair_reaching_the_next_slab_connects(self):
        kind, detail = logic.classify_stair(stair(top=3200.0), LEVELS)
        self.assertEqual(logic.STAIR_CONNECTS, kind)
        self.assertIn(u'3200', detail)

    def test_slab_thickness_still_counts_as_reaching(self):
        """樓板厚度與面層常讓頂端差幾十到兩百多 mm，不留容差會把正常的
        樓梯全判成未達。"""
        kind, unused = logic.classify_stair(stair(top=3050.0), LEVELS)
        self.assertEqual(logic.STAIR_CONNECTS, kind)

    def test_a_three_riser_step_is_not_a_stair(self):
        """整個修正的理由：三階的室內高差踏階也有 Stairs 元素，
        把它當量測終點會讓附近房間全部變成合格。"""
        kind, detail = logic.classify_stair(stair(top=450.0), LEVELS)
        self.assertEqual(logic.STAIR_STEP, kind)
        self.assertIn(u'450', detail)

    def test_a_stair_that_climbs_but_stops_short_is_flagged_separately(self):
        """爬了 2 公尺卻沒接到樓板，跟一個 45 公分的踏階不是同一回事——
        前者可能是模型畫錯，值得看；後者本來就不該算。"""
        kind, detail = logic.classify_stair(stair(top=2000.0), LEVELS)
        self.assertEqual(logic.STAIR_SHORT, kind)
        self.assertIn(u'1200', detail)

    def test_the_top_storey_has_no_level_above_to_compare_with(self):
        kind, unused = logic.classify_stair(
            stair(base=9600.0, top=12800.0), LEVELS)
        self.assertEqual(logic.STAIR_TOP, kind)

    def test_a_missing_elevation_is_undecided_not_excluded(self):
        record = stair()
        record['top_elevation_mm'] = None
        kind, unused = logic.classify_stair(record, LEVELS)
        self.assertEqual(logic.STAIR_UNKNOWN, kind)

    def test_a_looser_tolerance_can_turn_short_into_connects(self):
        record = stair(top=2600.0)
        tight, unused = logic.classify_stair(record, LEVELS)
        loose, unused2 = logic.classify_stair(record, LEVELS,
                                              tolerance_mm=800.0)
        self.assertEqual(logic.STAIR_SHORT, tight)
        self.assertEqual(logic.STAIR_CONNECTS, loose)

    def test_only_connecting_stairs_are_suggested(self):
        rows = logic.describe_stairs(
            [stair(1, top=3200.0), stair(2, top=450.0), stair(3, top=2000.0)],
            LEVELS)
        self.assertEqual([1], logic.suggested_stair_ids(rows))

    def test_describe_does_not_mutate_the_caller(self):
        records = [stair()]
        logic.describe_stairs(records, LEVELS)
        self.assertNotIn('kind', records[0])

    def test_the_label_carries_the_verdict_and_its_reason(self):
        rows = logic.describe_stairs([stair(name=u'ST-A')], LEVELS)
        label = logic.stair_label(rows[0])
        self.assertIn(u'ST-A', label)
        self.assertIn(logic.STAIR_CONNECTS, label)
        self.assertIn(u'1F', label)

    def test_the_note_says_the_verdict_is_only_a_suggestion(self):
        self.assertIn(u'建議', logic.STAIR_NOTE)
        self.assertIn(u'勾選', logic.STAIR_NOTE)


class StairsForLevelTests(unittest.TestCase):
    def _rows(self):
        return [stair(1, base_level=1, top_level=2),
                stair(2, base_level=2, top_level=3),
                stair(3, base_level=3, top_level=4)]

    def test_a_stair_based_on_this_level_is_used(self):
        used, other = logic.stairs_for_level(self._rows(), 1, [1, 2, 3])
        self.assertEqual([1], [row['id'] for row in used])

    def test_a_stair_arriving_at_this_level_is_also_used(self):
        """3F→4F 的樓梯在 4F 是往下的那一跑；兩層看到的是同一個梯間。"""
        used, unused = logic.stairs_for_level(self._rows(), 4, [1, 2, 3])
        self.assertEqual([3], [row['id'] for row in used])

    def test_unticked_stairs_are_ignored_entirely(self):
        used, other = logic.stairs_for_level(self._rows(), 1, [])
        self.assertEqual([], used)
        self.assertEqual([], other)

    def test_ticked_stairs_on_other_levels_are_reported_not_silently_dropped(self):
        """勾了卻沒被用到，使用者要知道為什麼，否則會以為工具漏算。"""
        used, other = logic.stairs_for_level(self._rows(), 1, [1, 2, 3])
        self.assertEqual([2, 3], [row['id'] for row in other])


class HabitableRoomTests(unittest.TestCase):
    def test_every_room_the_article_names_is_excluded(self):
        """§1 十九逐字列舉的那十個，一個都不能漏——這是條文不是慣例。"""
        for name in (u'門廳', u'走廊', u'樓梯間', u'衣帽間', u'廁所',
                     u'盥洗室', u'浴室', u'儲藏室', u'機械室', u'車庫'):
            kind, hit = logic.classify_room(name)
            self.assertEqual(logic.ROOM_NON_STATUTORY, kind, name)
            self.assertEqual(name, hit)

    def test_an_ordinary_room_is_habitable(self):
        for name in (u'辦公室', u'客廳', u'教室', u'會議室', u'廚房'):
            kind, unused = logic.classify_room(name)
            self.assertEqual(logic.ROOM_HABITABLE, kind, name)

    def test_the_statutory_list_wins_over_convention(self):
        """一個叫「儲藏室兼機房」的房間，要報的是條文那一條。"""
        kind, hit = logic.classify_room(u'儲藏室兼機房')
        self.assertEqual(logic.ROOM_NON_STATUTORY, kind)
        self.assertEqual(u'儲藏室', hit)

    def test_convention_only_rooms_are_labelled_as_such(self):
        """陽台不在 §1 十九的列舉裡。把它報成「條文明列」會是假的。"""
        kind, hit = logic.classify_room(u'陽台')
        self.assertEqual(logic.ROOM_NON_CONVENTION, kind)
        self.assertEqual(u'陽台', hit)

    def test_the_longest_match_is_reported(self):
        kind, hit = logic.classify_room(u'安全梯樓梯間',
                                        statutory=(u'樓梯', u'樓梯間'))
        self.assertEqual(u'樓梯間', hit)

    def test_a_blank_name_is_treated_as_habitable_not_skipped(self):
        """沒有名字不等於不是居室。當成非居室會靜默漏檢。"""
        kind, unused = logic.classify_room(u'')
        self.assertEqual(logic.ROOM_HABITABLE, kind)

    def test_the_note_quotes_the_article(self):
        self.assertIn(u'§1 十九', logic.HABITABLE_NOTE)
        self.assertIn(u'烹飪', logic.HABITABLE_NOTE)


class RefugeReachTests(unittest.TestCase):
    def _stack(self):
        """1F→2F→3F→4F 一整串，避難層是 1F（level id 1）。"""
        return [stair(1, base_level=1, top_level=2),
                stair(2, base_level=2, top_level=3),
                stair(3, base_level=3, top_level=4)]

    def test_a_stair_starting_at_the_refuge_level_qualifies(self):
        rows = self._stack()
        self.assertTrue(logic.reaches_refuge(rows[0], rows, 1))

    def test_a_stair_higher_up_qualifies_through_the_chain(self):
        rows = self._stack()
        self.assertTrue(logic.reaches_refuge(rows[2], rows, 1))

    def test_a_stair_with_the_chain_broken_does_not_qualify(self):
        """5F→6F 但下方斷掉：接到了上層，卻通不到避難層。
        §1 三十九要的是能通達避難層，不是能往上走。"""
        rows = [stair(9, base_level=5, top_level=6)]
        self.assertFalse(logic.reaches_refuge(rows[0], rows, 1))

    def test_a_cycle_does_not_hang(self):
        """模型畫錯時兩座樓梯可能互相指涉；無限遞迴會讓 Revit 卡死。"""
        rows = [stair(1, base_level=2, top_level=3),
                stair(2, base_level=3, top_level=2)]
        self.assertFalse(logic.reaches_refuge(rows[0], rows, 1))

    def test_the_refuge_test_only_tightens_never_loosens(self):
        """踏階即使追得到避難層也不該變成建議——條文是兩個條件都要滿足。"""
        rows = logic.describe_stairs(
            [stair(1, base=0.0, top=450.0, base_level=1, top_level=2)],
            LEVELS)
        tightened = logic.apply_refuge_test(rows, 1)
        self.assertTrue(tightened[0]['reaches_refuge'])
        self.assertFalse(tightened[0]['suggested'])

    def test_a_connecting_stair_that_cannot_reach_refuge_loses_its_suggestion(self):
        rows = logic.describe_stairs(
            [stair(1, base=6400.0, top=9600.0, base_level=3, top_level=4)],
            LEVELS)
        self.assertTrue(rows[0]['suggested'])
        tightened = logic.apply_refuge_test(rows, 1)
        self.assertFalse(tightened[0]['suggested'])
        self.assertEqual(logic.STAIR_NO_REFUGE_PATH,
                         tightened[0]['refuge_note'])

    def test_apply_refuge_test_does_not_mutate_the_caller(self):
        rows = logic.describe_stairs([stair()], LEVELS)
        logic.apply_refuge_test(rows, 99)
        self.assertNotIn('reaches_refuge', rows[0])

    def test_the_note_quotes_the_article_and_says_why(self):
        self.assertIn(u'§1 三十九', logic.REFUGE_NOTE)
        self.assertIn(u'必要條件', logic.REFUGE_NOTE)


def room(room_id=1, number=u'F103', name=u'操作室', area=20.87, level=u'D-1F',
         level_id=1):
    return {'id': room_id, 'room_number': number, 'room_name': name,
            'area_m2': area, 'level': level, 'level_id': level_id}


class RoomChecklistTests(unittest.TestCase):
    def test_a_working_room_is_suggested(self):
        rows = logic.describe_rooms([room()])
        self.assertTrue(rows[0]['suggested'])
        self.assertEqual(logic.ROOM_HABITABLE, rows[0]['kind'])

    def test_a_statutory_non_habitable_room_is_not_suggested(self):
        rows = logic.describe_rooms([room(name=u'廁所')])
        self.assertFalse(rows[0]['suggested'])

    def test_the_real_project_names_that_keywords_miss_are_still_suggested(self):
        """實測污水處理廠 D-1F：備品室其實是儲藏室、鼓風機室其實是機械室，
        兩者都不會被條文用詞命中。工具因此只能建議，最終由人勾——
        這條測試就是把那個限制釘住，免得日後有人以為關鍵字夠用。"""
        rows = logic.describe_rooms([room(name=u'備品室'),
                                     room(name=u'鼓風機室'),
                                     room(name=u'除臭設備區')])
        for row in rows:
            self.assertTrue(row['suggested'],
                            u'{} 竟然被關鍵字命中了'.format(row['room_name']))

    def test_describe_rooms_does_not_mutate_the_caller(self):
        rooms = [room()]
        logic.describe_rooms(rooms)
        self.assertNotIn('kind', rooms[0])

    def test_the_label_shows_level_number_name_area_and_verdict(self):
        label = logic.room_label(logic.describe_rooms([room()])[0])
        for part in (u'D-1F', u'F103', u'操作室', u'20.9', logic.ROOM_HABITABLE):
            self.assertIn(part, label)

    def test_the_label_names_the_keyword_that_fired(self):
        label = logic.room_label(logic.describe_rooms([room(name=u'廁所')])[0])
        self.assertIn(u'廁所', label)

    def test_only_rooms_on_this_level_are_used(self):
        rows = logic.describe_rooms([room(1, level_id=1), room(2, level_id=2)])
        used = logic.rooms_for_level(rows, 1, [1, 2])
        self.assertEqual([1], [item['id'] for item in used])

    def test_unticked_rooms_are_dropped_even_on_the_right_level(self):
        rows = logic.describe_rooms([room(1, level_id=1)])
        self.assertEqual([], logic.rooms_for_level(rows, 1, []))


class HeadlineTests(unittest.TestCase):
    def _result(self, distance, verdict_room=u'F104'):
        rooms = [{'id': 1, 'room_number': verdict_room, 'room_name': u'公共區域',
                  'cells': set([(0, 0)])}]
        return logic.evaluate(rooms, {(0, 0): distance}, logic.LIMIT_70_M)

    def test_a_pass_states_the_worst_room_and_says_pass(self):
        """實務上第一個問題是「最不利那條多少、在哪、過不過」，
        不是「每一間各是多少」——設計者在圖上也只畫一條最不利路徑。"""
        text = logic.headline(self._result(45000.0))
        self.assertIn(u'F104', text)
        self.assertIn(u'45.0', text)
        self.assertIn(u'合格', text)

    def test_a_failure_leads_with_the_overage(self):
        text = logic.headline(self._result(90000.0))
        self.assertIn(u'超過', text)
        self.assertIn(u'90.0', text)

    def test_an_unreachable_room_is_named_without_a_fake_number(self):
        rooms = [{'id': 1, 'room_number': u'F105', 'room_name': u'鼓風機室',
                  'cells': set([(0, 0), (9, 9)])}]
        result = logic.evaluate(rooms, {(0, 0): 1000.0}, logic.LIMIT_70_M)
        text = logic.headline(result)
        self.assertIn(u'F105', text)
        self.assertIn(logic.VERDICT_UNREACHABLE, text)

    def test_nothing_to_check_says_so(self):
        self.assertIn(u'沒有可檢核',
                      logic.headline(logic.evaluate([], {}, logic.LIMIT_70_M)))


class ThresholdTableTests(unittest.TestCase):
    def test_the_real_project_number_passes_the_c_class_threshold(self):
        """實案：桃園污水處理廠，C 類，9.55+15.1+8.15 = 32.8 m < 70 m。"""
        rows = dict((limit, ok)
                    for limit, unused, ok, unused2
                    in logic.threshold_table(32800.0))
        self.assertTrue(rows[logic.LIMIT_70_M])
        self.assertTrue(rows[logic.LIMIT_50_M])
        self.assertTrue(rows[logic.LIMIT_40_M])
        self.assertFalse(rows[logic.LIMIT_30_M])
        self.assertFalse(rows[logic.LIMIT_20_M])

    def test_the_tightest_passing_threshold_is_reported(self):
        """報「最嚴還能過哪一級」比報「選的那級過了」有用——
        它直接說出這份平面還有多少餘地。"""
        limit, unused = logic.tightest_passing(32800.0)
        self.assertEqual(logic.LIMIT_40_M, limit)

    def test_a_short_distance_passes_everything(self):
        limit, unused = logic.tightest_passing(15000.0)
        self.assertEqual(logic.LIMIT_20_M, limit)

    def test_a_distance_over_every_threshold_reports_none(self):
        self.assertIsNone(logic.tightest_passing(90000.0))

    def test_exactly_on_a_threshold_passes_it(self):
        rows = dict((limit, ok)
                    for limit, unused, ok, unused2
                    in logic.threshold_table(70000.0))
        self.assertTrue(rows[logic.LIMIT_70_M])

    def test_the_margin_is_signed_so_a_failure_shows_the_overage(self):
        table = dict((limit, margin)
                     for limit, unused, unused2, margin
                     in logic.threshold_table(32800.0))
        self.assertAlmostEqual(-2800.0, table[logic.LIMIT_30_M], 6)
        self.assertAlmostEqual(37200.0, table[logic.LIMIT_70_M], 6)

    def test_every_threshold_line_names_the_article_clause(self):
        for line in logic.threshold_lines(32800.0)[1:]:
            self.assertTrue(u'§93' in line or u'類' in line or u'用途' in line,
                            line)

    def test_no_distance_says_so_rather_than_printing_zero(self):
        self.assertIn(u'沒有量到', logic.threshold_lines(None)[0])


class Article94Tests(unittest.TestCase):
    def test_stairs_become_evaluatable_subjects(self):
        """§94 的受檢對象是樓梯而不是房間，但評定與排序程式共用——
        所以樓梯要填進同樣的欄位，而不是另外複製一份幾乎一樣的評定程式。"""
        rows = logic.stair_subjects(
            [{'id': 7, 'element_id': 'X', 'mark': u'ST1', 'name': u'東側樓梯',
              'base_level': u'D-1F'}],
            {7: set([(0, 0), (1, 0)])})
        self.assertEqual(1, len(rows))
        self.assertEqual(u'ST1', rows[0]['room_number'])
        self.assertEqual(u'東側樓梯', rows[0]['room_name'])
        self.assertEqual(2, len(rows[0]['cells']))

    def test_an_unnamed_stair_still_gets_a_label(self):
        rows = logic.stair_subjects([{'id': 1}], {})
        self.assertIn(u'未命名', rows[0]['room_name'])

    def test_a_stair_without_cells_becomes_no_cells_not_a_crash(self):
        rows = logic.stair_subjects([{'id': 1, 'name': u'X'}], {})
        result = logic.evaluate(rows, {}, logic.LIMIT_70_M)
        self.assertEqual(logic.VERDICT_NO_CELLS, result['rows'][0]['verdict'])

    def test_the_note_says_it_measures_something_different(self):
        """§93 從居室量到樓梯口，§94 從樓梯口量到屋外出入口——
        混為一談會量錯對象。"""
        self.assertIn(u'§94', logic.ARTICLE_94_NOTE)
        self.assertIn(u'樓梯口', logic.ARTICLE_94_NOTE)
        self.assertIn(u'屋外出入口', logic.ARTICLE_94_NOTE)
        self.assertIn(u'前條', logic.ARTICLE_94_NOTE)

    def test_the_blockers_explain_what_to_do(self):
        self.assertIn(u'單層建築', logic.EXIT_NO_STAIR)
        self.assertIn(u'功能', logic.EXIT_NO_DOOR)

    def test_article_94_uses_the_same_limits_as_93(self):
        """條文寫「不得超過前條規定」，所以門檻是同一組數字，不另立一套。"""
        limit, unused = logic.limit_for('C')
        self.assertEqual(logic.LIMIT_70_M, limit)
