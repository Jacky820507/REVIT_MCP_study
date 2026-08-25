# -*- coding: utf-8 -*-
import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import scaffold_height_logic as logic


def hit(elevation, element_id, location=False, category='Floor'):
    return {
        'elevation_m': elevation,
        'element_id': element_id,
        'element_name': '{} {}'.format(category, element_id),
        'category': category,
        'is_location_sample': location,
    }


class ScaffoldHeightLogicTests(unittest.TestCase):
    def test_normal_floor_stays_at_room_level(self):
        selected = logic.select_bottom_surface(
            [hit(0.0, 10, True), hit(0.01, 10), hit(0.0, 10)],
            reference_base_m=0.0,
            room_lower_offset_m=0.0)
        self.assertEqual('physical-floor-top-ray', selected['source'])
        self.assertAlmostEqual(0.0, selected['offset_m'], places=2)
        self.assertFalse(selected['ambiguous'])

    def test_unpulled_room_detects_lowered_floor(self):
        selected = logic.select_bottom_surface(
            [hit(-0.12, 20, True), hit(-0.11, 20), hit(-0.12, 20)],
            reference_base_m=0.0,
            room_lower_offset_m=0.0)
        self.assertEqual(
            'physical-lowered-floor-top-ray', selected['source'])
        self.assertAlmostEqual(-0.12, selected['offset_m'], places=2)

    def test_pit_floor_can_come_from_foundation(self):
        selected = logic.select_bottom_surface(
            [hit(-1.50, 30, True, 'StructuralFoundation'),
             hit(-1.49, 30, False, 'StructuralFoundation')],
            reference_base_m=0.0,
            room_lower_offset_m=-1.50)
        self.assertEqual(
            'physical-lowered-floor-top-ray', selected['source'])
        self.assertEqual([30], selected['element_ids'])
        self.assertEqual(['StructuralFoundation'], selected['categories'])

    def test_dominant_surface_wins_but_mixed_levels_are_flagged(self):
        selected = logic.select_bottom_surface(
            [hit(-0.10, 40, True), hit(-0.10, 40), hit(-0.10, 40),
             hit(-0.45, 41), hit(-0.45, 41)],
            reference_base_m=0.0,
            room_lower_offset_m=0.0)
        self.assertAlmostEqual(-0.10, selected['elevation_m'], places=2)
        self.assertTrue(selected['ambiguous'])
        self.assertEqual(2, selected['bucket_count'])
        self.assertEqual(2, selected['runner_up_count'])
        self.assertAlmostEqual(0.6, selected['dominant_ratio'], places=2)

    def test_nominal_height_is_rebased_to_lowered_floor(self):
        shifted = logic.shift_height_info(
            {'height': 2.40, 'raw_height': 2.40},
            0.12,
            lambda value: round(value, 2))
        self.assertEqual(2.52, shifted['height'])
        self.assertEqual(2.52, shifted['raw_height'])

    def test_no_hits_returns_none(self):
        self.assertIsNone(logic.select_bottom_surface([], 0.0, 0.0))

    def test_ceiling_has_priority_over_floor(self):
        source, values = logic.choose_top_surface([2.70], [3.00])
        self.assertEqual('ceiling', source)
        self.assertEqual([2.70], values)

    def test_higher_floor_is_used_for_open_to_above_room(self):
        source, values = logic.choose_top_surface([], [6.00])
        self.assertEqual('floor', source)
        self.assertEqual([6.00], values)

    def test_level_fallback_is_last(self):
        source, values = logic.choose_top_surface([], [])
        self.assertEqual('level', source)
        self.assertEqual([], values)

    def test_full_wall_uses_room_clear_height(self):
        height, source = logic.effective_wall_height(3.05, 2.80)
        self.assertAlmostEqual(2.80, height, places=2)
        self.assertEqual('room-clear-height', source)

    def test_low_wall_keeps_model_height(self):
        height, source = logic.effective_wall_height(2.10, 2.80)
        self.assertAlmostEqual(2.10, height, places=2)
        self.assertEqual('model-partial-wall-height', source)

    def test_near_tie_mixed_levels_are_not_reliable(self):
        selected = logic.select_bottom_surface(
            [hit(-0.10, 50, True), hit(-0.10, 50), hit(-0.10, 50),
             hit(-0.10, 50), hit(-0.10, 50),
             hit(-0.45, 51), hit(-0.45, 51), hit(-0.45, 51),
             hit(-0.45, 51)],
            reference_base_m=0.0,
            room_lower_offset_m=0.0)
        reliable, reason = logic.bottom_surface_is_reliable(selected, 9)
        self.assertFalse(reliable)
        self.assertEqual('insufficient-dominance', reason)

    def test_two_thirds_dominant_level_is_reliable(self):
        selected = logic.select_bottom_surface(
            [hit(-0.10, 60, True), hit(-0.10, 60), hit(-0.10, 60),
             hit(-0.10, 60), hit(-0.10, 60), hit(-0.10, 60),
             hit(-0.45, 61), hit(-0.45, 61), hit(-0.45, 61)],
            reference_base_m=0.0,
            room_lower_offset_m=0.0)
        reliable, reason = logic.bottom_surface_is_reliable(selected, 9)
        self.assertTrue(reliable)
        self.assertEqual('', reason)


if __name__ == '__main__':
    unittest.main()
