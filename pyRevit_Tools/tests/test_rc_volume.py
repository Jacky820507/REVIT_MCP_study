# -*- coding: utf-8 -*-
import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import rc_volume_logic as logic


class KeywordFilterTests(unittest.TestCase):
    def test_default_keywords_match_real_type_names(self):
        for name in ('WA1 RC 牆 15cm', '外牆-RC-35cm', '内牆-RC-25cm',
                     'RC牆', '清水混凝土牆', 'CONCRETE WALL 200'):
            self.assertTrue(
                logic.matches_keywords(name, logic.DEFAULT_KEYWORDS), name)

    def test_rc_needs_a_latin_word_boundary(self):
        """A bare substring would pull ARCH/PORCH/SRC into a concrete pour."""
        for name in ('ARCH-隔間牆', 'PORCH 外牆', 'SRC 鋼骨柱牆',
                     'TYPE-A 濕式輕隔間'):
            self.assertFalse(
                logic.matches_keywords(name, logic.DEFAULT_KEYWORDS), name)

    def test_keywords_are_parsed_from_user_text(self):
        self.assertEqual(['RC', '混凝土'], logic.parse_keywords('RC,混凝土'))
        self.assertEqual(['RC', '混凝土'], logic.parse_keywords(' RC 、混凝土 '))
        self.assertEqual([], logic.parse_keywords('   '))

    def test_case_and_fullwidth_are_normalised(self):
        self.assertTrue(logic.matches_keywords('外牆-rc-35cm', ['RC']))
        self.assertTrue(logic.matches_keywords('ＲＣ牆', ['RC']))


class LocationMarkTests(unittest.TestCase):
    # A grid running along Y is a letter grid here; along X, a numbered one.
    GRIDS = [
        {'name': 'G', 'point': (10.0, 0.0), 'direction': (0.0, 50.0)},
        {'name': 'H', 'point': (20.0, 0.0), 'direction': (0.0, 50.0)},
        {'name': '15', 'point': (0.0, 30.0), 'direction': (50.0, 0.0)},
        {'name': '16', 'point': (0.0, 45.0), 'direction': (50.0, 0.0)},
    ]

    def test_nearest_grid_per_direction_with_offsets(self):
        self.assertEqual('G(2.6)/15(1.5)',
                         logic.location_mark((12.6, 31.5), self.GRIDS))

    def test_on_grid_prints_no_offset(self):
        self.assertEqual('H/16', logic.location_mark((20.0, 45.0), self.GRIDS))

    def test_offsets_are_signed(self):
        self.assertEqual('H(-3.5)/16(-4.5)',
                         logic.location_mark((16.5, 40.5), self.GRIDS))

    def test_grid_direction_does_not_flip_the_sign(self):
        """A grid drawn end-to-start must not report the opposite side."""
        flipped = [dict(grid, direction=(-grid['direction'][0],
                                         -grid['direction'][1]))
                   for grid in self.GRIDS]
        self.assertEqual(logic.location_mark((12.6, 31.5), self.GRIDS),
                         logic.location_mark((12.6, 31.5), flipped))

    def test_no_grids_gives_an_empty_mark(self):
        self.assertEqual('', logic.location_mark((1.0, 2.0), []))

    def test_single_direction_still_marks(self):
        grids = [self.GRIDS[0]]
        self.assertEqual('G(1.0)', logic.location_mark((11.0, 5.0), grids))


class OpeningTests(unittest.TestCase):
    def test_identical_openings_collapse_into_a_count(self):
        rows = logic.group_openings([
            {'name': '門開口 - 門開口_220x240', 'width': 2.24, 'height': 2.53},
            {'name': '門開口 - 門開口_220x240', 'width': 2.24, 'height': 2.53},
            {'name': '開口_MO FIX - 牆開口CW8_180x225',
             'width': 1.815, 'height': 3.065},
        ])
        self.assertEqual([2, 1], [row['count'] for row in rows])
        self.assertAlmostEqual(2.24 * 2.53 * 2 + 1.815 * 3.065,
                               logic.opening_area(rows), places=6)

    def test_sizeless_openings_are_dropped_not_counted_as_zero(self):
        rows = logic.group_openings([
            {'name': '未知開口', 'width': None, 'height': 2.1},
            {'name': '零寬開口', 'width': 0, 'height': 2.1},
        ])
        self.assertEqual([], rows)
        self.assertEqual(0, logic.opening_area(rows))


class WallSplitTests(unittest.TestCase):
    """L 形房間會讓 bbox 判斷失效，牆要依 boundary segment 切割分攤。"""

    def test_param_along_wall(self):
        start, end = (0.0, 0.0), (0.0, 9.9)
        self.assertAlmostEqual(0.0, logic.project_param((0.0, 0.0), start, end))
        self.assertAlmostEqual(2.06, logic.project_param((0.0, 2.06), start,
                                                         end), places=6)
        self.assertAlmostEqual(9.9, logic.project_param((0.5, 9.9), start, end),
                               places=6)

    def test_exterior_wall_splits_where_the_rooms_divide_it(self):
        """474261：一支 9.9m 東側外牆同時是 A/B/C 三間房的邊界。"""
        allocations = logic.allocate_wall_to_rooms(9.9, [
            {'room_key': 'F103', 'seg_length': 3.18, 'span': (0.075, 3.255)},
            {'room_key': 'F102', 'seg_length': 2.67, 'span': (3.255, 5.925)},
            {'room_key': 'F101', 'seg_length': 3.90, 'span': (5.925, 9.825)},
        ])
        self.assertEqual(3, len(allocations))
        self.assertAlmostEqual(9.9, sum(a['length'] for a in allocations),
                               places=9)
        by_room = dict((a['room_key'], a['length']) for a in allocations)
        # 3.18 / (3.18+2.67+3.90) * 9.9
        self.assertAlmostEqual(3.2289, by_room['F103'], places=3)

    def test_interior_wall_between_two_rooms_is_halved_not_doubled(self):
        """兩間房各自回報整支牆長，分攤後總和仍等於一支牆。"""
        allocations = logic.allocate_wall_to_rooms(5.0, [
            {'room_key': 'F102', 'seg_length': 5.0, 'span': (0.0, 5.0)},
            {'room_key': 'F103', 'seg_length': 5.0, 'span': (0.0, 5.0)},
        ])
        self.assertAlmostEqual(5.0, sum(a['length'] for a in allocations),
                               places=9)
        for allocation in allocations:
            self.assertAlmostEqual(2.5, allocation['length'], places=9)

    def test_wall_touching_no_room_yields_no_allocation(self):
        self.assertEqual([], logic.allocate_wall_to_rooms(5.0, []))
        self.assertEqual([], logic.allocate_wall_to_rooms(
            5.0, [{'room_key': 'F101', 'seg_length': 0}]))

    def test_opening_follows_its_own_position_not_the_wall(self):
        """百葉窗在 Y 6.04~8.04，落在 C房間那一段，不該記到 B房間。"""
        allocations = logic.allocate_wall_to_rooms(9.9, [
            {'room_key': 'F103', 'seg_length': 3.18, 'span': (0.075, 3.255)},
            {'room_key': 'F102', 'seg_length': 2.67, 'span': (3.255, 5.925)},
            {'room_key': 'F101', 'seg_length': 3.90, 'span': (5.925, 9.825)},
        ])
        louvre = logic.assign_opening_to_allocation(2.055, allocations)
        self.assertEqual('F103', louvre['room_key'])
        upper = logic.assign_opening_to_allocation(7.0, allocations)
        self.assertEqual('F101', upper['room_key'])

    def test_opening_outside_every_span_falls_back_to_largest_share(self):
        allocations = logic.allocate_wall_to_rooms(9.9, [
            {'room_key': 'F103', 'seg_length': 3.18, 'span': (0.075, 3.255)},
            {'room_key': 'F101', 'seg_length': 3.90, 'span': (5.925, 9.825)},
        ])
        stray = logic.assign_opening_to_allocation(4.5, allocations)
        self.assertEqual('F101', stray['room_key'])
        self.assertIsNone(logic.assign_opening_to_allocation(1.0, []))

    def test_allocation_summary_is_readable(self):
        allocations = logic.allocate_wall_to_rooms(10.0, [
            {'room_key': 'a', 'seg_length': 7.5, 'span': (0, 7.5)},
            {'room_key': 'b', 'seg_length': 2.5, 'span': (7.5, 10.0)},
        ])
        text = logic.format_room_allocation(
            allocations, {'a': 'F103', 'b': 'F102'})
        self.assertEqual('F103:7.50m(75%) / F102:2.50m(25%)', text)


class VolumeTests(unittest.TestCase):
    def test_volume_matches_the_reference_expression(self):
        """(10.05*4.2-(2.51*2.9+2.18*2.2+3.13*0.6*2))*0.15 from 牆面清單."""
        deduct = 2.51 * 2.9 + 2.18 * 2.2 + 3.13 * 0.6 * 2
        self.assertAlmostEqual(
            3.96, logic.wall_volume(10.05, 4.2, 0.15, deduct), places=2)

    def test_plain_wall_volume(self):
        self.assertAlmostEqual(8.316, logic.wall_volume(9.9, 2.4, 0.35),
                               places=3)

    def test_over_deduction_never_produces_a_negative_pour(self):
        self.assertEqual(0.0, logic.wall_volume(2.0, 2.0, 0.2, 99.0))

    def test_unjoined_beam_overlap_comes_off_the_gross(self):
        """未接合時牆與樑是重疊實體，同一塊混凝土會被算兩次。"""
        gross = logic.wall_volume(6.0, 3.0, 0.25)
        self.assertAlmostEqual(4.5, gross, places=6)
        self.assertAlmostEqual(4.148, logic.net_volume(gross, 0.352),
                               places=6)

    def test_net_volume_never_goes_negative(self):
        self.assertEqual(0.0, logic.net_volume(1.0, 5.0))
        self.assertEqual(4.5, logic.net_volume(4.5, None))

    def test_deduction_detail_names_every_element(self):
        text = logic.format_deduction_detail([
            {'label': '梁', 'id': 55501, 'volume': 0.3521},
            {'label': '樓板', 'id': 66601, 'volume': 0.06},
        ])
        self.assertEqual('梁 55501:0.352 / 樓板 66601:0.060', text)
        self.assertEqual('', logic.format_deduction_detail([]))

    def test_deduction_detail_truncates_but_says_how_many(self):
        items = [{'label': '梁', 'id': i, 'volume': 0.1} for i in range(12)]
        text = logic.format_deduction_detail(items, limit=3)
        self.assertEqual(4, len(text.split(' / ')))
        self.assertIn('另 9 項', text)

    def test_join_state_is_readable(self):
        self.assertEqual('無相鄰樑柱板', logic.format_join_state(0, 0))
        self.assertEqual('已接合 3', logic.format_join_state(3, 0))
        self.assertEqual('已接合 3／未接合扣除 2',
                         logic.format_join_state(3, 2))

    def test_group_key_separates_thickness_and_height(self):
        same = logic.wall_group_key('RC 15cm', 2.4, 0.15)
        self.assertEqual(same, logic.wall_group_key('RC 15cm', 2.4, 0.15))
        self.assertNotEqual(same, logic.wall_group_key('RC 15cm', 2.4, 0.20))
        self.assertNotEqual(same, logic.wall_group_key('RC 15cm', 4.2, 0.15))


class FormattingAndSortTests(unittest.TestCase):
    def test_format_number_digits(self):
        self.assertEqual('2.55', logic.format_number(2.5499999999999998))
        self.assertEqual('0.150', logic.format_number(0.15, 3))
        self.assertEqual('', logic.format_number(None))

    def test_excel_columns(self):
        self.assertEqual('A', logic.excel_col(1))
        self.assertEqual('Q', logic.excel_col(17))
        self.assertEqual('Y', logic.excel_col(25))
        self.assertEqual('AA', logic.excel_col(27))

    def test_floor_sort_follows_the_takeoff_sop(self):
        numbers = ['F601', 'B105', 'R202', 'BS01', 'B201']
        ordered = sorted(numbers, key=logic.floor_sort_key)
        self.assertEqual(['BS01', 'B105', 'B201', 'F601', 'R202'], ordered)

    def test_type_sort_groups_by_thickness_in_the_name(self):
        names = ['WA1 RC 牆 20cm', 'WA1 RC 牆 15cm', '外牆-RC-35cm']
        ordered = sorted(names, key=logic.type_sort_key)
        self.assertEqual(['WA1 RC 牆 15cm', 'WA1 RC 牆 20cm', '外牆-RC-35cm'],
                         ordered)


if __name__ == '__main__':
    unittest.main()
