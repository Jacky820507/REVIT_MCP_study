# -*- coding: utf-8 -*-
import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import parking_excel_logic
from parking_excel_logic import (
    annotation_matches,
    classify_any_space,
    classify_space,
    empty_counts,
    find_unique_item_rows,
    level_basis,
    normalize_label,
    parse_dimensions,
    protected_input_formula_shape_ok,
    resolve_geometric_level_ids,
    row_formula_shape_ok,
    standalone_tables,
    wheel_stop_values,
    wheel_stop_formula_multiplier,
)


B1_LEVELS = [
    (11, u'B3F', -12000.0),
    (12, u'B2F', -8000.0),
    (13, u'B1F', -4000.0),
    (14, u'1F', 0.0),
]


class ParkingExcelLogicTests(unittest.TestCase):
    def test_annotation_filter_matches_normalized_schedule_value(self):
        self.assertTrue(
            annotation_matches(u' 汽車停車 ', [u'汽車停車', u'機車停車']))
        self.assertFalse(
            annotation_matches(u'', [u'汽車停車']))
        self.assertFalse(
            annotation_matches(u'其他停車', [u'汽車停車']))

    def test_schedule_annotation_scope_keeps_vehicle_kind_boundary(self):
        self.assertTrue(
            annotation_matches(u'汽車停車', [u'汽車停車']))
        self.assertIsNone(
            classify_space(
                'car', 3000, 7000,
                name=u'大客車 300*700',
                accessible=False,
            ))
        self.assertEqual(
            'bus',
            classify_space(
                'bus', 3000, 7000,
                name=u'大客車 300*700',
                accessible=False,
            ))

    def test_all_six_target_dimensions(self):
        cases = [
            ('bus', 3000, 7000, False, 'bus'),
            ('car', 2500, 6000, False, 'side_car'),
            ('car', 2500, 5500, False, 'general_car'),
            ('car', 3500, 6000, True, 'accessible_car'),
            ('motorcycle', 1000, 2000, False, 'general_motorcycle'),
            ('motorcycle', 2200, 2250, True, 'accessible_motorcycle'),
        ]
        for schedule, width, length, accessible, expected in cases:
            self.assertEqual(
                expected,
                classify_space(schedule, width, length, accessible=accessible),
            )

    def test_name_dimension_parsing_units(self):
        self.assertEqual((1000.0, 2000.0), parse_dimensions('一般 1m x 2m'))
        self.assertEqual((2500.0, 5500.0), parse_dimensions('汽車 250*550'))
        self.assertEqual((2500.0, 5500.0), parse_dimensions('2500×5500 mm'))

    def test_name_fallback_and_accessibility(self):
        self.assertEqual(
            'accessible_motorcycle',
            classify_space(
                'motorcycle', name='無障礙機車 2.2m x 2.25m'),
        )

    def test_dimension_only_classification_avoids_parameter_lookup(self):
        self.assertEqual(
            'accessible_car',
            classify_space('car', 3500, 6000, accessible=None),
        )
        self.assertEqual(
            'accessible_motorcycle',
            classify_space('motorcycle', 2200, 2250, accessible=None),
        )

    def test_auto_detect_classifies_without_schedule_boundary(self):
        self.assertEqual(
            'bus',
            classify_any_space(3000, 7000, accessible=None),
        )
        self.assertEqual(
            'general_car',
            classify_any_space(2500, 5500, accessible=None),
        )
        self.assertEqual(
            'accessible_motorcycle',
            classify_any_space(2200, 2250, accessible=None),
        )

    def test_tolerance_boundary_and_rejection(self):
        self.assertEqual(
            'general_car',
            classify_space('car', 2550, 5450, accessible=False),
        )
        self.assertIsNone(
            classify_space('car', 2551, 5500, accessible=False),
        )

    def test_schedule_boundary_prevents_cross_classification(self):
        self.assertIsNone(
            classify_space('car', 3000, 7000, accessible=False),
        )
        self.assertIsNone(
            classify_space('motorcycle', 2500, 5500, accessible=False),
        )

    def test_wheel_stops_one_and_two(self):
        counts = empty_counts()
        counts.update({
            'bus': 1,
            'side_car': 37,
            'general_car': 500,
            'accessible_car': 14,
        })
        self.assertEqual((552, 1, 552), wheel_stop_values(counts, 1))
        self.assertEqual((552, 2, 1104), wheel_stop_values(counts, 2))

    def test_formula_shape_requires_same_row_f_and_g(self):
        self.assertTrue(
            row_formula_shape_ok(8, ('=$F8*$G8', '=H8', '=I8')))
        self.assertTrue(
            row_formula_shape_ok(14, ('=PRODUCT(F14,G14)', '=H14', '=I14')))
        self.assertTrue(
            row_formula_shape_ok(
                10,
                ('=ROUND(F10*G10,2)', '=SUM(H10:H10)', '=ROUND($I10,2)'),
            ))
        self.assertFalse(
            row_formula_shape_ok(8, ('=H7', '=H8', '=I8')))
        self.assertFalse(
            row_formula_shape_ok(8, ('=F8', '=H8', '=I8')))
        self.assertFalse(
            row_formula_shape_ok(8, ('', '=H8', '=I8')))
        self.assertFalse(
            row_formula_shape_ok(8, ('=F8+G8', '=H8', '=I8')))
        self.assertFalse(
            row_formula_shape_ok(8, ('=SUM(F8,G8)', '=H8', '=I8')))
        self.assertFalse(
            row_formula_shape_ok(8, ('=IF(A1>0,F8*G8,0)', '=H8', '=I8')))
        self.assertFalse(
            row_formula_shape_ok(8, ('=IF(F8>0,G8,0)', '=H8', '=I8')))

    def test_protected_input_formula_whitelist(self):
        rows = {
            'wheel_stop': 8,
            'bus': 9,
            'side_car': 10,
            'general_car': 11,
            'accessible_car': 12,
        }
        self.assertEqual(
            2,
            wheel_stop_formula_multiplier('=SUM(F9:F12)*2', rows))
        self.assertTrue(
            protected_input_formula_shape_ok(
                'wheel_stop', 8, '=SUM(F9:F12)*2', rows))
        self.assertTrue(
            protected_input_formula_shape_ok(
                'accessible_car', 12, '=10+4', rows))
        self.assertFalse(
            protected_input_formula_shape_ok(
                'accessible_car', 12, '=F10+4', rows))
        self.assertFalse(
            protected_input_formula_shape_ok(
                'wheel_stop', 8, '=SUM(F9:F13)*2', rows))
        self.assertFalse(
            protected_input_formula_shape_ok(
                'wheel_stop', 8, '=IF(A1>0,SUM(F9:F12)*2,0)', rows))

    def test_label_normalization_and_unique_matching(self):
        self.assertEqual(
            '無障礙汽車350*600',
            normalize_label(' 無障礙汽車（350 × 600），'),
        )
        rows = [
            (8, '塑膠車輪檔'),
            (9, '大客車（300 × 700）'),
            (10, '側停汽車 250 x 600'),
            (11, '一般汽車，250＊550'),
            (12, '無障礙汽車 (350*600)'),
            (13, '一般機車 100×200'),
            (14, '無障礙機車【220 x 225】'),
        ]
        matched = find_unique_item_rows(rows)
        self.assertEqual(8, matched['wheel_stop'])
        self.assertEqual(14, matched['accessible_motorcycle'])

    def test_duplicate_label_is_rejected(self):
        rows = [
            (8, '塑膠車輪檔'), (18, '塑膠車輪檔'),
            (9, '大客車300*700'), (10, '側停汽車250*600'),
            (11, '一般汽車250*550'), (12, '無障礙汽車350*600'),
            (13, '一般機車100*200'), (14, '無障礙機車220*225'),
        ]
        with self.assertRaises(ValueError):
            find_unique_item_rows(rows)

    def test_geometric_level_beats_a_shared_level_parameter(self):
        # The reported bug: every bay in the link carries one Level value, so
        # bays on B2F/B3F must still be separated by where they actually sit.
        self.assertEqual([13], resolve_geometric_level_ids(-4000.0, B1_LEVELS))
        self.assertEqual([13], resolve_geometric_level_ids(-4150.0, B1_LEVELS))
        self.assertEqual([12], resolve_geometric_level_ids(-8000.0, B1_LEVELS))
        self.assertEqual([11], resolve_geometric_level_ids(-11500.0, B1_LEVELS))
        self.assertEqual([14], resolve_geometric_level_ids(120.0, B1_LEVELS))

    def test_geometric_level_is_unknown_without_usable_evidence(self):
        self.assertEqual([], resolve_geometric_level_ids(None, B1_LEVELS))
        self.assertEqual([], resolve_geometric_level_ids(-4000.0, []))
        # Below every level: fall back to the Level parameter instead of
        # silently dropping the bay.
        self.assertEqual([], resolve_geometric_level_ids(-99000.0, B1_LEVELS))

    def test_levels_sharing_an_elevation_are_all_returned(self):
        levels = list(B1_LEVELS) + [(15, u'B1F-結構', -4000.0)]
        self.assertEqual(
            [13, 15], sorted(resolve_geometric_level_ids(-3900.0, levels)))

    def test_level_basis_labels_each_kind_of_evidence(self):
        self.assertEqual(
            parking_excel_logic.LEVEL_BASIS_MATCH, level_basis(13, [13]))
        self.assertEqual(
            parking_excel_logic.LEVEL_BASIS_GEOMETRIC, level_basis(13, [12]))
        self.assertEqual(
            parking_excel_logic.LEVEL_BASIS_GEOMETRIC_ONLY,
            level_basis(None, [12]))
        self.assertEqual(
            parking_excel_logic.LEVEL_BASIS_PARAMETER_ONLY,
            level_basis(13, []))
        self.assertEqual(
            parking_excel_logic.LEVEL_BASIS_UNKNOWN, level_basis(None, []))

    def test_audit_reports_level_exclusions_and_mismatches(self):
        takeoff = {
            'details': [{
                'source_key': 'link:77',
                'level_id': 13,
                'element_id': 1,
                'geometric_level_id': 12,
                'level_basis': parking_excel_logic.LEVEL_BASIS_GEOMETRIC,
                'classification_key': 'general_car',
            }],
            'unclassified': [],
            'ignored': [],
            'annotation_candidates': [],
            'source_counts': [{
                'source_key': 'link:77',
                'name': u'鮮食中心',
                'levels': u'B1F',
                'included': 1,
                'excluded_by_level': 42,
                'level_mismatch': 1,
            }],
        }
        audit = dict(
            (row[0], row) for row in standalone_tables(takeoff, 2)['audit_rows'])
        self.assertEqual(u'42 個', audit[u'不在所選樓層而排除'][2])
        self.assertEqual(u'REVIEW', audit[u'樓層參數與實際高程不符'][1])
        self.assertIn(u'依樓層排除 42 個', audit[u'讀取範圍'][2])

    def test_detail_columns_keep_classification_in_column_f(self):
        headers = list(parking_excel_logic.STANDALONE_DETAIL_HEADERS)
        self.assertEqual(u'分類鍵', headers[5])
        self.assertEqual(
            [u'樓層名稱', u'幾何樓層 Id', u'幾何樓層',
             u'底部高程(mm)', u'樓層判定'],
            headers[11:])

    def test_standalone_tables_preserve_source_key_and_formulas(self):
        takeoff = {
            'details': [
                {
                    'source_key': 'host',
                    'source_name': '主模型',
                    'level_id': 3,
                    'element_id': 10,
                    'name': '一般汽車',
                    'classification_key': 'general_car',
                    'classification_label': '一般汽車 250*550',
                    'width_mm': 2500,
                    'length_mm': 5500,
                    'grouped': False,
                    'status': '已分類',
                },
                {
                    'source_key': 'link:77',
                    'source_name': '鮮食中心',
                    'level_id': 8,
                    'element_id': 10,
                    'name': '一般機車',
                    'classification_key': 'general_motorcycle',
                    'classification_label': '一般機車 100*200',
                    'width_mm': 1000,
                    'length_mm': 2000,
                    'grouped': True,
                    'status': '已分類',
                },
            ],
            'unclassified': [],
            'ignored': [],
            'annotation_candidates': [],
            'source_counts': [
                {
                    'source_key': 'host',
                    'name': '主模型',
                    'levels': '全部樓層',
                    'included': 1,
                },
                {
                    'source_key': 'link:77',
                    'name': '鮮食中心',
                    'levels': 'B1F',
                    'included': 1,
                },
            ],
        }
        tables = standalone_tables(takeoff, 2)
        self.assertEqual('host', tables['detail_rows'][0][0])
        self.assertEqual('link:77', tables['detail_rows'][1][0])
        self.assertTrue(tables['formula_rows'][0][2].startswith('=COUNTIF('))
        self.assertEqual(2, tables['formula_rows'][-1][3])
        self.assertTrue(tables['formula_rows'][-1][4].startswith('=C'))


if __name__ == '__main__':
    unittest.main()
