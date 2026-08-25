# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import link_level_logic as logic


def level(level_id=1, name=u'1FL', elevation_mm=0.0):
    return {'id': level_id, 'name': name, 'elevation_mm': elevation_mm}


class MatchTests(unittest.TestCase):
    def _levels(self):
        return [level(1, u'1FL', 0.0),
                level(2, u'2FL', 3200.0),
                level(3, u'3FL', 6400.0)]

    def test_an_exact_elevation_matches_exactly(self):
        found, quality, delta = logic.match_level(3200.0, self._levels())
        self.assertEqual(2, found['id'])
        self.assertEqual(logic.MATCH_EXACT, quality)
        self.assertAlmostEqual(0.0, delta, 6)

    def test_a_small_offset_is_near(self):
        """Slab thickness routinely shifts a link level a few tens of mm."""
        found, quality, delta = logic.match_level(3230.0, self._levels())
        self.assertEqual(2, found['id'])
        self.assertEqual(logic.MATCH_NEAR, quality)
        self.assertAlmostEqual(30.0, delta, 6)

    def test_exactly_on_the_tolerance_is_still_near(self):
        unused, quality, unused2 = logic.match_level(3250.0, self._levels())
        self.assertEqual(logic.MATCH_NEAR, quality)

    def test_beyond_the_tolerance_is_flagged_far(self):
        found, quality, delta = logic.match_level(4800.0, self._levels())
        self.assertEqual(logic.MATCH_FAR, quality)
        self.assertAlmostEqual(1600.0, delta, 6)

    def test_a_far_match_still_returns_the_nearest_level(self):
        """A bad match the user can see and reject beats no answer."""
        found, unused, unused2 = logic.match_level(4800.0, self._levels())
        self.assertIsNotNone(found)
        self.assertEqual(2, found['id'])

    def test_no_levels_matches_nothing(self):
        found, quality, delta = logic.match_level(0.0, [])
        self.assertIsNone(found)
        self.assertEqual(logic.MATCH_NONE, quality)
        self.assertIsNone(delta)

    def test_a_missing_host_elevation_matches_nothing(self):
        found, quality, unused = logic.match_level(None, self._levels())
        self.assertIsNone(found)
        self.assertEqual(logic.MATCH_NONE, quality)

    def test_levels_without_an_elevation_are_ignored(self):
        levels = [{'id': 9, 'name': u'壞掉'}, level(2, u'2FL', 3200.0)]
        found, unused, unused2 = logic.match_level(3200.0, levels)
        self.assertEqual(2, found['id'])

    def test_negative_elevations_match(self):
        levels = [level(1, u'B1', -3600.0), level(2, u'1FL', 0.0)]
        found, quality, unused = logic.match_level(-3600.0, levels)
        self.assertEqual(1, found['id'])
        self.assertEqual(logic.MATCH_EXACT, quality)

    def test_a_custom_tolerance_changes_the_verdict(self):
        unused, loose, unused2 = logic.match_level(3400.0, self._levels(),
                                                   tolerance_mm=500.0)
        unused3, tight, unused4 = logic.match_level(3400.0, self._levels(),
                                                    tolerance_mm=10.0)
        self.assertEqual(logic.MATCH_NEAR, loose)
        self.assertEqual(logic.MATCH_FAR, tight)

    def test_the_nearest_wins_when_two_are_close(self):
        levels = [level(1, u'A', 3000.0), level(2, u'B', 3400.0)]
        found, unused, unused2 = logic.match_level(3350.0, levels)
        self.assertEqual(2, found['id'])


class SortTests(unittest.TestCase):
    def test_levels_sort_by_elevation_not_name(self):
        """1F/2F/10F as text puts 10F in the middle."""
        levels = [level(1, u'10FL', 32000.0), level(2, u'1FL', 0.0),
                  level(3, u'2FL', 3200.0)]
        ordered = logic.sorted_levels(levels)
        self.assertEqual([u'1FL', u'2FL', u'10FL'],
                         [item['name'] for item in ordered])

    def test_basements_sort_below_ground(self):
        levels = [level(1, u'1FL', 0.0), level(2, u'B1', -3600.0)]
        self.assertEqual(u'B1', logic.sorted_levels(levels)[0]['name'])

    def test_sorting_nothing_is_fine(self):
        self.assertEqual([], logic.sorted_levels([]))
        self.assertEqual([], logic.sorted_levels(None))


class LabelTests(unittest.TestCase):
    def test_the_label_shows_name_and_elevation(self):
        text = logic.level_label(level(1, u'2FL', 3200.0))
        self.assertIn(u'2FL', text)
        self.assertIn(u'3200', text)

    def test_the_label_shows_the_match_quality_and_delta(self):
        text = logic.level_label(level(1, u'2FL', 3200.0),
                                 logic.MATCH_NEAR, 30.0)
        self.assertIn(logic.MATCH_NEAR, text)
        self.assertIn(u'30', text)

    def test_a_missing_level_gets_a_placeholder(self):
        self.assertEqual(u'(無樓層)', logic.level_label(None))


class WarningTests(unittest.TestCase):
    def test_an_exact_match_needs_no_warning(self):
        self.assertEqual(u'', logic.match_warning(logic.MATCH_EXACT))

    def test_a_near_match_needs_no_warning(self):
        self.assertEqual(u'', logic.match_warning(logic.MATCH_NEAR))

    def test_a_far_match_says_why_it_matters(self):
        """Drawing a floor's walls onto the wrong storey is invisible in plan."""
        text = logic.match_warning(logic.MATCH_FAR, 1600.0)
        self.assertIn(u'1600', text)
        self.assertIn(u'看不出來', text)

    def test_no_levels_says_so(self):
        self.assertIn(u'讀不到', logic.match_warning(logic.MATCH_NONE))


if __name__ == '__main__':
    unittest.main()
