# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import area_export_logic as logic
import xlsx_xml


# 100 sq ft and 40 ft are chosen because their metric values are not round —
# a passthrough bug would still look plausible with 1.0.
SQ_FT = 100.0
FT = 40.0


def area(area_id, number=u'A1', name=u'辦公室', level=u'1F', elevation=0.0,
         area_sqft=SQ_FT, perimeter_ft=FT, scheme=u'法定面積',
         status=u'正常', warnings=None, area_type=u'室內'):
    return {
        'id': area_id,
        'number': number,
        'name': name,
        'level': level,
        'level_elevation': elevation,
        'area_sqft': area_sqft,
        'perimeter_ft': perimeter_ft,
        'scheme': scheme,
        'status': status,
        'warnings': warnings or [],
        'area_type': area_type,
    }


class RecordValueTests(unittest.TestCase):
    def test_area_is_converted_to_square_metres(self):
        value = logic.record_value(area(1), 'area_m2')
        self.assertAlmostEqual(100.0 * 0.09290304, value, 2)
        self.assertNotAlmostEqual(100.0, value, 2)

    def test_perimeter_is_converted_to_metres(self):
        value = logic.record_value(area(1), 'perimeter_m')
        self.assertAlmostEqual(40.0 * 0.3048, value, 2)

    def test_id_is_an_integer_not_text(self):
        self.assertEqual(7, logic.record_value(area(7), 'id'))
        self.assertTrue(xlsx_xml.is_number(logic.record_value(area(7), 'id')))

    def test_warnings_join_their_labels(self):
        record = area(1, warnings=[{'label': u'多餘面積'},
                                   {'label': u'未封閉'}])
        self.assertEqual(u'多餘面積；未封閉',
                         logic.record_value(record, 'warnings'))

    def test_plain_string_warnings_survive(self):
        record = area(1, warnings=[u'某警告'])
        self.assertEqual(u'某警告', logic.record_value(record, 'warnings'))

    def test_missing_values_become_blank_not_none(self):
        self.assertEqual(u'', logic.record_value({}, 'name'))
        self.assertEqual(0.0, logic.record_value({}, 'area_m2'))


class FieldSelectionTests(unittest.TestCase):
    def test_unknown_keys_are_dropped(self):
        self.assertEqual(['number', 'name'],
                         logic.resolve_fields(['number', 'nope', 'name']))

    def test_empty_selection_falls_back_to_the_default(self):
        self.assertEqual(list(logic.DEFAULT_FIELD_KEYS),
                         logic.resolve_fields([]))
        self.assertEqual(list(logic.DEFAULT_FIELD_KEYS),
                         logic.resolve_fields(None))

    def test_all_nonsense_also_falls_back(self):
        self.assertEqual(list(logic.DEFAULT_FIELD_KEYS),
                         logic.resolve_fields(['nope']))

    def test_order_follows_the_request_not_the_menu(self):
        self.assertEqual(['name', 'number'],
                         logic.resolve_fields(['name', 'number']))

    def test_every_menu_entry_resolves(self):
        keys = [key for unused, key in logic.field_labels()]
        self.assertEqual(keys, logic.resolve_fields(keys))


class BuildSheetTests(unittest.TestCase):
    def test_header_matches_the_chosen_fields(self):
        rows, unused = logic.build_sheet([area(1)], ['number', 'area_m2'])
        self.assertEqual([u'編號', u'面積(m²)'], rows[0])

    def test_rows_follow_the_shared_sort_order(self):
        records = [area(1, u'A10', elevation=0.0),
                   area(2, u'A2', elevation=0.0),
                   area(3, u'A1', elevation=-3000.0)]
        rows, unused = logic.build_sheet(records, ['number'])
        self.assertEqual([[u'編號'], [u'A1'], [u'A2'], [u'A10']], rows)

    def test_spec_widths_and_formats_line_up_with_the_columns(self):
        keys = ['number', 'area_m2', 'id']
        rows, spec = logic.build_sheet([area(1)], keys)
        self.assertEqual(len(keys), len(spec['widths']))
        self.assertEqual(len(keys), len(rows[0]))
        self.assertEqual(xlsx_xml.STYLE_DECIMAL, spec['formats'][2])
        self.assertEqual(xlsx_xml.STYLE_INT, spec['formats'][3])
        self.assertEqual(1, spec['freeze'])

    def test_no_records_still_yields_a_header(self):
        rows, unused = logic.build_sheet([], ['number'])
        self.assertEqual([[u'編號']], rows)


class BuildSummaryTests(unittest.TestCase):
    def test_totals_per_level_then_per_scheme_then_grand(self):
        grouped = [(u'法定面積', [area(1, level=u'B1F', elevation=-3000.0),
                                area(2, level=u'1F', elevation=0.0),
                                area(3, level=u'1F', elevation=0.0)])]
        rows, unused = logic.build_summary(grouped)
        self.assertEqual([u'面積計畫', u'樓層', u'面積數', u'合計面積(m²)'],
                         rows[0])
        self.assertEqual(u'B1F', rows[1][1])
        self.assertEqual(1, rows[1][2])
        self.assertEqual(u'1F', rows[2][1])
        self.assertEqual(2, rows[2][2])
        self.assertEqual(u'小計', rows[3][1])
        self.assertEqual(3, rows[3][2])
        self.assertEqual(u'總計', rows[4][0])
        self.assertEqual(3, rows[4][2])

    def test_levels_are_ordered_by_elevation_not_name(self):
        grouped = [(u'x', [area(1, level=u'B1F', elevation=-3000.0),
                           area(2, level=u'2F', elevation=6000.0),
                           area(3, level=u'1F', elevation=0.0)])]
        rows, unused = logic.build_summary(grouped)
        self.assertEqual([u'B1F', u'1F', u'2F'],
                         [row[1] for row in rows[1:4]])

    def test_grand_total_spans_schemes(self):
        grouped = [(u'a', [area(1)]), (u'b', [area(2), area(3)])]
        rows, unused = logic.build_summary(grouped)
        self.assertEqual(3, rows[-1][2])

    def test_totals_use_the_same_conversion_as_the_detail_sheets(self):
        grouped = [(u'a', [area(1), area(2)])]
        rows, unused = logic.build_summary(grouped)
        detail, unused_spec = logic.build_sheet([area(1)], ['area_m2'])
        self.assertAlmostEqual(detail[1][0] * 2, rows[-1][3], 2)

    def test_empty_export_still_produces_a_grand_total(self):
        rows, unused = logic.build_summary([])
        self.assertEqual(u'總計', rows[-1][0])
        self.assertEqual(0, rows[-1][2])


class BuildWorkbookTests(unittest.TestCase):
    def test_summary_comes_first_then_one_sheet_per_scheme(self):
        grouped = [(u'法定面積', [area(1)]), (u'銷售面積', [area(2)])]
        sheets = logic.build_workbook(grouped)
        self.assertEqual(3, len(sheets))
        self.assertEqual(logic.SUMMARY_SHEET, sheets[0][0])
        self.assertEqual([u'法定面積', u'銷售面積'],
                         [name for name, unused, unused2 in sheets[1:]])

    def test_scheme_names_are_made_sheet_safe_and_unique(self):
        grouped = [(u'法定/面積', [area(1)]), (u'法定/面積', [area(2)])]
        names = [name for name, unused, unused2
                 in logic.build_workbook(grouped)]
        self.assertEqual(u'法定面積', names[1])
        self.assertEqual(u'法定面積(2)', names[2])

    def test_a_scheme_called_the_summary_name_does_not_collide(self):
        grouped = [(logic.SUMMARY_SHEET, [area(1)])]
        names = [name for name, unused, unused2
                 in logic.build_workbook(grouped)]
        self.assertEqual(len(names), len(set(names)))

    def test_output_is_shaped_for_the_xml_writer(self):
        sheets = logic.build_workbook([(u'a', [area(1)])])
        parts = dict(xlsx_xml.workbook_parts(sheets))
        self.assertIn('xl/worksheets/sheet2.xml', parts)


class ExportLinesTests(unittest.TestCase):
    def test_summary_reports_schemes_counts_and_fields(self):
        grouped = [(u'法定面積', [area(1), area(2)])]
        text = logic.export_lines(grouped, ['number', 'area_m2'],
                                  path=u'C:/out.xlsx')
        self.assertIn(u'面積計畫：1 個', text)
        self.assertIn(u'面積合計：2 個', text)
        self.assertIn(u'編號、面積(m²)', text)
        self.assertIn(u'C:/out.xlsx', text)

    def test_default_fields_are_named_when_none_chosen(self):
        text = logic.export_lines([(u'a', [area(1)])], [])
        self.assertIn(u'樓層', text)


if __name__ == '__main__':
    unittest.main()
