# -*- coding: utf-8 -*-

import importlib.util
import os
import unittest
from unittest import mock


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
MODULE_PATH = os.path.join(
    ROOT, 'MCP_Tools.extension', 'lib', 'takeoff_direct_publish.py')
SPEC = importlib.util.spec_from_file_location(
    'takeoff_direct_publish', MODULE_PATH)
publish = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publish)

STYLES_PATH = os.path.join(
    ROOT, 'MCP_Tools.extension', 'lib', 'takeoff_excel_styles.py')
STYLES_SPEC = importlib.util.spec_from_file_location(
    'takeoff_excel_styles', STYLES_PATH)
styles = importlib.util.module_from_spec(STYLES_SPEC)
STYLES_SPEC.loader.exec_module(styles)

BUTTON_ROOT = os.path.join(
    ROOT, 'MCP_Tools.extension', 'MCP_Macros.tab',
    'Takeoff.panel')
DIRECT_BUTTONS = (
    'Baseboard',
    'CeilingTakeoff',
    'FloorTakeoff',
    'InteriorWallPaint',
)

ALL_FORMATTED_BUTTONS = DIRECT_BUTTONS + (
    'PartitionTakeoff',
    'RcVolumeExcel',
)

PUBLISH_BUTTONS = DIRECT_BUTTONS + ('PartitionTakeoff',)


class FakeId(object):
    def __init__(self, value):
        self.IntegerValue = value


class FakeExcelError(object):
    def __init__(self, error_code):
        self.ErrorCode = error_code


class FakeAxis(object):
    def __init__(self, count):
        self.Count = count


class FakeUsedRange(object):
    def __init__(self, formulas, values):
        self.Row = 1
        self.Column = 1
        self.Rows = FakeAxis(len(formulas))
        self.Columns = FakeAxis(len(formulas[0]))
        self.Formula = formulas
        self.Value2 = values


class FakeSheet(object):
    def __init__(self, name, formulas, values):
        self.Name = name
        self.UsedRange = FakeUsedRange(formulas, values)


class FakeWorksheets(object):
    def __init__(self, sheets):
        self._sheets = sheets
        self.Count = len(sheets)

    def Item(self, index):
        return self._sheets[index - 1]


class FakeWorkbook(object):
    def __init__(self, sheets):
        self.Worksheets = FakeWorksheets(sheets)


class TakeoffDirectPublishTests(unittest.TestCase):
    def test_composite_keys_keep_sources_distinct(self):
        self.assertEqual('host:42', publish.composite_element_key(
            'host', FakeId(42)))
        self.assertEqual('link:7:42', publish.composite_element_key(
            'link:7', FakeId(42)))

    def test_rekey_room_records_tags_openings_and_hosts(self):
        rooms = [{'element_id': 9, 'number': '101'}]
        related = {
            9: [{'id': 11, 'host_id': 12, 'name': 'D1'}],
        }
        tagged_rooms, tagged = publish.rekey_room_records(
            'link:5', 'Architectural [id 5]', rooms, related)
        self.assertEqual('link:5:9', tagged_rooms[0]['element_id'])
        self.assertEqual(
            'Architectural [id 5]', tagged_rooms[0]['source_label'])
        self.assertEqual('link:5:11', tagged['link:5:9'][0]['id'])
        self.assertEqual('link:5:12', tagged['link:5:9'][0]['host_id'])

    def test_merge_stats_recurses_and_extends(self):
        result = publish.merge_stats(
            {'rooms': 2, 'sources': {'room-area': 1}, 'warnings': ['A']},
            {'rooms': 3, 'sources': {'room-area': 2}, 'warnings': ['B']})
        self.assertEqual(5, result['rooms'])
        self.assertEqual(3, result['sources']['room-area'])
        self.assertEqual(['A', 'B'], result['warnings'])

    def test_formula_scan_covers_seven_classic_excel_errors(self):
        self.assertEqual({
            '#NULL!', '#DIV/0!', '#VALUE!', '#REF!',
            '#NAME?', '#NUM!', '#N/A',
        }, set(publish.FORMULA_ERROR_TOKENS))

    def test_formula_scan_uses_matrices_and_excel_error_wrappers(self):
        workbook = FakeWorkbook([FakeSheet(
            'Sheet1',
            [['=1/0', '=#REF!'], ['plain', '=2+2']],
            [[FakeExcelError(0x800A07D7), FakeExcelError(0x800A07E7)],
             ['plain', 4]],
        )])
        self.assertEqual({
            'Sheet1!$A$1|#DIV/0!',
            'Sheet1!$B$1|#REF!',
        }, publish._scan_workbook_formula_errors(workbook))

    def test_formula_scan_does_not_use_findnext_or_force_release_rcws(self):
        with open(MODULE_PATH, 'r', encoding='utf-8') as stream:
            text = stream.read()
        scan_text = text[text.index(
            'def _scan_workbook_formula_errors'):text.index(
            'def _merge_area_bounds')]
        release_text = text[text.index('def _release_com'):text.index(
            'def _worksheet_by_name')]
        self.assertNotIn('.FindNext(', scan_text)
        self.assertNotIn('.Find(', scan_text)
        self.assertIn('Marshal.ReleaseComObject(value)', release_text)
        self.assertNotIn(
            'Marshal.FinalReleaseComObject(value)', release_text)

    def test_shared_excel_font_scheme_matches_desktop_roles(self):
        self.assertEqual('標楷體', styles.FONT_NAME)
        self.assertIn('<font><sz val="9"/', styles.FONTS_XML)
        self.assertIn('<font><sz val="12"/', styles.FONTS_XML)
        self.assertIn('<font><sz val="24"/', styles.FONTS_XML)
        self.assertIn('<font><sz val="14"/', styles.FONTS_XML)
        self.assertIn('<font><b/><sz val="9"/', styles.FONTS_XML)
        self.assertIn('<borders count="1">', styles.BORDERS_XML)

    def test_managed_sheet_mapping_targets_the_existing_main_sheet(self):
        self.assertEqual(
            [('地坪數量計算', '地坪'), ('高度檢核', '高度檢核')],
            publish._managed_sheet_mappings([
                ('地坪數量計算', '地坪'), '高度檢核']))

    def test_subtotal_reference_rebases_row_and_material_column(self):
        formula, changed, zeroed = publish.rebase_summary_formula(
            '=ROUND(地坪!$D$312,0)', '地坪', 312, 305, {4: 7})
        self.assertEqual('=ROUND(地坪!$G$305,0)', formula)
        self.assertEqual(1, changed)
        self.assertEqual(0, zeroed)

    def test_missing_material_column_becomes_zero_not_wrong_index(self):
        formula, changed, zeroed = publish.rebase_summary_formula(
            '=天花!K310', '天花', 310, 300, {11: None})
        self.assertEqual('=0', formula)
        self.assertEqual(1, changed)
        self.assertEqual(1, zeroed)

    def test_other_sheet_reference_is_untouched(self):
        formula, changed, zeroed = publish.rebase_summary_formula(
            '=其他面積!P18', '地坪', 312, 305, {4: 7})
        self.assertEqual('=其他面積!P18', formula)
        self.assertEqual(0, changed)
        self.assertEqual(0, zeroed)

    def test_summary_reference_contract_detects_valid_but_stale_rows(self):
        self.assertEqual(
            [('P', 311), ('Q', 312)],
            publish.summary_reference_rows(
                "=ROUND('內牆'!$P$311,0)+內牆!Q312",
                u'內牆'))

    def test_summary_sum_contract_requires_exact_dynamic_boundaries(self):
        self.assertIsNone(publish.summary_sum_formula_issue(
            '=SUM($D$8:D13)', 4, 8, 13))
        self.assertEqual(
            u'expected rows 8:14, found 8:13',
            publish.summary_sum_formula_issue(
                '=SUM(D8:D13)', 4, 8, 14))
        self.assertEqual(
            u'expected SUM to use its own column D',
            publish.summary_sum_formula_issue(
                '=SUM(E8:E14)', 4, 8, 14))

    def test_empty_summary_region_requires_literal_zero(self):
        self.assertIsNone(publish.summary_sum_formula_issue(
            '=0', 4, 8, 7))
        self.assertEqual(
            u'expected =0 for an empty data region',
            publish.summary_sum_formula_issue(
                '=SUM(D8:D8)', 4, 8, 7))

    def test_backup_path_is_timestamped_and_non_destructive(self):
        folder = os.path.join(ROOT, 'fixture')
        workbook = os.path.join(folder, 'main.xlsm')
        with mock.patch.object(publish.os.path, 'exists', return_value=False):
            first = publish.make_backup_path(workbook, '20260731_120000')
        self.assertEqual(
            os.path.join(
                folder, 'main_backup_20260731_120000.xlsm'), first)
        with mock.patch.object(
                publish.os.path, 'exists', side_effect=[True, False]):
            second = publish.make_backup_path(workbook, '20260731_120000')
        self.assertEqual(
            os.path.join(
                folder, 'main_backup_20260731_120000_2.xlsm'), second)

    def test_four_direct_buttons_use_shared_preflight_before_other_pickers(self):
        for button in DIRECT_BUTTONS:
            path = os.path.join(
                BUTTON_ROOT, button + '.pushbutton', 'script.py')
            with open(path, 'r', encoding='utf-8') as stream:
                text = stream.read()
            self.assertEqual(1, text.count(
                'takeoff_entry.choose_options'), button)
            main_text = text[text.index('def main():'):]
            preflight = main_text.index('takeoff_entry.choose_options')
            material_picker = main_text.index('choose_material_family')
            save_picker = main_text.index('forms.save_file')
            self.assertLess(preflight, material_picker, button)
            self.assertLess(preflight, save_picker, button)
            self.assertIn(
                'allow_host=True, host_required=False', main_text)
            self.assertIn('takeoff_entry.iter_sources', text)
            self.assertIn('room_is_in_active_level_scope', text)
            self.assertIn(
                'takeoff_direct_publish.rekey_room_records', text)
            self.assertIn(
                'reload(takeoff_direct_publish)', text)

    def test_workbook_mode_branches_before_standalone_save(self):
        for button in DIRECT_BUTTONS:
            path = os.path.join(
                BUTTON_ROOT, button + '.pushbutton', 'script.py')
            with open(path, 'r', encoding='utf-8') as stream:
                text = stream.read()
            main_text = text[text.index('def main():'):]
            self.assertLess(
                main_text.index('if workbook_path:'),
                main_text.index('forms.save_file'),
                button)
            self.assertIn('write_xlsx(temp_path', main_text)
            self.assertIn('publish_generated_workbook', main_text)

    def test_four_direct_buttons_map_to_real_main_workbook_sheets(self):
        expected = {
            'Baseboard': "(u'踢腳數量計算', u'踢腳')",
            'CeilingTakeoff': "(u'天花數量計算', u'天花')",
            'FloorTakeoff': "(u'地坪數量計算', u'地坪')",
            'InteriorWallPaint': "(u'內牆粉刷數量計算', u'內牆')",
        }
        for button, mapping in expected.items():
            path = os.path.join(
                BUTTON_ROOT, button + '.pushbutton', 'script.py')
            with open(path, 'r', encoding='utf-8') as stream:
                text = stream.read()
            self.assertIn(mapping, text, button)
            self.assertIn('summary_specs={', text, button)
            self.assertIn(
                'room_takeoff_sources_logic.room_number_sort_key',
                text, button)

    def test_publish_buttons_anchor_headers_by_label_not_row_number(self):
        for button in PUBLISH_BUTTONS:
            path = os.path.join(
                BUTTON_ROOT, button + '.pushbutton', 'script.py')
            with open(path, 'r', encoding='utf-8') as stream:
                text = stream.read()
            start = text.index('summary_specs={')
            publish_call = text[start:start + 500]
            self.assertIn("'header_label':", publish_call, button)
            self.assertIn("'data_header_label':", publish_call, button)
            self.assertNotIn("'header_row':", publish_call, button)

    def test_height_buttons_keep_evidence_inside_each_source_model(self):
        for button in ('CeilingTakeoff', 'InteriorWallPaint'):
            path = os.path.join(
                BUTTON_ROOT, button + '.pushbutton', 'script.py')
            with open(path, 'r', encoding='utf-8') as stream:
                text = stream.read()
            self.assertIn('doc = source_doc', text, button)
            self.assertIn(
                "'level-to-level-no-slab-thickness'", text, button)
            self.assertIn(
                u'同一來源模型的樓層到樓層高度', text, button)

    def test_publisher_preserves_existing_worksheet_identity(self):
        with open(MODULE_PATH, 'r', encoding='utf-8') as stream:
            text = stream.read()
        self.assertNotIn('old_sheet.Delete(', text)
        self.assertIn('_copy_sheet_contents(', text)
        self.assertIn('baseline_errors', text)
        self.assertIn('source_errors', text)
        self.assertIn('final_errors.difference(baseline_errors)', text)
        self.assertIn(
            'if failed and os.path.isfile(backup_path):', text)
        publish_text = text[text.index(
            'def publish_generated_workbook'):]
        self.assertLess(
            publish_text.index('_calculate_full(app)'),
            publish_text.index('baseline_errors ='))

    def test_missing_sheet_is_created_in_target_format_then_range_copied(self):
        with open(MODULE_PATH, 'r', encoding='utf-8') as stream:
            text = stream.read()
        publish_text = text[text.index(
            'def publish_generated_workbook'):]
        helper_text = text[text.index(
            'def _copy_generated_sheet_to_new_target'):text.index(
            'def _calculate_full')]
        self.assertNotIn('source_sheet.Copy(', publish_text)
        self.assertIn('target_sheets.Add(last_sheet)', publish_text)
        self.assertIn(
            '_copy_generated_sheet_to_new_target(', publish_text)
        self.assertIn('source_used.Copy(target_start)', helper_text)
        self.assertIn(
            'target_column.ColumnWidth = source_column.ColumnWidth',
            helper_text)
        self.assertIn(
            'target_row.RowHeight = source_row.RowHeight', helper_text)
        self.assertIn('_copy_sheet_contents(', helper_text)

    def test_publisher_keeps_target_layout_and_only_replaces_values(self):
        with open(MODULE_PATH, 'r', encoding='utf-8') as stream:
            text = stream.read()
        values_text = text[text.index('def _copy_sheet_values'):text.index(
            'def _copy_generated_row_fonts')]
        self.assertIn('_clear_values_preserving_merges', values_text)
        self.assertIn('target_used.ClearContents()', text)
        self.assertNotIn('target_used.Clear()', values_text)
        self.assertNotIn('target_used.UnMerge()', values_text)
        self.assertIn('target_font.Name = source_font.Name', text)
        self.assertIn('target_font.Size = source_font.Size', text)

    def test_publisher_applies_a_complete_thin_grid_to_each_report(self):
        with open(MODULE_PATH, 'r', encoding='utf-8') as stream:
            text = stream.read()
        border_text = text[text.index(
            'def _apply_generated_table_borders'):text.index(
            'def _copy_sheet_contents')]
        self.assertIn('borders.LineStyle = 1', border_text)
        self.assertIn('borders.Weight = 2', border_text)
        self.assertNotIn('borders.Item(', border_text)
        contents_text = text[text.index(
            'def _copy_sheet_contents'):text.index(
            'def _calculate_full')]
        self.assertIn('_apply_generated_table_borders(', contents_text)

    def test_all_formatted_buttons_use_the_shared_font_and_border_scheme(self):
        for button in ALL_FORMATTED_BUTTONS:
            path = os.path.join(
                BUTTON_ROOT, button + '.pushbutton', 'script.py')
            with open(path, 'r', encoding='utf-8') as stream:
                text = stream.read()
            self.assertIn('takeoff_excel_styles.FONTS_XML', text, button)
            self.assertIn('takeoff_excel_styles.BORDERS_XML', text, button)


if __name__ == '__main__':
    unittest.main()
