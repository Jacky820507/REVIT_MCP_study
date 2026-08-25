# -*- coding: utf-8 -*-
import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import machine_room_threshold_logic as logic


class MachineRoomThresholdLogicTests(unittest.TestCase):
    def test_default_classification(self):
        for name in (
                '消防泵房', 'B101 排風機房', '水箱機房', '電氣室',
                '電信室', 'SERVER ROOM', 'AHU機房', '防災中心'):
            self.assertEqual(logic.INCLUDE, logic.classify_room(name), name)
        self.assertEqual(logic.REVIEW, logic.classify_room('一般機房'))
        self.assertEqual(logic.EXCLUDE, logic.classify_room('停車場'))

    def test_threshold_label_variants(self):
        self.assertTrue(logic.is_threshold_label('不鏽鋼門檻（機房）'))
        self.assertTrue(logic.is_threshold_label(' 不銹鋼 門檻(機房) '))
        self.assertFalse(logic.is_threshold_label('不鏽鋼門檻（廁所）'))

    def test_dynamic_room_header_and_target(self):
        header = logic.find_room_header([
            (5, 3, '編號'), (5, 4, '空間名稱'), (7, 3, 'B101')])
        self.assertEqual((5, 3, 4), header)
        target = logic.find_unique_target([
            ('其他長度', 19, 3, '不銹鋼門檻(機房)'),
            ('內牆', 5, 3, '編號')])
        self.assertEqual(('其他長度', 19, 3), target)

    def test_specific_room_name_header_wins_over_opening_name(self):
        header = logic.find_room_header([
            (5, 3, '編號'),
            (5, 4, '空間名稱'),
            (5, 11, '名稱'),
        ])
        self.assertEqual((5, 3, 4), header)

    def test_dynamic_input_columns_and_formula(self):
        cells = [
            (5, 3, '項次'), (5, 5, '數量'), (5, 6, '長度'),
            (19, 3, '不鏽鋼門檻(機房)'),
        ]
        self.assertEqual((5, 5, 6), logic.find_input_columns(cells, 19, 3))
        self.assertTrue(logic.formula_references_inputs('=$E19*$F19', 19, 5, 6))
        self.assertFalse(logic.formula_references_inputs('=F19', 19, 5, 6))

    def test_duplicate_labels_resolve_to_only_input_table(self):
        cells_by_sheet = {
            '其他長度': [
                (5, 3, '項次'), (5, 5, '數量'), (5, 6, '長度'),
                (19, 3, '不銹鋼門檻(機房)'),
            ],
            '小計': [(93, 3, '不銹鋼門檻(機房)')],
            '更新工項': [(115, 2, '不銹鋼門檻(機房)')],
        }
        targets = [
            ('其他長度', 19, 3, '不銹鋼門檻(機房)'),
            ('小計', 93, 3, '不銹鋼門檻(機房)'),
            ('更新工項', 115, 2, '不銹鋼門檻(機房)'),
        ]
        self.assertEqual(
            ('其他長度', 19, 3, 5, 5, 6),
            logic.find_unique_input_target(cells_by_sheet, targets))

    def test_duplicate_input_targets_are_rejected(self):
        cells_by_sheet = {
            'A': [(1, 2, '數量'), (1, 3, '長度'),
                  (2, 1, '不鏽鋼門檻(機房)')],
            'B': [(4, 2, '數量'), (4, 3, '長度'),
                  (5, 1, '不銹鋼門檻(機房)')],
        }
        targets = [
            ('A', 2, 1, '不鏽鋼門檻(機房)'),
            ('B', 5, 1, '不銹鋼門檻(機房)'),
        ]
        with self.assertRaises(ValueError):
            logic.find_unique_input_target(cells_by_sheet, targets)

    def test_nearest_pair_wins_when_header_has_two_pairs(self):
        cells = [
            (5, 3, '工項'), (5, 5, '數量'), (5, 6, '長'),
            (5, 10, '數量'), (5, 11, '長'),
            (19, 3, '不銹鋼門檻(機房)'),
        ]
        self.assertEqual((5, 5, 6), logic.find_input_columns(
            cells, 19, 3))

    def test_safe_existing_formula_and_auditable_sum(self):
        self.assertTrue(logic.is_safe_length_formula('=0.9+1.8+1.2'))
        self.assertTrue(logic.is_safe_length_formula('=SUM(0.9,1.8,1.2)'))
        self.assertTrue(logic.is_safe_length_formula('=SUM(0.9;1.8)'))
        self.assertTrue(logic.is_safe_length_formula('=12*0.9+7*1.8'))
        self.assertFalse(logic.is_safe_length_formula('=E19*F19'))
        self.assertFalse(logic.is_safe_length_formula('=ROUND(1.2,2)'))
        self.assertEqual('=0.9+1.2', logic.build_length_formula([0.9, 1.2]))
        self.assertEqual('=0', logic.build_length_formula([]))

    def test_addition_chain_is_preferred_over_sum(self):
        """.xls caps functions at 30 args, so SUM() is never written."""
        widths = [0.9] * 45
        formula = logic.build_length_formula(widths)
        self.assertTrue(formula.startswith('=0.9+0.9'))
        self.assertNotIn('SUM', formula)
        self.assertEqual(45, formula.count('0.9'))
        # Whatever is written must be overwritable on the next run.
        self.assertTrue(logic.is_safe_length_formula(formula))

    def test_grouped_fallback_when_chain_is_too_long(self):
        widths = [0.9] * 120 + [1.8] * 80
        chain = logic.build_addition_chain(widths)
        self.assertGreater(len(chain), logic.XLS_FORMULA_BUDGET)
        formula = logic.build_length_formula(widths)
        self.assertEqual('=120*0.9+80*1.8', formula)
        self.assertTrue(logic.is_safe_length_formula(formula))
        self.assertLessEqual(len(formula), logic.XLS_FORMULA_BUDGET)

    def test_grouped_fallback_preserves_the_total(self):
        widths = [0.9] * 100 + [1.2] * 60 + [1.8] * 40
        formula = logic.build_length_formula(widths)
        terms = [term.split('*') for term in formula[1:].split('+')]
        rebuilt = sum(float(count) * float(width) for count, width in terms)
        self.assertAlmostEqual(sum(widths), rebuilt, places=6)

    def test_xlsx_budget_keeps_the_per_door_chain(self):
        widths = [0.9] * 200
        chain = logic.build_length_formula(widths, logic.XLSX_FORMULA_BUDGET)
        self.assertEqual(200, chain.count('0.9'))

    def test_duplicate_target_and_ambiguous_header_are_rejected(self):
        with self.assertRaises(ValueError):
            logic.find_unique_target([
                ('A', 1, 1, '不鏽鋼門檻(機房)'),
                ('B', 2, 2, '不銹鋼門檻(機房)')])
        with self.assertRaises(ValueError):
            logic.find_room_header([
                (1, 1, '房號'), (1, 2, '房名'),
                (5, 1, '編號'), (5, 2, '空間名稱')])

    def test_opening_index_carries_room_forward(self):
        """Only a room's first row repeats 編號/空間名稱."""
        cells = [
            (5, 3, '編號'), (5, 4, '空間名稱'), (5, 11, '名稱'), (5, 13, '寬'),
            (6, 3, 'B101'), (6, 4, '排風機房'), (6, 13, 0.9),
            (7, 3, 'B107'), (7, 4, '梯廳'), (7, 13, 1.8),
            (8, 13, 1.2),
            (9, 3, 'B112'), (9, 4, '排氣機房'), (9, 13, 0.9),
            (10, 13, ''),
        ]
        self.assertEqual((5, 3, 4), logic.find_room_header(cells))
        self.assertEqual(13, logic.find_opening_width_column(cells, 5, 4))
        openings = logic.index_openings(cells, 5, 3, 4, 13)
        self.assertEqual(
            [(6, 'B101', '排風機房', 0.9),
             (7, 'B107', '梯廳', 1.8),
             (8, 'B107', '梯廳', 1.2),
             (9, 'B112', '排氣機房', 0.9)], openings)

        rows, total, matched = logic.select_opening_rows(
            openings, [{'number': 'B101', 'name': '排風機房'},
                       {'number': 'B112', 'name': '排氣機房'}])
        self.assertEqual([6, 9], rows)
        self.assertAlmostEqual(1.8, total)
        missing = logic.unmatched_rooms(
            [{'number': 'B999', 'name': '電氣室'}], matched)
        self.assertEqual(1, len(missing))

    def test_reference_formula_collapses_runs_and_round_trips(self):
        formula = logic.build_reference_formula(
            '內牆', 'M', [16, 17, 18, 19, 20, 30, 33, 67])
        self.assertEqual(
            '=SUM(內牆!M16:M20)+內牆!M30+內牆!M33+內牆!M67', formula)
        # Must stay overwritable, or the next run refuses its own output.
        self.assertTrue(logic.is_safe_length_formula(formula))
        sheet, column, rows = logic.is_single_column_reference_formula(formula)
        self.assertEqual('內牆', sheet)
        self.assertEqual('M', column)
        self.assertEqual([16, 17, 18, 19, 20, 30, 33, 67], rows)

    def test_reference_guard_still_protects_unknown_formulas(self):
        for formula in ('=內牆!M16+內牆!N17',      # two columns
                        '=內牆!M16+踢腳!M17',      # two sheets
                        '=SUM(內牆!M16:M484)-F19',  # subtraction
                        '=E19*F19'):
            self.assertIsNone(
                logic.is_single_column_reference_formula(formula), formula)
            self.assertFalse(logic.is_safe_length_formula(formula), formula)

    def test_reference_formula_avoids_the_30_argument_trap(self):
        """One SUM per run, joined by +, never one SUM holding every run."""
        rows = list(range(1, 200, 2))  # 100 non-consecutive rows
        formula = logic.build_reference_formula(
            '內牆', 'M', rows, max_chars=100000)
        self.assertNotIn(',', formula)
        self.assertEqual(100, formula.count('內牆!M'))

    def test_sheet_name_quoted_only_when_needed(self):
        self.assertEqual('內牆', logic.sheet_reference('內牆'))
        self.assertEqual("'內 牆'", logic.sheet_reference('內 牆'))
        self.assertIn("'", logic.build_reference_formula('其他 長度', 'M', [5]))

    def test_room_match_prefers_number_and_name(self):
        selected = [{'number': 'B101', 'name': '排風機房'}]
        self.assertTrue(logic.room_matches(selected, 'B101', '排風機房'))
        self.assertFalse(logic.room_matches(selected, 'B102', '排風機房'))
        self.assertTrue(logic.room_matches(
            [{'number': '', 'name': '排風機房'}], '', '排風機房'))

    def test_element_id_dedup_width_sum_and_blocking(self):
        rows = [
            {'element_id': 10, 'from_name': '停車場', 'to_name': '電氣室',
             'included': True, 'width_m': 0.9},
            {'element_id': 10, 'from_name': '停車場', 'to_name': '電氣室',
             'included': True, 'width_m': 0.9},
            {'element_id': 11, 'from_name': '排風機房', 'to_name': '走廊',
             'included': True, 'width_m': 1.2},
        ]
        summary = logic.summarize_doors(rows)
        self.assertEqual(2, len(summary['doors']))
        self.assertAlmostEqual(2.1, summary['total_m'])
        self.assertFalse(logic.write_is_blocked([], summary))

        blocked = logic.summarize_doors([
            {'element_id': 13, 'from_name': '機房', 'to_name': '走廊',
             'included': True, 'width_m': None},
        ])
        self.assertEqual(1, len(blocked['blockers']))
        self.assertTrue(logic.write_is_blocked([], blocked))

        empty = logic.summarize_doors([])
        self.assertEqual(0.0, empty['total_m'])
        self.assertIsInstance(empty['total_m'], float)

    def test_unrelated_doors_never_block(self):
        """A door with no room association must not block a machine room."""
        summary = logic.summarize_doors([
            {'element_id': 12, 'from_name': '', 'to_name': '',
             'included': False, 'width_m': None},
            {'element_id': 14, 'from_name': '走廊', 'to_name': '樓梯',
             'included': False, 'width_m': 0.8},
            {'element_id': 15, 'from_name': '電氣室', 'to_name': '走廊',
             'included': True, 'width_m': 0.9},
        ])
        self.assertEqual([], summary['blockers'])
        self.assertEqual(1, len(summary['doors']))
        self.assertAlmostEqual(0.9, summary['total_m'])

    def test_blocker_message_locates_the_door(self):
        summary = logic.summarize_doors([
            {'element_id': 13, 'from_number': 'B101', 'from_name': '排風機房',
             'to_number': '', 'to_name': '', 'included': True,
             'width_m': None},
        ])
        message = summary['blockers'][0]
        self.assertIn('13', message)
        self.assertIn('B101', message)
        self.assertIn('排風機房', message)
        self.assertIn('(無房間)', message)

    def test_ascii_keywords_need_a_latin_word_boundary(self):
        for name in ('UPS室', 'MDF機房', 'AHU-1', '1F AHU'):
            self.assertEqual(logic.INCLUDE, logic.classify_room(name), name)
        for name in ('GROUPS', 'MAUSOLEUM', 'SERVERY'):
            self.assertEqual(logic.EXCLUDE, logic.classify_room(name), name)
        # CJK keywords keep plain substring matching.
        self.assertEqual(logic.INCLUDE, logic.classify_room('地下消防泵房區'))

    def test_room_filter_matches_number_name_and_source(self):
        room = {'number': 'B101', 'name': '排風機房',
                'classification': logic.INCLUDE}
        self.assertTrue(logic.room_matches_query(room, ''))
        self.assertTrue(logic.room_matches_query(room, 'b101'))
        self.assertTrue(logic.room_matches_query(room, '機房'))
        self.assertFalse(logic.room_matches_query(room, 'e'))
        self.assertFalse(logic.room_matches_query(room, '廁所'))
        linked = dict(room, source_key='link:11128732',
                      source_label='U-PARK-AR-鮮食中心.rvt')
        self.assertTrue(logic.room_matches_query(linked, '鮮食'))
        self.assertFalse(logic.room_matches_query(room, '鮮食'))

    def test_classification_counts(self):
        counts = logic.classification_counts([
            {'classification': logic.INCLUDE},
            {'classification': logic.INCLUDE},
            {'classification': logic.REVIEW},
            {'classification': logic.EXCLUDE},
        ])
        self.assertEqual(
            {logic.INCLUDE: 2, logic.REVIEW: 1, logic.EXCLUDE: 1}, counts)


class LinkedModelIdentityTests(unittest.TestCase):
    """L-015: room numbers collide across documents and mean different rooms."""

    LINK = logic.link_source_key(11128732)

    def test_composite_keys_separate_the_documents(self):
        self.assertNotEqual(logic.room_uid(logic.HOST_SOURCE, 123),
                            logic.room_uid(self.LINK, 123))
        self.assertNotEqual(logic.level_key(logic.HOST_SOURCE, 8),
                            logic.level_key(self.LINK, 8))

    def test_level_filter_is_per_source(self):
        """Filtering one link's level must not silence the host."""
        selected = [logic.level_key(self.LINK, 8)]
        self.assertIsNone(
            logic.level_filter_for_source(logic.HOST_SOURCE, selected))
        self.assertEqual(
            set(selected),
            logic.level_filter_for_source(self.LINK, selected))
        self.assertIsNone(logic.level_filter_for_source(self.LINK, []))

    def test_level_filter_does_not_leak_between_similar_link_ids(self):
        other = logic.link_source_key(111287)
        selected = [logic.level_key(self.LINK, 8)]
        self.assertIsNone(logic.level_filter_for_source(other, selected))

    def test_same_number_in_two_models_is_not_the_same_room(self):
        """F125 is 電氣室 in the host and 女廁 in the 鮮食中心 link."""
        selected = [{'number': 'F125', 'name': '電氣室'}]
        self.assertTrue(logic.room_matches(selected, 'F125', '電氣室'))
        self.assertFalse(logic.room_matches(selected, 'F125', '女廁'))

    def test_linked_rooms_and_doors_name_their_model(self):
        room = {'number': 'B139', 'name': '電氣室',
                'source_key': self.LINK, 'source_label': '鮮食中心'}
        self.assertEqual('鮮食中心｜B139 電氣室',
                         logic.room_source_display(room))
        host_room = {'number': 'F125', 'name': '電氣室',
                     'source_key': logic.HOST_SOURCE, 'source_label': '主模型'}
        self.assertEqual('F125 電氣室', logic.room_source_display(host_room))
        self.assertIn('鮮食中心', logic.describe_door({
            'element_id': 77, 'source_key': self.LINK,
            'source_label': '鮮食中心', 'from_number': 'B139',
            'from_name': '電氣室', 'to_number': '', 'to_name': ''}))

    def test_doors_dedup_per_document_not_per_element_id(self):
        """The same ElementId in two documents is two different doors."""
        summary = logic.summarize_doors([
            {'key': logic.room_uid(logic.HOST_SOURCE, 10),
             'element_id': 10, 'source_key': logic.HOST_SOURCE,
             'included': True, 'width_m': 0.9},
            {'key': logic.room_uid(self.LINK, 10), 'element_id': 10,
             'source_key': self.LINK, 'source_label': '鮮食中心',
             'included': True, 'width_m': 1.2},
            {'key': logic.room_uid(self.LINK, 10), 'element_id': 10,
             'source_key': self.LINK, 'source_label': '鮮食中心',
             'included': True, 'width_m': 1.2},
        ])
        self.assertEqual(2, len(summary['doors']))
        self.assertAlmostEqual(2.1, summary['total_m'])

    def test_linked_rooms_reach_the_shared_opening_index(self):
        """內牆 is project-wide, so a C棟 machine room owns rows there too."""
        openings = [
            (74, 'B139', '電氣室', 0.9),
            (80, 'B142', '發電機房', 1.2),
            (95, 'F125', '女廁', 0.8),
        ]
        selected = [
            {'number': 'B139', 'name': '電氣室', 'source_key': self.LINK},
            {'number': 'B142', 'name': '發電機房', 'source_key': self.LINK},
        ]
        rows, total, matched = logic.select_opening_rows(openings, selected)
        self.assertEqual([74, 80], rows)
        self.assertAlmostEqual(2.1, total)
        self.assertEqual([], logic.unmatched_rooms(selected, matched))


class StandaloneWorkbookTests(unittest.TestCase):
    def test_tables_keep_composite_source_and_formula_contract(self):
        link = logic.link_source_key(77)
        summary = logic.summarize_doors([
            {
                'key': logic.room_uid(logic.HOST_SOURCE, 10),
                'element_id': 10,
                'source_key': logic.HOST_SOURCE,
                'source_label': '主模型',
                'included': True,
                'width_m': 0.9,
            },
            {
                'key': logic.room_uid(link, 10),
                'element_id': 10,
                'source_key': link,
                'source_label': '鮮食中心',
                'included': True,
                'width_m': 1.2,
            },
        ])
        rooms = [
            {'source_key': logic.HOST_SOURCE},
            {'source_key': link},
        ]
        scopes = [
            {
                'source_key': logic.HOST_SOURCE,
                'label': '主模型',
                'levels': '全部樓層',
                'room_count': 8,
                'loaded': True,
            },
            {
                'source_key': link,
                'label': '鮮食中心',
                'levels': 'B1F',
                'room_count': 6,
                'loaded': True,
            },
        ]
        tables = logic.standalone_tables(rooms, summary, scopes)
        self.assertEqual('host', tables['detail_rows'][0][0])
        self.assertEqual('link:77', tables['detail_rows'][1][0])
        self.assertTrue(tables['formula_rows'][0][1].startswith('=COUNTA('))
        self.assertTrue(tables['formula_rows'][1][1].startswith('=SUM('))
        self.assertIn('link:77', tables['audit_rows'][1][2])


class BrokenReferenceRepairTests(unittest.TestCase):
    """空間表更新 deletes 內牆 rows, which invalidates row-indexed formulas."""

    BROKEN_F19 = ('=SUM(內牆!#REF!)+內牆!#REF!+SUM(內牆!#REF!)')
    BROKEN_F20 = '=SUM(內牆!#REF!)-F19'

    def test_broken_formula_is_detected(self):
        self.assertTrue(logic.is_broken_reference(self.BROKEN_F19))
        self.assertTrue(logic.is_broken_reference(self.BROKEN_F20))
        self.assertFalse(
            logic.is_broken_reference('=SUM(內牆!M16:M20)+內牆!M30'))

    def test_broken_formula_may_be_overwritten(self):
        """Refusing to overwrite #REF! would leave the sheet permanently broken."""
        self.assertTrue(logic.is_safe_length_formula(self.BROKEN_F19))
        # A healthy formula outside the whitelist is still protected.
        self.assertFalse(logic.is_safe_length_formula('=E19*F19'))

    def test_running_total_is_repaired_to_current_last_row(self):
        repaired = logic.rebuild_running_total(
            self.BROKEN_F20, '內牆', 'M', 16, 483, 'F19')
        self.assertEqual('=SUM(內牆!M16:M483)-F19', repaired)

    def test_only_the_exact_shape_is_repaired(self):
        for other in ('=SUM(內牆!#REF!)-F25',           # different target
                      '=SUM(踢腳!#REF!)-F19',           # different sheet
                      '=SUM(內牆!#REF!)+F19',           # not a subtraction
                      '=SUM(內牆!M16:M483)-F19'):       # already healthy
            self.assertIsNone(
                logic.rebuild_running_total(other, '內牆', 'M', 16, 483,
                                            'F19'), other)


if __name__ == '__main__':
    unittest.main()
