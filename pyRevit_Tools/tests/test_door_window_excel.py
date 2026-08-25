# -*- coding: utf-8 -*-
import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import door_window_excel_logic as logic


def cell_rows(rows):
    """rows = [(row, label, unit, quantity)] -> sparse cell tuples."""
    cells = []
    for row, label, unit, quantity in rows:
        if label:
            cells.append((row, 3, label))
        if unit:
            cells.append((row, 5, unit))
        if quantity is not None:
            cells.append((row, 6, quantity))
    return cells


SHEET = cell_rows([
    (141, '金屬門窗工程', '', None),
    (142, 'D1-60x120cm(WxH)鋼板烤漆防火門(F60A)', '樘', 17),
    (143, 'D2-90x220cm(WxH)鋼板烤漆防火門(F60A)', '樘', 22),
    (175, 'W6-R=100cm固定圓形窗', '樘', 8),
    (176, '複層式金屬鋼浪板工程(以面積計算)', '', None),
    (177, '鍍鋁鋅鋼浪板F60A, (板片單元1mx10m)(白色#9285C)', 'M2', 15627),
    (188, '外牆鋁包板工程(以面積計算)', '', None),
    (189, '造型鋁包板th=3mm,表面PVDF', 'M2', 785),
])


class TypeKeyTests(unittest.TestCase):
    def test_revit_type_and_excel_label_share_a_key(self):
        self.assertEqual('d3-180x220cm', logic.type_key('D3-180x220 cm'))
        self.assertEqual(
            'd3-180x220cm',
            logic.type_key('D3-180x220cm(WxH)雙開鋼板烤漆防火門(F60A)'))
        self.assertEqual('sd10-1100x280cm',
                         logic.type_key('SD10-1100x280 cm'))
        self.assertEqual('d5a-120x220cm', logic.type_key('D5a-120x220 cm'))

    def test_item_without_wxh_still_resolves(self):
        """W6 has no (WxH); a bracket-based split would break it."""
        self.assertEqual('w6-r=100cm',
                         logic.type_key('W6-R=100cm固定圓形窗'))

    def test_case_and_fullwidth_are_normalized(self):
        self.assertEqual('d12-100x210cm',
                         logic.type_key('D12-100x210CM(WxH)SMC百葉門'))

    def test_type_without_cm_falls_back_to_leading_token(self):
        self.assertEqual('廁所門', logic.type_key('廁所門（60x200）'))

    def test_empty_input(self):
        self.assertEqual('', logic.type_key(''))
        self.assertEqual('', logic.type_key(None))


class SectionTests(unittest.TestCase):
    def test_bracketed_heading_ends_the_block(self):
        """複層式金屬鋼浪板工程(以面積計算) is a heading despite the suffix."""
        first, last = logic.find_section_rows(SHEET)
        self.assertEqual(142, first)
        self.assertEqual(175, last)

    def test_heading_needs_an_empty_unit(self):
        self.assertTrue(logic.is_section_heading('金屬門窗工程', ''))
        self.assertTrue(
            logic.is_section_heading('外牆鋁包板工程(以面積計算)', ''))
        # A priced item that happens to end with 工程 is not a heading.
        self.assertFalse(logic.is_section_heading('某某工程', '樘'))

    def test_items_exclude_the_next_section(self):
        first, last = logic.find_section_rows(SHEET)
        items = logic.parse_items(SHEET, first, last)
        keys = [item['key'] for item in items]
        self.assertEqual(['d1-60x120cm', 'd2-90x220cm', 'w6-r=100cm'], keys)

    def test_missing_section_raises(self):
        with self.assertRaises(ValueError):
            logic.find_section_rows(cell_rows([(1, '輕隔間工程', '', None)]))


class PlanTests(unittest.TestCase):
    def setUp(self):
        first, last = logic.find_section_rows(SHEET)
        self.items = logic.parse_items(SHEET, first, last)

    def test_updates_only_changed_rows(self):
        counts = {
            'd1-60x120cm': {'count': 17, 'names': ['D1-60x120 cm']},
            'd2-90x220cm': {'count': 25, 'names': ['D2-90x220 cm']},
            'w6-r=100cm': {'count': 8, 'names': ['W6-R=100cm']},
        }
        plan = logic.build_plan(self.items, counts)
        self.assertEqual(1, len(plan['updates']))
        update = plan['updates'][0]
        self.assertEqual(143, update['row'])
        self.assertEqual(22, update['old'])
        self.assertEqual(25, update['new'])
        self.assertEqual([], plan['unmatched_excel'])
        self.assertEqual([], plan['unmatched_revit'])

    def test_excel_item_without_revit_match_is_never_zeroed(self):
        counts = {'d1-60x120cm': {'count': 17, 'names': []}}
        plan = logic.build_plan(self.items, counts)
        rows = [item['row'] for item in plan['unmatched_excel']]
        self.assertEqual([143, 175], rows)
        self.assertEqual([], [u['row'] for u in plan['updates']])

    def test_revit_type_without_excel_row_is_reported(self):
        counts = {
            'd1-60x120cm': {'count': 17, 'names': []},
            'd2-90x220cm': {'count': 22, 'names': []},
            'w6-r=100cm': {'count': 8, 'names': []},
            '廁所門-60x200cm': {'count': 9, 'names': ['廁所門-60x200 cm']},
        }
        plan = logic.build_plan(self.items, counts)
        self.assertEqual(1, len(plan['unmatched_revit']))
        self.assertEqual('廁所門-60x200cm', plan['unmatched_revit'][0]['key'])
        self.assertEqual(9, plan['unmatched_revit'][0]['count'])

    def test_duplicate_excel_keys_block_that_row(self):
        items = logic.parse_items(cell_rows([
            (10, 'D1-60x120cm(WxH)甲式', '樘', 1),
            (11, 'D1-60x120cm(WxH)乙式', '樘', 2),
        ]), 10, 11)
        plan = logic.build_plan(
            items, {'d1-60x120cm': {'count': 5, 'names': []}})
        self.assertEqual([], plan['updates'])
        self.assertEqual(2, len(plan['blocked']))

    def test_blank_quantity_counts_as_an_update(self):
        items = logic.parse_items(cell_rows([
            (10, 'D1-60x120cm(WxH)鋼門', '樘', None)]), 10, 10)
        plan = logic.build_plan(
            items, {'d1-60x120cm': {'count': 3, 'names': []}})
        self.assertEqual(1, len(plan['updates']))
        self.assertIsNone(plan['updates'][0]['old'])


class LevelKeyTests(unittest.TestCase):
    def test_level_identity_includes_the_source_model(self):
        """B-1F in the host and D-1F in a link must never collide."""
        host = logic.level_key(logic.HOST_SOURCE, 5877)
        link = logic.level_key(logic.link_source_key(4242), 5877)
        self.assertEqual('host:5877', host)
        self.assertEqual('link:4242:5877', link)
        self.assertNotEqual(host, link)

    def test_empty_selection_means_every_source_is_in_scope(self):
        for empty in (None, [], set()):
            self.assertTrue(
                logic.source_has_selection(logic.HOST_SOURCE, empty))
            self.assertTrue(
                logic.source_has_selection('link:1', empty))

    def test_source_is_skipped_when_only_another_model_is_selected(self):
        selected = [logic.level_key(logic.link_source_key(7), 100)]
        self.assertFalse(
            logic.source_has_selection(logic.HOST_SOURCE, selected))
        self.assertTrue(logic.source_has_selection('link:7', selected))
        self.assertFalse(logic.source_has_selection('link:70', selected))

    def test_prefix_match_does_not_leak_between_similar_link_ids(self):
        """link:7 must not match link:70's keys."""
        selected = [logic.level_key(logic.link_source_key(70), 3)]
        self.assertFalse(logic.source_has_selection('link:7', selected))


def audit_row(model, level, key, count, name=''):
    return {'model': model, 'level': level, 'key': key, 'name': name,
            'count': count, 'updated': '2026-07-28'}


class AuditLedgerTests(unittest.TestCase):
    """The ledger is what makes partial-source runs accumulate correctly."""

    def test_rerunning_one_source_replaces_only_its_own_rows(self):
        existing = [
            audit_row('主模型', 'B-1F', 'd2-90x220cm', 10),
            audit_row('鮮食中心', 'C-B1F', 'd2-90x220cm', 6),
        ]
        run = [audit_row('鮮食中心', 'C-B1F', 'd2-90x220cm', 8)]
        merged = logic.replace_audit_rows(
            existing, run, {('鮮食中心', 'C-B1F')})
        totals = logic.aggregate_audit(merged)
        # 10 (host, untouched) + 8 (rerun replaced the old 6)
        self.assertEqual(18, totals['d2-90x220cm']['count'])
        self.assertEqual(2, len(merged))

    def test_sources_accumulate_rather_than_overwrite(self):
        existing = [audit_row('主模型', 'B-1F', 'd2-90x220cm', 10)]
        run = [audit_row('鮮食中心', 'C-B1F', 'd2-90x220cm', 6)]
        merged = logic.replace_audit_rows(
            existing, run, {('鮮食中心', 'C-B1F')})
        self.assertEqual(16,
                         logic.aggregate_audit(merged)['d2-90x220cm']['count'])

    def test_whole_model_run_clears_that_models_per_level_rows(self):
        """Otherwise an earlier per-level run would be counted twice."""
        existing = [
            audit_row('鮮食中心', 'C-B1F', 'd2-90x220cm', 6),
            audit_row('鮮食中心', 'C-1F', 'd2-90x220cm', 4),
            audit_row('主模型', 'B-1F', 'd2-90x220cm', 10),
        ]
        run = [audit_row('鮮食中心', logic.ALL_LEVELS, 'd2-90x220cm', 12)]
        merged = logic.replace_audit_rows(
            existing, run, {('鮮食中心', logic.ALL_LEVELS)})
        totals = logic.aggregate_audit(merged)
        self.assertEqual(22, totals['d2-90x220cm']['count'])  # 10 + 12
        models = sorted(set(row['model'] for row in merged))
        self.assertEqual(['主模型', '鮮食中心'], models)
        self.assertEqual(2, len(merged))

    def test_other_models_are_never_touched(self):
        existing = [
            audit_row('A棟', 'L1', 'd1-60x120cm', 3),
            audit_row('B棟', 'L1', 'd1-60x120cm', 5),
        ]
        merged = logic.replace_audit_rows(
            existing, [audit_row('A棟', 'L1', 'd1-60x120cm', 9)],
            {('A棟', 'L1')})
        totals = logic.aggregate_audit(merged)
        self.assertEqual(14, totals['d1-60x120cm']['count'])

    def test_aggregate_tracks_contributing_sources(self):
        rows = [
            audit_row('主模型', 'B-1F', 'd2-90x220cm', 10, 'D2-90x220 cm'),
            audit_row('鮮食中心', 'C-B1F', 'd2-90x220cm', 6, 'D2-90x220 cm'),
        ]
        entry = logic.aggregate_audit(rows)['d2-90x220cm']
        self.assertEqual(16, entry['count'])
        self.assertEqual(['D2-90x220 cm'], entry['names'])
        self.assertEqual(2, len(entry['sources']))

    def test_audit_round_trips_through_sheet_values(self):
        rows = [audit_row('鮮食中心', 'C-B1F', 'd2-90x220cm', 6, 'D2-90x220 cm')]
        values = logic.audit_values(rows)
        self.assertEqual(list(logic.AUDIT_HEADERS), values[0])
        cells = []
        for r, row in enumerate(values, start=1):
            for c, value in enumerate(row, start=1):
                if value not in (None, ''):
                    cells.append((r, c, value))
        parsed = logic.parse_audit_rows(cells)
        self.assertEqual(1, len(parsed))
        self.assertEqual('鮮食中心', parsed[0]['model'])
        self.assertEqual('C-B1F', parsed[0]['level'])
        self.assertEqual(6, parsed[0]['count'])

    def test_empty_ledger_is_safe(self):
        self.assertEqual({}, logic.aggregate_audit([]))
        self.assertEqual([], logic.parse_audit_rows([]))
        self.assertEqual([], logic.replace_audit_rows(None, None, set()))


class SafetyTests(unittest.TestCase):
    def test_only_plain_numbers_may_be_overwritten(self):
        self.assertTrue(logic.is_safe_quantity_cell(''))
        self.assertTrue(logic.is_safe_quantity_cell('17'))
        self.assertFalse(logic.is_safe_quantity_cell('=ROUND(H177,0)'))
        self.assertFalse(logic.is_safe_quantity_cell('=其他面積!P77'))

    def test_updates_relocate_by_key_after_rows_move(self):
        updates = [{'row': 20, 'key': 'd1-60x120cm',
                    'name': 'D1', 'new': 8}]
        current = [{'row': 23, 'key': 'd1-60x120cm', 'name': 'D1'}]
        relocated = logic.relocate_safe_updates(updates, current, [])
        self.assertEqual(23, relocated[0]['row'])
        self.assertEqual(20, updates[0]['row'])

    def test_formula_added_after_preview_blocks_write(self):
        updates = [{'row': 20, 'key': 'd1-60x120cm',
                    'name': 'D1', 'new': 8}]
        current = [{'row': 23, 'key': 'd1-60x120cm', 'name': 'D1'}]
        with self.assertRaises(ValueError):
            logic.relocate_safe_updates(
                updates, current,
                [{'row': 23, 'name': 'D1', 'reason': 'formula'}])

    def test_summary_lists_both_mismatch_directions(self):
        first, last = logic.find_section_rows(SHEET)
        items = logic.parse_items(SHEET, first, last)
        plan = logic.build_plan(items, {
            'd1-60x120cm': {'count': 20, 'names': ['D1-60x120 cm']},
            'zz-1x1cm': {'count': 4, 'names': ['ZZ-1x1 cm']},
        })
        text = logic.plan_summary(plan, 24, len(items))
        self.assertIn('17 → 20', text)
        self.assertIn('Excel 有工項但 Revit 找不到', text)
        self.assertIn('Revit 有門窗但 Excel 沒有', text)
        self.assertIn('zz-1x1cm', text)


class StandaloneTests(unittest.TestCase):
    def test_tables_keep_source_identity_and_real_formulas(self):
        takeoff = {
            'sources': ['主模型：2 樘', '鮮食中心：3 樘'],
            'audit_rows': [
                audit_row('主模型', 'B1F', 'd1-60x120cm', 2, 'D1'),
                dict(
                    audit_row('鮮食中心', 'B1F', 'd1-60x120cm', 3, 'D1'),
                    source_key='link:77'),
            ],
        }
        takeoff['audit_rows'][0]['source_key'] = 'host'
        tables = logic.standalone_tables(takeoff)
        self.assertEqual('host', tables['detail_rows'][0][0])
        self.assertEqual('link:77', tables['detail_rows'][1][0])
        self.assertEqual(
            ['來源鍵', '來源模型', '樓層', '類型鍵', 'Revit 類型', '數量'],
            tables['detail_headers'])
        self.assertTrue(tables['formula_rows'][0][2].startswith('=SUMIF('))
        self.assertTrue(tables['formula_rows'][-1][2].startswith('=SUM('))


if __name__ == '__main__':
    unittest.main()
