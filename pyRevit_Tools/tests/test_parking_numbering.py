# -*- coding: utf-8 -*-
import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

from parking_numbering import rotate_to_start, sort_bays


def bay(element_id, x, y):
    return {'id': element_id, 'x': x, 'y': y}


class ParkingNumberingTests(unittest.TestCase):
    def setUp(self):
        self.grid = [
            bay(1, 0, 10), bay(2, 10, 10),
            bay(3, 0, 0), bay(4, 10, 0),
        ]

    def test_rows_top_to_bottom_left_to_right(self):
        result = sort_bays(
            list(self.grid), 'y', True, False, False, 1.0)
        self.assertEqual([1, 2, 3, 4], [item['id'] for item in result])

    def test_rows_bottom_to_top_right_to_left(self):
        result = sort_bays(
            list(self.grid), 'y', False, True, False, 1.0)
        self.assertEqual([4, 3, 2, 1], [item['id'] for item in result])

    def test_columns_serpentine(self):
        result = sort_bays(
            list(self.grid), 'x', False, True, True, 1.0)
        self.assertEqual([1, 3, 4, 2], [item['id'] for item in result])

    def test_rotate_to_requested_start(self):
        result = rotate_to_start(self.grid, 3)
        self.assertEqual([3, 4, 1, 2], [item['id'] for item in result])

    def test_missing_start_raises(self):
        with self.assertRaises(ValueError):
            rotate_to_start(self.grid, 99)

    def test_tolerance_groups_small_coordinate_drift(self):
        items = [bay(2, 10, 9.7), bay(1, 0, 10.0), bay(3, 0, 0)]
        result = sort_bays(items, 'y', True, False, False, 0.5)
        self.assertEqual([1, 2, 3], [item['id'] for item in result])
        self.assertEqual([1, 1, 2], [item['_group'] for item in result])

    def test_group_span_cannot_chain_past_tolerance(self):
        items = [bay(1, 0, 0), bay(2, 10, 1000), bay(3, 20, 2000)]
        result = sort_bays(items, 'y', False, False, False, 1500.0)
        self.assertEqual([1, 2, 3], [item['id'] for item in result])
        self.assertEqual([1, 1, 2], [item['_group'] for item in result])

    def test_serpentine_and_start_element_across_three_rows(self):
        items = [
            bay(1, 0, 20), bay(2, 10, 20),
            bay(3, 0, 10), bay(4, 10, 10),
            bay(5, 0, 0), bay(6, 10, 0),
        ]
        ordered = sort_bays(items, 'y', True, False, True, 1.0)
        result = rotate_to_start(ordered, 4)
        self.assertEqual(
            [4, 3, 5, 6, 1, 2], [item['id'] for item in result])

    def test_equal_coordinates_use_element_id_tie_breaker(self):
        items = [bay(20, 0, 0), bay(10, 0, 0)]
        result = sort_bays(items, 'y', True, False, False, 1.0)
        self.assertEqual([10, 20], [item['id'] for item in result])

    def test_invalid_axis_and_tolerance_raise(self):
        with self.assertRaises(ValueError):
            sort_bays(self.grid, 'z', True, False, False, 1.0)
        with self.assertRaises(ValueError):
            sort_bays(self.grid, 'y', True, False, False, 0)


if __name__ == '__main__':
    unittest.main()
