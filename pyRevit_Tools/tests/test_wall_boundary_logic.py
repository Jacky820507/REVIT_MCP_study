# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import wall_boundary_logic as logic


# A 300 wall built exterior -> interior: 20 finish, 250 core, 30 finish.
# Deliberately asymmetric so a "core is centred" assumption cannot pass.
ASYMMETRIC = {
    'width': 300.0,
    'layer_widths': [20.0, 250.0, 30.0],
    'first_core': 1,
    'last_core': 1,
}


def offsets_of(spec):
    """layer_offsets() from a record-shaped dict, which names the key 'width'."""
    return logic.layer_offsets(spec['width'], spec['layer_widths'],
                               spec['first_core'], spec['last_core'])


def wall(wall_id=1, location=logic.LOCATION_CENTRE, **overrides):
    record = {
        'id': wall_id,
        'name': u'RC-300',
        'has_curve': True,
        'is_curtain': False,
        'is_stacked': False,
        'location_line': location,
    }
    record.update(ASYMMETRIC)
    record.update(overrides)
    return record


class LayerOffsetTests(unittest.TestCase):
    def test_faces_are_half_the_width_each_side(self):
        offsets = logic.layer_offsets(300.0)
        self.assertAlmostEqual(150.0, offsets['exterior'], 6)
        self.assertAlmostEqual(-150.0, offsets['interior'], 6)
        self.assertAlmostEqual(0.0, offsets['centre'], 6)

    def test_core_faces_walk_inward_from_each_side(self):
        offsets = offsets_of(ASYMMETRIC)
        self.assertAlmostEqual(130.0, offsets['core_exterior'], 6)
        self.assertAlmostEqual(-120.0, offsets['core_interior'], 6)

    def test_core_centre_is_not_the_wall_centre_when_asymmetric(self):
        """The whole reason the core is measured rather than assumed."""
        offsets = offsets_of(ASYMMETRIC)
        self.assertAlmostEqual(5.0, offsets['core_centre'], 6)
        self.assertNotAlmostEqual(offsets['centre'], offsets['core_centre'], 3)

    def test_symmetric_build_up_puts_the_core_on_the_centre(self):
        offsets = logic.layer_offsets(300.0, [25.0, 250.0, 25.0], 1, 1)
        self.assertAlmostEqual(0.0, offsets['core_centre'], 6)

    def test_core_spanning_several_layers(self):
        offsets = logic.layer_offsets(
            300.0, [20.0, 100.0, 150.0, 30.0], 1, 2)
        self.assertAlmostEqual(130.0, offsets['core_exterior'], 6)
        self.assertAlmostEqual(-120.0, offsets['core_interior'], 6)

    def test_no_layers_means_no_core(self):
        offsets = logic.layer_offsets(300.0)
        self.assertIsNone(offsets['core_exterior'])
        self.assertIsNone(offsets['core_centre'])

    def test_negative_width_is_treated_as_thickness(self):
        offsets = logic.layer_offsets(-300.0)
        self.assertAlmostEqual(150.0, offsets['exterior'], 6)


class LocationLineTests(unittest.TestCase):
    def _offsets(self):
        return offsets_of(ASYMMETRIC)

    def test_every_setting_maps_to_its_position(self):
        offsets = self._offsets()
        expected = {
            logic.LOCATION_CENTRE: 0.0,
            logic.LOCATION_FACE_EXTERIOR: 150.0,
            logic.LOCATION_FACE_INTERIOR: -150.0,
            logic.LOCATION_CORE_EXTERIOR: 130.0,
            logic.LOCATION_CORE_INTERIOR: -120.0,
            logic.LOCATION_CORE_CENTRE: 5.0,
        }
        for kind, value in expected.items():
            self.assertAlmostEqual(
                value, logic.location_line_position(kind, offsets), 6,
                u'{} 位置錯誤'.format(kind))

    def test_core_setting_without_a_core_reports_none(self):
        offsets = logic.layer_offsets(300.0)
        self.assertIsNone(logic.location_line_position(
            logic.LOCATION_CORE_EXTERIOR, offsets))

    def test_unknown_setting_falls_back_to_the_centreline(self):
        offsets = self._offsets()
        self.assertAlmostEqual(
            0.0, logic.location_line_position(u'SomethingNew', offsets), 6)


class PlanOffsetTests(unittest.TestCase):
    def _distance(self, mode, location, label):
        pairs = dict(logic.plan_offsets(wall(location=location), mode))
        return pairs[label]

    def test_centre_from_a_centreline_wall_needs_no_offset(self):
        self.assertAlmostEqual(
            0.0, self._distance(logic.MODE_CENTRE, logic.LOCATION_CENTRE,
                                u'牆心'), 6)

    def test_centre_from_an_exterior_face_wall_moves_inward(self):
        """The case that silently breaks if the location line is ignored."""
        self.assertAlmostEqual(
            -150.0, self._distance(logic.MODE_CENTRE,
                                   logic.LOCATION_FACE_EXTERIOR, u'牆心'), 6)

    def test_centre_from_an_interior_face_wall_moves_outward(self):
        self.assertAlmostEqual(
            150.0, self._distance(logic.MODE_CENTRE,
                                  logic.LOCATION_FACE_INTERIOR, u'牆心'), 6)

    def test_faces_from_a_centreline_wall(self):
        pairs = dict(logic.plan_offsets(wall(), logic.MODE_FACE))
        self.assertAlmostEqual(150.0, pairs[u'外牆面'], 6)
        self.assertAlmostEqual(-150.0, pairs[u'內牆面'], 6)

    def test_faces_from_an_exterior_face_wall(self):
        pairs = dict(logic.plan_offsets(
            wall(location=logic.LOCATION_FACE_EXTERIOR), logic.MODE_FACE))
        self.assertAlmostEqual(0.0, pairs[u'外牆面'], 6)
        self.assertAlmostEqual(-300.0, pairs[u'內牆面'], 6)

    def test_core_faces_from_a_centreline_wall(self):
        pairs = dict(logic.plan_offsets(wall(), logic.MODE_CORE))
        self.assertAlmostEqual(130.0, pairs[u'核心外緣'], 6)
        self.assertAlmostEqual(-120.0, pairs[u'核心內緣'], 6)

    def test_core_faces_from_a_core_exterior_wall(self):
        pairs = dict(logic.plan_offsets(
            wall(location=logic.LOCATION_CORE_EXTERIOR), logic.MODE_CORE))
        self.assertAlmostEqual(0.0, pairs[u'核心外緣'], 6)
        self.assertAlmostEqual(-250.0, pairs[u'核心內緣'], 6)

    def test_the_two_face_lines_are_always_one_thickness_apart(self):
        for location in (logic.LOCATION_CENTRE, logic.LOCATION_FACE_EXTERIOR,
                         logic.LOCATION_FACE_INTERIOR,
                         logic.LOCATION_CORE_CENTRE):
            pairs = dict(logic.plan_offsets(wall(location=location),
                                            logic.MODE_FACE))
            self.assertAlmostEqual(300.0, pairs[u'外牆面'] - pairs[u'內牆面'],
                                   6, u'{} 的牆面間距不等於牆厚'.format(location))

    def test_unknown_mode_rejected(self):
        self.assertRaises(ValueError, logic.plan_offsets, wall(), 'sideways')


class BlockingTests(unittest.TestCase):
    def test_a_normal_wall_is_not_blocked(self):
        for mode in (logic.MODE_CENTRE, logic.MODE_FACE, logic.MODE_CORE):
            self.assertEqual(u'', logic.block_reason(wall(), mode))

    def test_curtain_wall_is_blocked(self):
        self.assertEqual(logic.BLOCK_CURTAIN,
                         logic.block_reason(wall(is_curtain=True),
                                            logic.MODE_CENTRE))

    def test_stacked_wall_is_blocked(self):
        self.assertEqual(logic.BLOCK_STACKED,
                         logic.block_reason(wall(is_stacked=True),
                                            logic.MODE_CENTRE))

    def test_missing_curve_is_blocked(self):
        self.assertEqual(logic.BLOCK_NO_CURVE,
                         logic.block_reason(wall(has_curve=False),
                                            logic.MODE_CENTRE))

    def test_zero_thickness_is_blocked(self):
        self.assertEqual(logic.BLOCK_NO_WIDTH,
                         logic.block_reason(wall(width=0.0),
                                            logic.MODE_CENTRE))

    def test_core_mode_needs_a_core(self):
        plain = wall(layer_widths=[], first_core=None, last_core=None)
        self.assertEqual(logic.BLOCK_NO_CORE,
                         logic.block_reason(plain, logic.MODE_CORE))
        # The same wall is perfectly usable for centreline and face lines.
        self.assertEqual(u'', logic.block_reason(plain, logic.MODE_CENTRE))
        self.assertEqual(u'', logic.block_reason(plain, logic.MODE_FACE))


class BuildPlanTests(unittest.TestCase):
    def test_centre_mode_makes_one_line_per_wall(self):
        plan = logic.build_plan([wall(1), wall(2)], logic.MODE_CENTRE)
        self.assertEqual(2, len(plan['seeds']))
        self.assertEqual(2, plan['line_count'])

    def test_face_mode_makes_two_lines_per_wall(self):
        plan = logic.build_plan([wall(1), wall(2)], logic.MODE_FACE)
        self.assertEqual(4, plan['line_count'])

    def test_blocked_walls_are_separated(self):
        plan = logic.build_plan(
            [wall(1), wall(2, is_curtain=True)], logic.MODE_CENTRE)
        self.assertEqual(1, len(plan['seeds']))
        self.assertEqual(logic.BLOCK_CURTAIN, plan['blocked'][0]['reason'])

    def test_core_mode_skips_walls_without_a_core(self):
        plan = logic.build_plan(
            [wall(1), wall(2, layer_widths=[], first_core=None,
                           last_core=None)], logic.MODE_CORE)
        self.assertEqual(1, len(plan['seeds']))
        self.assertEqual(logic.BLOCK_NO_CORE, plan['blocked'][0]['reason'])

    def test_empty_input(self):
        plan = logic.build_plan([], logic.MODE_CENTRE)
        self.assertEqual(0, plan['line_count'])

    def test_unknown_mode_rejected(self):
        self.assertRaises(ValueError, logic.build_plan, [], 'sideways')

    def test_summary_reports_counts_and_reasons(self):
        plan = logic.build_plan(
            [wall(1), wall(2, is_curtain=True)], logic.MODE_FACE)
        text = logic.plan_lines(plan)
        self.assertIn(u'掃描牆 2 道', text)
        self.assertIn(u'2 條線', text)
        self.assertIn(logic.BLOCK_CURTAIN, text)


if __name__ == '__main__':
    unittest.main()
