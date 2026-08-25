# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import io
import os
import unittest
import xml.etree.ElementTree as ET


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
EXT_ROOT = os.path.join(ROOT, 'MCP_Tools.extension')
BUNDLE_ROOT = os.path.join(
    EXT_ROOT, 'MCP_Macros.tab', 'BIMGovernance.panel')
LIB_ROOT = os.path.join(EXT_ROOT, 'lib')
XAML_PATH = os.path.join(LIB_ROOT, 'agile_bim_rule_ui.xaml')
HELPER_PATH = os.path.join(LIB_ROOT, 'agile_bim_rule_ui.py')
XAML_NAME = '{http://schemas.microsoft.com/winfx/2006/xaml}Name'


class AgileRuleUiTests(unittest.TestCase):
    def test_single_window_contains_table_controls(self):
        root = ET.parse(XAML_PATH).getroot()
        names = set(element.attrib.get(XAML_NAME) for element in root.iter())
        required = {
            'sourceCombo', 'loadJsonButton', 'settingsPanel',
            'targetParameterBox', 'matchFieldCombo', 'targetScopePanel',
            'sourceParameterPanel', 'sourceParameterBox',
            'modeCombo', 'caseInsensitiveCheck', 'collapseWhitespaceCheck',
            'rulesPanel', 'addRuleButton', 'statusText', 'previewButton',
            'cancelButton',
        }
        self.assertTrue(required.issubset(names))

    def test_helper_uses_one_window_instead_of_nested_prompts(self):
        with io.open(HELPER_PATH, 'r', encoding='utf-8') as script_file:
            source = script_file.read()
        self.assertIn(
            'class AgileRuleSettingsWindow(forms.WPFWindow)', source)
        self.assertNotIn('forms.SelectFromList.show(', source)
        self.assertNotIn('forms.ask_for_string(', source)
        self.assertIn('loadJsonButton', source)
        self.assertIn('previewButton', source)

    def test_three_buttons_use_shared_ui_and_extra_options(self):
        scripts = (
            'RoomClassification.pushbutton',
            'DoorSpecifications.pushbutton',
            'WallPerformanceClassification.pushbutton',
        )
        for name in scripts:
            path = os.path.join(BUNDLE_ROOT, name, 'script.py')
            with io.open(path, 'r', encoding='utf-8') as script_file:
                source = script_file.read()
            self.assertIn('import agile_bim_rule_ui as rule_ui', source)
            self.assertIn('extra_option_label=', source)


if __name__ == '__main__':
    unittest.main()
