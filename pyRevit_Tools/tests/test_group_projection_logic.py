# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import colorsys
import copy
import os
import random
import sys
import unittest

LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import group_projection_logic as logic


class RelationTests(unittest.TestCase):
    def test_mm_tolerance_in_feet(self):
        for target in (0.0, 10.0, -10.0):
            for mm, expected in ((-1.001, 'below'), (-1, 'same'),
                                 (-0.5, 'same'), (0, 'same'),
                                 (0.5, 'same'), (1, 'same'),
                                 (1.001, 'above')):
                self.assertEqual(expected, logic.relation(
                    target + mm / 304.8, target))

    def test_custom_and_zero_tolerance(self):
        self.assertEqual('same', logic.relation(12, 10, 2))
        self.assertEqual('below', logic.relation(7.9, 10, 2))
        self.assertEqual('above', logic.relation(10.00001, 10, 0))
        self.assertEqual('same', logic.relation(10, 10, 0))

    def test_missing_and_nonfinite(self):
        for value in (None, '', 'bad', float('nan'), float('inf'),
                      -float('inf')):
            self.assertEqual('unknown', logic.relation(value, 0))
            self.assertEqual('unknown', logic.relation(0, value))
        for tolerance in (None, -1, float('nan'), float('inf')):
            self.assertEqual('unknown', logic.relation(0, 0, tolerance))


class ColorTests(unittest.TestCase):
    def test_missing_elevation_and_target(self):
        records = [{'id': 1}, {'id': 2, 'elevation': None}]
        result = logic.assign_colors(records, 0)
        self.assertTrue(all(v['relation'] == 'unknown' for v in result.values()))
        self.assertEqual('unknown', logic.assign_colors(
            [{'id': 3, 'elevation': 10}], None)[3]['relation'])
        self.assertEqual({}, logic.assign_colors([], 0))

    def test_reordering_is_deterministic_and_inputs_unchanged(self):
        records = [{'id': i, 'elevation': (10, -10, 0, None)[i % 4]}
                   for i in range(160)]
        original = copy.deepcopy(records)
        expected = logic.assign_colors(records, 0)
        self.assertEqual(original, records)
        random.Random(17).shuffle(records)
        self.assertEqual(expected, logic.assign_colors(records, 0))
        self.assertEqual(expected, logic.assign_colors(reversed(records), 0))

    def test_numeric_ids_sort_within_relation(self):
        result = logic.assign_colors([
            {'id': 10, 'elevation': 2}, {'id': 2, 'elevation': 2}], 0)
        first = logic.assign_colors([{'id': 2, 'elevation': 2}], 0)
        self.assertEqual(first[2], result[2])
        self.assertNotEqual(result[2]['rgb'], result[10]['rgb'])

    def test_40_per_direction_are_distinct_and_keep_direction(self):
        records = []
        for direction, elevation in enumerate((10, -10, 0, None)):
            records.extend({'id': direction * 40 + i, 'elevation': elevation}
                           for i in range(40))
        result = logic.assign_colors(records, 0)
        self.assertEqual(160, len(set(v['rgb'] for v in result.values())))
        labels = {'above': '↑ 上方', 'below': '↓ 下方',
                  'same': '↔ 同高', 'unknown': '↕ 未知'}
        for group_id, entry in result.items():
            direction = ('above', 'below', 'same', 'unknown')[group_id // 40]
            self.assertEqual(direction, entry['relation'])
            self.assertEqual(labels[direction], entry['label'])
            rgb = entry['rgb']
            self.assertIsInstance(rgb, tuple)
            self.assertTrue(all(isinstance(c, int) and 0 <= c <= 255 for c in rgb))
            self.assertEqual(rgb, tuple(int(entry['hex'][i:i + 2], 16)
                                        for i in (1, 3, 5)))
            hue, saturation, _ = colorsys.rgb_to_hsv(
                *[c / 255.0 for c in rgb])
            if direction == 'above':
                self.assertTrue(hue <= 0.13 or hue >= 0.95)
                self.assertGreater(saturation, 0.5)
                self.assertGreater(rgb[0], rgb[2])
            elif direction == 'below':
                self.assertTrue(0.49 <= hue <= 0.71)
                self.assertGreater(saturation, 0.5)
                self.assertGreater(rgb[2], rgb[0])
            else:
                self.assertLess(saturation, 0.12)

    def test_duplicate_ids_are_rejected(self):
        with self.assertRaises(ValueError):
            logic.assign_colors([{'id': 1, 'elevation': 5},
                                 {'id': 1, 'elevation': -5}], 0)


class CoincidentTests(unittest.TestCase):
    def test_reverse_overlap_keeps_extents_and_both_colors(self):
        red, blue = (255, 0, 0), (0, 0, 255)
        result = logic.interleave_coincident([
            ((0, 0, 1), (10, 0, 1), red),
            ((10, 0, 1), (0, 0, 1), blue)])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0][0], (0, 0, 1))
        self.assertEqual(result[0][1], result[1][0])
        self.assertEqual(result[1][1], (10, 0, 1))
        self.assertEqual(set(item[2] for item in result), {red, blue})

    def test_three_colors_duplicates_and_unique_line(self):
        colors = [(1, 0, 0), (0, 1, 0), (0, 0, 1)]
        inputs = [((0, 0, 0), (9, 0, 0), c) for c in colors]
        inputs.append(inputs[0])
        result = logic.interleave_coincident(inputs)
        self.assertEqual(len(result), 3)
        self.assertEqual([r[1][0] - r[0][0] for r in result], [3, 3, 3])
        self.assertEqual(result, logic.interleave_coincident(list(reversed(inputs))))
        unique = [((1.123456789, 0, 0), (4, 1, 2), colors[0])]
        self.assertEqual(logic.interleave_coincident(unique), unique)


class LevelOptionTests(unittest.TestCase):
    def test_levels_sorted_by_elevation_with_counts(self):
        records = [dict(level='3F', elevation=30.0), dict(level='1F', elevation=0.0),
                   dict(level='3F', elevation=30.0), dict(level='未指定樓層', elevation=None),
                   dict(level='B1F', elevation=-12.0)]
        options = logic.level_options(records)
        self.assertEqual(options[0], (logic.ALL_LEVELS, '全部樓層 (5)'))
        self.assertEqual([key for key, label in options[1:]], ['B1F', '1F', '3F', '未指定樓層'])
        self.assertEqual(dict(options)['3F'], '3F (2)')

    def test_empty_records_only_all(self):
        self.assertEqual(logic.level_options([]), [(logic.ALL_LEVELS, '全部樓層 (0)')])

if __name__ == '__main__':
    unittest.main()
