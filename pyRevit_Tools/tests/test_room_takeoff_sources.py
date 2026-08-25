# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys
import unittest
import math


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import room_takeoff_sources
import room_takeoff_sources_logic as logic


class _FakeTextParameter(object):
    def __init__(self, value):
        self.value = value

    def AsString(self):
        return self.value

    def AsValueString(self):
        return self.value


class _FakeBuiltInParameter(object):
    ROOM_NAME = object()


class _FakeDB(object):
    BuiltInParameter = _FakeBuiltInParameter


class _FakeLinkedRoom(object):
    @property
    def Name(self):
        raise AttributeError('linked room Name property unavailable')

    def get_Parameter(self, built_in):
        if built_in is _FakeBuiltInParameter.ROOM_NAME:
            return _FakeTextParameter(u'連結模型房名')
        return None


class RoomTakeoffSourceLogicTests(unittest.TestCase):

    def test_linked_room_name_prefers_builtin_room_name_parameter(self):
        self.assertEqual(
            u'連結模型房名',
            room_takeoff_sources._room_name(
                _FakeLinkedRoom(), _FakeDB))

    def test_composite_identity_prevents_host_link_and_link_collisions(self):
        self.assertEqual('host:42', logic.composite_room_id('host', 42))
        self.assertEqual(
            'link:7:42', logic.composite_room_id('link:7', 42))
        self.assertNotEqual(
            logic.composite_room_id('link:7', 42),
            logic.composite_room_id('link:70', 42))

    def test_level_filter_is_per_source_collector_input(self):
        self.assertTrue(logic.level_is_allowed(12, None))
        self.assertTrue(logic.level_is_allowed(12, set([12, 13])))
        self.assertFalse(logic.level_is_allowed(14, set([12, 13])))

    def test_duplicate_numbers_report_composite_owners(self):
        duplicates = logic.duplicate_room_numbers([
            {'Number': ' F101 ', 'CompositeId': 'host:1'},
            {'Number': 'f101', 'CompositeId': 'link:9:3'},
            {'Number': 'F102', 'CompositeId': 'host:2'},
        ])
        self.assertEqual(
            ['host:1', 'link:9:3'], duplicates['F101'])
        self.assertNotIn('F102', duplicates)

    def test_partial_scope_never_authorizes_removal(self):
        self.assertFalse(logic.destructive_space_sync_allowed({
            'include_host': True,
            'selected_link_ids': [],
            'selected_level_keys': ['host:12'],
        }))
        self.assertFalse(logic.destructive_space_sync_allowed({
            'include_host': True,
            'selected_link_ids': [77],
            'selected_level_keys': [],
        }))
        self.assertEqual(
            'out_of_scope', logic.unmatched_workbook_status(False))

    def test_full_legacy_host_scope_can_remove_but_link_managed_book_cannot(self):
        self.assertTrue(logic.destructive_space_sync_allowed({
            'include_host': True,
            'selected_link_ids': [],
            'selected_level_keys': [],
        }))
        self.assertTrue(logic.workbook_is_host_only([
            {'rid': ''}, {'rid': '123'}, {'rid': 'host:456'}]))
        self.assertFalse(logic.workbook_is_host_only([
            {'rid': 'host:123'}, {'rid': 'link:8:456'}]))

    def test_host_bare_id_migration_is_explicit(self):
        self.assertTrue(logic.is_host_identity_migration(
            '123', 'host:123'))
        self.assertFalse(logic.is_host_identity_migration(
            'link:8:123', 'link:8:123'))

    def test_link_only_same_room_label_never_rebinds_host_row(self):
        self.assertFalse(logic.exact_room_identity_matches(
            '123', 'link:8', 123, 'link:8:123'))
        self.assertFalse(logic.exact_room_identity_matches(
            'host:123', 'link:8', 123, 'link:8:123'))
        conflicts = logic.source_conflict_numbers(
            [{'number': ' F101 ', 'rid': 'host:123'}],
            [{'number': 'f101', 'rid': 'link:8:123'}])
        self.assertEqual(set(['F101']), conflicts)
        self.assertEqual(
            'out_of_scope', logic.unmatched_workbook_status(False))
        self.assertFalse(logic.space_status_is_pending('out_of_scope'))
        self.assertFalse(logic.space_status_is_pending('source_conflict'))

    def test_room_number_sort_key_keeps_b135_after_b134(self):
        ordered = sorted(
            ['B151', 'B135', 'B134', 'B9', 'B10'],
            key=logic.room_number_sort_key)
        self.assertEqual(
            ['B9', 'B10', 'B134', 'B135', 'B151'],
            ordered)

    def test_space_insert_anchors_include_preserved_out_of_scope_rows(self):
        b134 = {'row': 134, 'number': 'B134'}
        anchors = logic.space_insert_anchor_rows(
            [b134],
            [{'entry': b134, 'status': 'out_of_scope', 'number': 'B134'}])
        self.assertIs(b134, anchors['B134'])

    def test_space_row_moves_restore_split_prefix_block(self):
        b134 = {'row': 46, 'number': 'B134'}
        f101 = {'row': 47, 'number': 'F101'}
        r202 = {'row': 287, 'number': 'R202'}
        b135 = {'row': 288, 'number': 'B135'}
        b136 = {'row': 289, 'number': 'B136'}
        moves = logic.plan_space_row_moves(
            [b134, f101, r202, b135, b136],
            [b135, b136])
        self.assertEqual([b135, b136], [move['entry'] for move in moves])
        self.assertEqual([f101, f101], [move['before'] for move in moves])
        self.assertEqual([b134, b135], [move['anchor'] for move in moves])

    def test_space_row_moves_restore_same_prefix_inversion(self):
        f427 = {'row': 211, 'number': 'F427'}
        f428 = {'row': 205, 'number': 'F428'}
        f422 = {'row': 206, 'number': 'F422'}
        moves = logic.plan_space_row_moves(
            [f428, f422, f427],
            [f428, f422, f427])
        self.assertEqual([f422, f427], [move['entry'] for move in moves])
        self.assertEqual([f428, f428], [move['before'] for move in moves])

    def test_partial_host_scope_can_exactly_migrate_legacy_numeric_id(self):
        self.assertTrue(logic.exact_room_identity_matches(
            '123', 'host', 123, 'host:123'))
        self.assertTrue(logic.exact_room_identity_matches(
            '123.0', 'host', 123, 'host:123'))
        self.assertFalse(logic.exact_room_identity_matches(
            '123.5', 'host', 123, 'host:123'))

    def test_rotated_room_uses_oriented_boundary_dimensions(self):
        angle = math.radians(30.0)
        cosine = math.cos(angle)
        sine = math.sin(angle)
        points = []
        for x, y in ((0, 0), (4, 0), (4, 2), (0, 2)):
            points.append((
                x * cosine - y * sine,
                x * sine + y * cosine,
            ))
        length, width = logic.oriented_dimensions(points)
        self.assertAlmostEqual(4.0, length, places=6)
        self.assertAlmostEqual(2.0, width, places=6)

    def test_space_standalone_contains_real_summary_formulas(self):
        payload = room_takeoff_sources.space_standalone_tables([{
            'SourceKey': 'host',
            'SourceLabel': 'Host',
            'LinkInstanceId': None,
            'LocalElementId': 1,
            'CompositeId': 'host:1',
            'Level': '1F',
            'Number': 'F101',
            'Name': 'Office',
            'PerimeterM': 12.0,
            'AreaM2': 8.0,
            'BoundaryLoopCount': 1,
            'BoundarySegmentCount': 4,
            'BoundaryWarning': '',
        }])
        formulas = [row[2] for row in payload['formula_rows']]
        self.assertTrue(all(value.startswith('=') for value in formulas))
        self.assertIn("'數量明細'!I2:I2", formulas[1])


class SpaceScaffoldWiringContractTests(unittest.TestCase):

    def _read(self, *parts):
        path = os.path.abspath(os.path.join(
            os.path.dirname(__file__), '..', 'MCP_Tools.extension', *parts))
        with open(path, 'r', encoding='utf-8') as stream:
            return stream.read()

    def test_space_table_uses_shared_ui_and_no_legacy_file_or_sheet_picker(self):
        source = self._read(
            'MCP_Macros.tab', 'Takeoff.panel',
            'SpaceTableUpdate.pushbutton', 'script.py')
        self.assertIn('takeoff_entry.choose_options(', source)
        self.assertIn('if revit.doc is None:', source)
        self.assertIn("entry_options.get('workbook_path')", source)
        self.assertNotIn('forms.pick_file(', source)
        self.assertNotIn('forms.SelectFromList.show(', source)
        self.assertIn("TARGET_SPACE_SHEET = u'01空間表'", source)
        self.assertIn(
            'takeoff_direct_publish.make_backup_path(xls_path)', source)
        self.assertIn('plan_space_row_moves(', source)
        self.assertIn('def _move_space_row(', source)
        self.assertIn('def _repair_space_row_formats(', source)
        self.assertIn('target.PasteSpecial(XL_PASTE_FORMATS)', source)
        self.assertIn("ws.Columns(cols['rid']).Hidden = True", source)
        self.assertIn(
            "rid_value = ws.Cells(r, cols['rid']).Value2", source)
        self.assertIn(u'版面修復：', source)

    def test_space_table_reanchors_after_preview_before_writing(self):
        source = self._read(
            'MCP_Macros.tab', 'Takeoff.panel',
            'SpaceTableUpdate.pushbutton', 'script.py')
        self.assertIn('def _space_entries_signature(', source)
        self.assertIn('preview_entries_signature =', source)
        self.assertIn('current_header_row, current_cols', source)
        self.assertIn('current_entries, current_last_row', source)
        self.assertIn('內容自 dry-run 預覽後已改變', source)
        self.assertIn('items = _plan(\n            entries,', source)
        self.assertNotIn(
            "cols = {'number': 2, 'name': 3, 'perimeter': 4, 'area': 5}",
            source)

    def test_scaffold_wrapper_has_one_ui_and_routes_both_modes(self):
        source = self._read(
            'MCP_Macros.tab', 'Takeoff.panel',
            'ScaffoldRooms.pushbutton', 'script.py')
        self.assertEqual(1, source.count('takeoff_entry.choose_options('))
        self.assertIn('if revit.doc is None:', source)
        self.assertIn("'_TAKEOFF_OPTIONS': entry_options", source)
        self.assertIn(
            "scaffold_excel.run('general', options=entry_options)", source)
        self.assertIn('options=entry_options', source)

    def test_scaffold_standalone_keeps_formula_and_source_identity(self):
        source = self._read('lib', 'scaffold_excel.py')
        self.assertIn('def _scaffold_standalone_tables(', source)
        self.assertIn("u'來源Key'", source)
        self.assertIn("u'複合識別'", source)
        self.assertIn('ROUND(I{0}*L{0},3)', source)
        self.assertIn('ROUND(J{0}*K{0}*L{0},3)', source)
        self.assertIn('write_standard_workbook(', source)

    def test_scaffold_and_machine_room_use_shared_natural_room_order(self):
        scaffold = self._read('lib', 'scaffold_excel.py')
        machine = self._read('lib', 'machine_room_threshold_excel.py')
        machine_logic = self._read(
            'lib', 'machine_room_threshold_logic.py')
        self.assertIn(
            'room_takeoff_sources_logic.room_number_sort_key(',
            scaffold)
        self.assertIn(
            'room_order_logic.room_number_sort_key(', machine)
        self.assertIn(
            'room_order_logic.room_number_sort_key(', machine_logic)


if __name__ == '__main__':
    unittest.main()
