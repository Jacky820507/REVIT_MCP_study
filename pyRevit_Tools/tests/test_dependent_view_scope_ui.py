# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import io
import unittest
import xml.etree.ElementTree as ET


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
BUNDLE = os.path.join(
    ROOT, 'MCP_Tools.extension', 'MCP_Macros.tab', 'Visual.panel',
    'DependentViewCropScope.pushbutton')
XAML_PATH = os.path.join(BUNDLE, 'DependentViewCropScope.xaml')
SCRIPT_PATH = os.path.join(BUNDLE, 'script.py')
XAML_NAME = '{http://schemas.microsoft.com/winfx/2006/xaml}Name'


class DependentViewScopeUiTests(unittest.TestCase):
    def test_single_window_contains_required_controls(self):
        root = ET.parse(XAML_PATH).getroot()
        names = set(element.attrib.get(XAML_NAME) for element in root.iter())
        required = {
            'sourceModeRadio', 'gridModeRadio', 'sourceCombo',
            'sourceHintText',
            'targetFilterBox', 'targetList', 'selectAllButton',
            'clearTargetsButton', 'scopeBoxCombo', 'acknowledgeCheck',
            'statusText', 'executeButton', 'cancelButton',
        }
        self.assertTrue(required.issubset(names))
        resources = [element for element in root
                     if element.tag.endswith('Resources')]
        resources = resources[0] if resources else None
        self.assertIsNotNone(resources)

    def test_script_does_not_restore_yes_no_or_nested_list_picker(self):
        with io.open(SCRIPT_PATH, 'r', encoding='utf-8') as script_file:
            source = script_file.read()
        self.assertNotIn('yes=True', source)
        self.assertNotIn('forms.SelectFromList', source)
        self.assertNotIn('from System.Windows import Visibility', source)
        self.assertIn("'copySourceDependents': True", source)
        self.assertIn("'copyCropVisibility': False", source)


if __name__ == '__main__':
    unittest.main()
