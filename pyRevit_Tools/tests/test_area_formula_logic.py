# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import area_formula_logic as logic


def rect(width_m, depth_m, x=0.0, y=0.0):
    w = width_m * 1000.0
    d = depth_m * 1000.0
    return [(x, y), (x + w, y), (x + w, y + d), (x, y + d)]


def triangle(base_m, height_m):
    b = base_m * 1000.0
    h = height_m * 1000.0
    return [(0.0, 0.0), (b, 0.0), (0.0, h)]


def trapezoid(top_m, bottom_m, height_m):
    t = top_m * 1000.0
    b = bottom_m * 1000.0
    h = height_m * 1000.0
    offset = (b - t) / 2.0
    return [(0.0, 0.0), (b, 0.0), (b - offset, h), (offset, h)]


def sub(area_id, unit=u'A1', category=u'居室', loop=None, elevation=0.0,
        number=u''):
    return {
        'id': area_id,
        'unit': unit,
        'category': category,
        'loop': loop if loop is not None else rect(2.8, 4.5),
        'level_elevation': elevation,
        'number': number or u'A{}'.format(area_id),
    }


class NormalizeLoopTests(unittest.TestCase):
    def test_plain_rectangle_keeps_four_corners(self):
        self.assertEqual(4, len(logic.normalize_loop(rect(3.0, 2.0))))

    def test_collinear_midpoint_is_dropped(self):
        """A wall split into two segments puts a point mid-edge."""
        loop = [(0.0, 0.0), (1500.0, 0.0), (3000.0, 0.0),
                (3000.0, 2000.0), (0.0, 2000.0)]
        self.assertEqual(4, len(logic.normalize_loop(loop)))

    def test_repeated_and_closing_points_are_dropped(self):
        loop = [(0.0, 0.0), (0.0, 0.0), (3000.0, 0.0), (3000.0, 2000.0),
                (0.0, 2000.0), (0.0, 0.0)]
        self.assertEqual(4, len(logic.normalize_loop(loop)))

    def test_degenerate_input_returns_empty(self):
        self.assertEqual([], logic.normalize_loop([]))
        self.assertEqual([], logic.normalize_loop([(0.0, 0.0), (1.0, 0.0)]))


class ClassifyRectangleTests(unittest.TestCase):
    def test_rectangle_expression_and_value(self):
        result = logic.classify(rect(2.8, 4.5))
        self.assertEqual(logic.KIND_RECTANGLE, result['kind'])
        self.assertEqual(u'2.80 x 4.50', result['expression'])
        self.assertAlmostEqual(12.60, result['value_m2'], 2)
        self.assertAlmostEqual(12.60, result['actual_m2'], 2)

    def test_slightly_skewed_rectangle_still_recognised(self):
        loop = rect(3.0, 2.0)
        loop[2] = (loop[2][0] + 8.0, loop[2][1])   # 8 mm out of square
        result = logic.classify(loop)
        self.assertEqual(logic.KIND_RECTANGLE, result['kind'])

    def test_badly_skewed_quad_is_not_called_a_rectangle(self):
        loop = [(0.0, 0.0), (3000.0, 0.0), (2500.0, 2000.0), (200.0, 2000.0)]
        self.assertNotEqual(logic.KIND_RECTANGLE,
                            logic.classify(loop)['kind'])


class ClassifyTriangleTests(unittest.TestCase):
    def test_right_triangle_is_written_on_its_two_legs(self):
        """The hypotenuse can be the longest side, and nobody writes that."""
        result = logic.classify(triangle(2.6, 4.5))
        self.assertEqual(logic.KIND_TRIANGLE, result['kind'])
        self.assertEqual(u'2.60 x 4.50 / 2', result['expression'])
        self.assertAlmostEqual(5.85, result['actual_m2'], 2)
        self.assertAlmostEqual(5.85, result['value_m2'], 2)

    def test_sliver_right_triangle_uses_its_legs_not_the_hypotenuse(self):
        result = logic.classify(triangle(10.0, 0.5))
        self.assertEqual(u'0.50 x 10.00 / 2', result['expression'])
        self.assertAlmostEqual(2.5, result['value_m2'], 2)

    def test_oblique_triangle_falls_back_to_the_longest_side(self):
        loop = [(0.0, 0.0), (6000.0, 0.0), (4500.0, 2000.0)]
        result = logic.classify(loop)
        self.assertEqual(logic.KIND_TRIANGLE, result['kind'])
        self.assertTrue(result['expression'].startswith(u'6.00'))
        self.assertAlmostEqual(result['actual_m2'], result['value_m2'], 2)


class ClassifyTrapezoidTests(unittest.TestCase):
    def test_trapezoid_expression_and_value(self):
        result = logic.classify(trapezoid(5.10, 6.20, 1.90))
        self.assertEqual(logic.KIND_TRAPEZOID, result['kind'])
        self.assertEqual(u'(5.10 + 6.20) x 1.90 / 2', result['expression'])
        self.assertAlmostEqual(10.735, result['actual_m2'], 2)
        self.assertAlmostEqual(result['actual_m2'], result['value_m2'], 2)

    def test_parallelogram_is_handled_as_a_trapezoid(self):
        loop = [(0.0, 0.0), (4000.0, 0.0), (5000.0, 2000.0), (1000.0, 2000.0)]
        result = logic.classify(loop)
        self.assertEqual(logic.KIND_TRAPEZOID, result['kind'])
        self.assertAlmostEqual(result['actual_m2'], result['value_m2'], 2)


class UnrecognisedShapeTests(unittest.TestCase):
    def test_l_shape_has_no_formula(self):
        loop = [(0.0, 0.0), (4000.0, 0.0), (4000.0, 1500.0),
                (1500.0, 1500.0), (1500.0, 4000.0), (0.0, 4000.0)]
        result = logic.classify(loop)
        self.assertEqual(logic.KIND_UNKNOWN, result['kind'])
        self.assertEqual(u'', result['expression'])
        self.assertIn(u'6 邊形', result['reason'])
        # The area is still reported — the row is not lost.
        self.assertAlmostEqual(9.75, result['actual_m2'], 2)

    def test_quad_with_no_parallel_sides_has_no_formula(self):
        loop = [(0.0, 0.0), (4000.0, 300.0), (3600.0, 2600.0),
                (500.0, 1900.0)]
        result = logic.classify(loop)
        self.assertEqual(logic.KIND_UNKNOWN, result['kind'])
        self.assertIn(u'平行', result['reason'])

    def test_empty_boundary_is_reported_not_crashed(self):
        result = logic.classify([])
        self.assertEqual(logic.KIND_UNKNOWN, result['kind'])
        self.assertEqual(0.0, result['actual_m2'])
        self.assertIn(u'讀不到', result['reason'])


class ExpectedAreaTests(unittest.TestCase):
    """Revit's own area is the number the reviewer sees, so it is the yardstick."""

    def test_revit_area_is_reported_over_the_polygon_maths(self):
        result = logic.classify(rect(2.8, 4.5), expected_m2=12.58)
        self.assertAlmostEqual(12.58, result['actual_m2'], 2)

    def test_expression_disagreeing_with_revit_is_refused(self):
        result = logic.classify(rect(2.8, 4.5), expected_m2=20.0)
        self.assertEqual(logic.KIND_UNKNOWN, result['kind'])
        self.assertEqual(u'', result['expression'])
        self.assertIn(u'不符', result['reason'])
        self.assertAlmostEqual(20.0, result['actual_m2'], 2)


class ClassifyLoopsTests(unittest.TestCase):
    def test_single_loop_behaves_like_classify(self):
        result = logic.classify_loops([rect(2.8, 4.5)])
        self.assertEqual(logic.KIND_RECTANGLE, result['kind'])

    def test_a_hole_makes_it_unformulatable(self):
        """A ring is not a shape any a x b describes."""
        outer = rect(10.0, 10.0)
        hole = rect(2.0, 2.0, x=3000.0, y=3000.0)
        result = logic.classify_loops([outer, hole], expected_m2=96.0)
        self.assertEqual(logic.KIND_UNKNOWN, result['kind'])
        self.assertEqual(u'', result['expression'])
        self.assertIn(u'迴圈', result['reason'])
        self.assertAlmostEqual(96.0, result['actual_m2'], 2)

    def test_no_loops_at_all(self):
        result = logic.classify_loops([])
        self.assertEqual(logic.KIND_UNKNOWN, result['kind'])

    def test_build_report_uses_loops_and_revit_area(self):
        record = sub(1, u'A1', u'居室', None)
        record.pop('loop')
        record['loops'] = [rect(2.8, 4.5)]
        record['area_m2'] = 12.60
        report = logic.build_report([record])
        item = report['items'][0]
        self.assertEqual(u'2.80 x 4.50', item['expression'])
        self.assertAlmostEqual(12.60, item['actual_m2'], 2)


class SelfCheckTests(unittest.TestCase):
    """The arithmetic is what makes a recognised shape trustworthy."""

    def test_expression_must_reproduce_the_polygon_area(self):
        # A very tight tolerance makes even honest rounding fail, which proves
        # the check is actually running rather than being decorative.
        result = logic.classify(rect(2.815, 4.505), area_tolerance=0.0)
        self.assertEqual(logic.KIND_UNKNOWN, result['kind'])
        self.assertIn(u'不符', result['reason'])

    def test_normal_rounding_passes_the_default_tolerance(self):
        result = logic.classify(rect(2.815, 4.505))
        self.assertEqual(logic.KIND_RECTANGLE, result['kind'])


class LetterMapTests(unittest.TestCase):
    def test_known_categories_get_their_conventional_letters(self):
        letters = logic.build_letter_map(
            [u'居室', u'陽台', u'樓梯間', u'梯廳', u'機電設備'])
        self.assertEqual(u'H', letters[u'居室'])
        self.assertEqual(u'B', letters[u'陽台'])
        self.assertEqual(u'S', letters[u'樓梯間'])
        self.assertEqual(u'L', letters[u'梯廳'])
        self.assertEqual(u'E', letters[u'機電設備'])

    def test_unknown_category_still_gets_a_letter(self):
        letters = logic.build_letter_map([u'居室', u'防空避難室'])
        self.assertEqual(u'H', letters[u'居室'])
        self.assertTrue(letters[u'防空避難室'])
        self.assertNotEqual(u'H', letters[u'防空避難室'])

    def test_letters_are_unique(self):
        letters = logic.build_letter_map(
            [u'居室', u'陽台', u'甲', u'乙', u'丙'])
        self.assertEqual(len(letters), len(set(letters.values())))

    def test_override_wins(self):
        letters = logic.build_letter_map([u'居室'], {u'居室': u'R'})
        self.assertEqual(u'R', letters[u'居室'])


class BuildReportTests(unittest.TestCase):
    def _records(self):
        return [
            sub(1, u'A1', u'居室', rect(2.8, 4.5)),
            sub(2, u'A1', u'居室', rect(10.5, 2.3)),
            sub(3, u'A1', u'陽台', rect(1.4, 1.6)),
            sub(4, u'A2', u'居室', rect(2.3, 4.5)),
            sub(5, u'A2', u'機電設備', triangle(2.6, 4.5)),
        ]

    def test_codes_run_continuously_per_category_across_units(self):
        report = logic.build_report(self._records())
        codes = dict((item['id'], item['code']) for item in report['items'])
        self.assertEqual(u'H1', codes[1])
        self.assertEqual(u'H2', codes[2])
        self.assertEqual(u'H3', codes[4])   # A2's 居室 continues from A1's
        self.assertEqual(u'B1', codes[3])
        self.assertEqual(u'E1', codes[5])

    def test_groups_are_unit_by_category(self):
        report = logic.build_report(self._records())
        keys = [(g['unit'], g['category']) for g in report['groups']]
        self.assertIn((u'A1', u'居室'), keys)
        self.assertIn((u'A2', u'機電設備'), keys)
        self.assertEqual(len(keys), len(set(keys)))

    def test_sum_line_only_when_more_than_one_term(self):
        report = logic.build_report(self._records())
        by_key = dict(((g['unit'], g['category']), g)
                      for g in report['groups'])
        self.assertEqual(u'(H1) + (H2)',
                         by_key[(u'A1', u'居室')]['sum_expression'])
        self.assertEqual(u'', by_key[(u'A1', u'陽台')]['sum_expression'])

    def test_group_totals_match_the_members(self):
        report = logic.build_report(self._records())
        group = dict(((g['unit'], g['category']), g)
                     for g in report['groups'])[(u'A1', u'居室')]
        self.assertAlmostEqual(12.60 + 24.15, group['total_m2'], 2)

    def test_unformulated_rows_are_collected_but_keep_their_code(self):
        records = self._records()
        records.append(sub(6, u'A2', u'居室',
                           [(0.0, 0.0), (4000.0, 0.0), (4000.0, 1500.0),
                            (1500.0, 1500.0), (1500.0, 4000.0),
                            (0.0, 4000.0)]))
        report = logic.build_report(records)
        self.assertEqual(1, len(report['unformulated']))
        odd = report['unformulated'][0]
        self.assertEqual(6, odd['id'])
        self.assertTrue(odd['code'])
        self.assertTrue(odd['actual_m2'] > 0)

    def test_empty_input(self):
        report = logic.build_report([])
        self.assertEqual(0, report['total'])
        self.assertEqual([], report['groups'])


class OutputTests(unittest.TestCase):
    def _report(self):
        return logic.build_report([
            sub(1, u'A1', u'居室', rect(2.8, 4.5)),
            sub(2, u'A1', u'居室', rect(10.5, 2.3)),
        ])

    def test_group_lines_read_like_the_printed_table(self):
        lines = logic.group_lines(self._report()['groups'][0])
        self.assertEqual(u'A1 居室', lines[0])
        self.assertEqual(u'(H1) = 2.80 x 4.50 = 12.60 m²', lines[1])
        self.assertEqual(u'(H2) = 10.50 x 2.30 = 24.15 m²', lines[2])
        self.assertEqual(u'(H1) + (H2) = 36.75 m²', lines[3])

    def test_unformulated_line_says_so_and_still_shows_area(self):
        report = logic.build_report([
            sub(1, u'A1', u'居室',
                [(0.0, 0.0), (4000.0, 0.0), (4000.0, 1500.0),
                 (1500.0, 1500.0), (1500.0, 4000.0), (0.0, 4000.0)])])
        line = logic.group_lines(report['groups'][0])[1]
        self.assertIn(logic.NO_FORMULA, line)
        self.assertIn(u'9.75 m²', line)

    def test_summary_reports_clean_and_dirty_cases(self):
        self.assertIn(u'全部都能列式',
                      logic.report_summary(self._report()))
        report = logic.build_report([
            sub(1, u'A1', u'居室',
                [(0.0, 0.0), (4000.0, 0.0), (4000.0, 1500.0),
                 (1500.0, 1500.0), (1500.0, 4000.0), (0.0, 4000.0)])])
        self.assertIn(u'無法列式 1 個', logic.report_summary(report))

    def test_export_rows_have_a_header_and_a_subtotal(self):
        rows = logic.export_rows(self._report())
        self.assertEqual(u'戶別', rows[0][0])
        self.assertEqual(u'計算式', rows[0][4])
        self.assertEqual(u'小計', rows[-1][2])
        self.assertEqual(3 + 1, len(rows))


if __name__ == '__main__':
    unittest.main()
