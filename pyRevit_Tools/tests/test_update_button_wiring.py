# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
EXTENSION = os.path.join(ROOT, 'MCP_Tools.extension')


BUTTONS = (
    (
        'DoorWindowExcel.pushbutton',
        'door_window_window.run(revit.doc, options)',
    ),
    (
        'MachineRoomThresholdExcel.pushbutton',
        'machine_room_threshold_excel.run(revit.doc, options)',
    ),
    (
        'ParkingExcel.pushbutton',
        'parking_excel.run(revit.doc, options)',
    ),
)


class UpdateButtonWiringTests(unittest.TestCase):
    def _script(self, bundle):
        path = os.path.join(
            EXTENSION, 'MCP_Macros.tab', 'Takeoff.panel',
            bundle, 'script.py')
        with open(path, 'r', encoding='utf-8') as stream:
            return stream.read()

    def _library(self, name):
        path = os.path.join(EXTENSION, 'lib', name)
        with open(path, 'r', encoding='utf-8') as stream:
            return stream.read()

    def test_all_three_entries_use_the_shared_optional_host_preflight(self):
        for bundle, unused_run_call in BUTTONS:
            source = self._script(bundle)
            self.assertIn('takeoff_entry.choose_options(', source, bundle)
            self.assertIn('host_required=False', source, bundle)

    def test_all_three_pass_the_preflight_options_to_their_runner(self):
        for bundle, run_call in BUTTONS:
            source = self._script(bundle)
            self.assertIn(run_call, source, bundle)

    def test_door_workbook_uses_only_the_subtotal_sheet(self):
        path = os.path.join(
            EXTENSION, 'lib', 'door_window_excel.py')
        with open(path, 'r', encoding='utf-8') as stream:
            source = stream.read()
        self.assertIn("SUBTOTAL_SHEET = u'小計'", source)
        inspection = source[source.index('def inspect_workbook('):]
        self.assertNotIn("DETAIL_SHEET = u'門窗表'", source)
        self.assertNotIn('_worksheet(workbook, DETAIL_SHEET)', inspection)
        update = source[source.index('def update_workbook('):]
        self.assertNotIn('_write_audit_sheet(workbook', update)
        window = self._library('door_window_window.py')
        self.assertNotIn('read_audit_rows(workbook)', window)
        self.assertNotIn('result[\'audit_rows\']', window)

    def test_legacy_scope_and_workbook_controls_are_locked(self):
        door = self._library('door_window_window.py')
        machine = self._library('machine_room_threshold_excel.py')
        parking = self._library('parking_excel.py')
        for name, source in (
                ('door', door), ('machine', machine), ('parking', parking)):
            self.assertIn('self.pathBox.IsReadOnly = True', source, name)
            self.assertIn('self.browseButton.IsEnabled = False', source, name)
            self.assertIn(
                'self.selectLinksButton.IsEnabled = False', source, name)
        self.assertIn(
            'self.selectLevelsButton.IsEnabled = False', door)
        self.assertIn(
            'self.selectLevelsButton.IsEnabled = False', machine)
        self.assertIn('self.levelCombo.IsEnabled = False', parking)


if __name__ == '__main__':
    unittest.main()
