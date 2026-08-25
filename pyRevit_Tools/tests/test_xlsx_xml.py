# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import xlsx_xml as xlsx


class ExcelColTests(unittest.TestCase):
    def test_single_letters(self):
        self.assertEqual(u'A', xlsx.excel_col(1))
        self.assertEqual(u'Z', xlsx.excel_col(26))

    def test_the_wrap_that_is_always_wrong(self):
        self.assertEqual(u'AA', xlsx.excel_col(27))
        self.assertEqual(u'AB', xlsx.excel_col(28))
        self.assertEqual(u'AZ', xlsx.excel_col(52))
        self.assertEqual(u'BA', xlsx.excel_col(53))

    def test_three_letters(self):
        self.assertEqual(u'ZZ', xlsx.excel_col(702))
        self.assertEqual(u'AAA', xlsx.excel_col(703))

    def test_zero_is_rejected(self):
        self.assertRaises(ValueError, xlsx.excel_col, 0)


class EscapingTests(unittest.TestCase):
    def test_xml_special_characters(self):
        self.assertEqual(u'a &amp; b &lt;c&gt; &quot;d&quot;',
                         xlsx.xml_escape(u'a & b <c> "d"'))

    def test_ampersand_is_escaped_before_the_others(self):
        """Escaping < first would turn &lt; into &amp;lt;."""
        self.assertEqual(u'&amp;lt;', xlsx.xml_escape(u'&lt;'))

    def test_chinese_passes_through(self):
        self.assertEqual(u'法定面積', xlsx.xml_escape(u'法定面積'))


class NumberDetectionTests(unittest.TestCase):
    def test_numbers(self):
        self.assertTrue(xlsx.is_number(1))
        self.assertTrue(xlsx.is_number(1.5))
        self.assertTrue(xlsx.is_number(-3))

    def test_bool_is_not_a_number(self):
        """True would be written as 1 and the column would lose its meaning."""
        self.assertFalse(xlsx.is_number(True))
        self.assertFalse(xlsx.is_number(False))

    def test_strings_are_not(self):
        self.assertFalse(xlsx.is_number(u'1'))
        self.assertFalse(xlsx.is_number(None))


class CellTests(unittest.TestCase):
    def test_number_cell_has_no_type_attribute(self):
        cell = xlsx.cell_xml(2, 1, 12.5, xlsx.STYLE_DECIMAL)
        self.assertIn(u'r="A2"', cell)
        self.assertIn(u's="3"', cell)
        self.assertIn(u'<v>12.5</v>', cell)
        self.assertNotIn(u't="inlineStr"', cell)

    def test_text_cell_is_inline(self):
        cell = xlsx.cell_xml(3, 2, u'B1F')
        self.assertIn(u'r="B3"', cell)
        self.assertIn(u't="inlineStr"', cell)
        self.assertIn(u'<t xml:space="preserve">B1F</t>', cell)

    def test_default_style_is_omitted(self):
        self.assertNotIn(u's=', xlsx.cell_xml(1, 1, u'x', xlsx.STYLE_TEXT))

    def test_blank_cells_are_dropped(self):
        self.assertEqual(u'', xlsx.cell_xml(1, 1, None))
        self.assertEqual(u'', xlsx.cell_xml(1, 1, u''))

    def test_zero_is_kept(self):
        """0 is falsy but is a real measurement, not an empty cell."""
        self.assertIn(u'<v>0</v>', xlsx.cell_xml(2, 1, 0, xlsx.STYLE_INT))


class SheetTests(unittest.TestCase):
    def _rows(self):
        return [[u'樓層', u'面積'], [u'B1F', 12.5], [u'1F', 20.0]]

    def test_header_row_gets_the_header_style(self):
        xml = xlsx.sheet_xml(self._rows())
        self.assertIn(u's="{}"'.format(xlsx.STYLE_HEADER), xml)

    def test_formats_apply_to_data_rows_only(self):
        xml = xlsx.sheet_xml(self._rows(),
                             {'formats': {2: xlsx.STYLE_DECIMAL}})
        self.assertIn(u'r="B2" s="3"', xml)
        # B1 is the header, so it keeps the header style rather than the
        # column format.
        self.assertIn(u'r="B1" s="1"', xml)

    def test_freeze_adds_pane_and_autofilter(self):
        xml = xlsx.sheet_xml(self._rows(), {'freeze': 1})
        self.assertIn(u'state="frozen"', xml)
        self.assertIn(u'<autoFilter ref="A1:B3"/>', xml)

    def test_no_freeze_means_no_autofilter(self):
        xml = xlsx.sheet_xml(self._rows())
        self.assertNotIn(u'autoFilter', xml)

    def test_widths_become_col_defs(self):
        xml = xlsx.sheet_xml(self._rows(), {'widths': [10, 20]})
        self.assertIn(u'<col min="1" max="1" width="10"', xml)
        self.assertIn(u'<col min="2" max="2" width="20"', xml)

    def test_empty_sheet_is_still_valid(self):
        xml = xlsx.sheet_xml([])
        self.assertIn(u'<dimension ref="A1:A1"/>', xml)
        self.assertIn(u'<sheetData>', xml)

    def test_ragged_rows_use_the_widest_for_dimension(self):
        xml = xlsx.sheet_xml([[u'a'], [u'b', u'c', u'd']])
        self.assertIn(u'<dimension ref="A1:C2"/>', xml)


class SheetNameTests(unittest.TestCase):
    def test_forbidden_characters_are_stripped(self):
        self.assertEqual(u'法定面積銷售面積',
                         xlsx.safe_sheet_name(u'法定面積/銷售面積'))
        self.assertEqual(u'ab', xlsx.safe_sheet_name(u'a[b]'))

    def test_length_is_capped(self):
        name = xlsx.safe_sheet_name(u'x' * 60)
        self.assertEqual(xlsx.SHEET_NAME_LIMIT, len(name))

    def test_duplicates_get_a_suffix(self):
        used = [u'面積']
        self.assertEqual(u'面積(2)', xlsx.safe_sheet_name(u'面積', used))

    def test_suffix_still_respects_the_length_cap(self):
        long_name = u'y' * 40
        used = [long_name[:xlsx.SHEET_NAME_LIMIT]]
        name = xlsx.safe_sheet_name(long_name, used)
        self.assertTrue(len(name) <= xlsx.SHEET_NAME_LIMIT)
        self.assertNotIn(name, used)

    def test_repeated_collisions_keep_counting(self):
        used = [u'面積', u'面積(2)']
        self.assertEqual(u'面積(3)', xlsx.safe_sheet_name(u'面積', used))

    def test_empty_name_gets_a_fallback(self):
        self.assertEqual(u'Sheet', xlsx.safe_sheet_name(u''))
        self.assertEqual(u'Sheet', xlsx.safe_sheet_name(None))


class WorkbookPartsTests(unittest.TestCase):
    def _sheets(self):
        return [(u'彙總', [[u'a']], {}), (u'法定面積', [[u'b']], {})]

    def test_every_required_part_is_present(self):
        names = [name for name, unused in xlsx.workbook_parts(self._sheets())]
        for required in ('[Content_Types].xml', '_rels/.rels',
                         'xl/_rels/workbook.xml.rels', 'xl/workbook.xml',
                         'xl/styles.xml', 'xl/worksheets/sheet1.xml',
                         'xl/worksheets/sheet2.xml'):
            self.assertIn(required, names)

    def test_styles_relationship_id_follows_the_sheets(self):
        parts = dict(xlsx.workbook_parts(self._sheets()))
        self.assertIn(u'Id="rId3"', parts['xl/_rels/workbook.xml.rels'])
        self.assertIn(u'Target="styles.xml"',
                      parts['xl/_rels/workbook.xml.rels'])

    def test_sheet_names_are_escaped_in_the_workbook(self):
        parts = dict(xlsx.workbook_parts([(u'a&b', [[u'x']], {})]))
        self.assertIn(u'name="a&amp;b"', parts['xl/workbook.xml'])

    def test_a_workbook_needs_a_sheet(self):
        self.assertRaises(ValueError, xlsx.workbook_parts, [])

    def test_styles_declare_as_many_xfs_as_the_style_constants(self):
        """A style index past cellXfs count makes Excel reject the file."""
        styles = xlsx.styles_xml()
        highest = max(xlsx.STYLE_TEXT, xlsx.STYLE_HEADER, xlsx.STYLE_INT,
                      xlsx.STYLE_DECIMAL)
        self.assertIn(u'<cellXfs count="{}">'.format(highest + 1), styles)


if __name__ == '__main__':
    unittest.main()
