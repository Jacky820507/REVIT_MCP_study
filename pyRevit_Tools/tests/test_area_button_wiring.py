# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import ast
import io
import os
import re
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
EXTENSION = os.path.join(ROOT, 'MCP_Tools.extension')
TAB = os.path.join(EXTENSION, 'MCP_Macros.tab')
MAKE_ICONS = os.path.join(ROOT, 'tools', 'make_icons.py')

AREA_BUTTON = os.path.join(
    TAB, 'Area.panel', 'AutoPlaceAreas.pushbutton')


def read(path):
    with io.open(path, 'r', encoding='utf-8') as stream:
        return stream.read()


class AreaButtonBundleTests(unittest.TestCase):
    def test_panel_and_button_bundles_exist(self):
        self.assertTrue(os.path.isfile(
            os.path.join(TAB, 'Area.panel', 'bundle.yaml')))
        self.assertTrue(os.path.isfile(
            os.path.join(AREA_BUTTON, 'bundle.yaml')))

    def test_bundle_has_title_and_tooltip(self):
        text = read(os.path.join(AREA_BUTTON, 'bundle.yaml'))
        self.assertIn('title:', text)
        self.assertIn('tooltip:', text)

    def test_bundle_carries_no_untested_availability_metadata(self):
        """L-061/L-063: unverified context makes the whole ribbon fail to load."""
        text = read(os.path.join(AREA_BUTTON, 'bundle.yaml'))
        self.assertNotIn('context:', text)
        self.assertNotIn('availability:', text)

    def test_script_declares_no_context(self):
        text = read(os.path.join(AREA_BUTTON, 'script.py'))
        self.assertNotIn('__context__', text)

    def test_script_parses(self):
        source = read(os.path.join(AREA_BUTTON, 'script.py'))
        ast.parse(source)

    def test_script_opens_no_transaction_itself(self):
        """Writes belong in the collection layer, which owns the rollback.

        Keeping ``DB.Transaction`` out of the button means there is exactly one
        place where an Area can be created, and that place always rolls back on
        failure. A Transaction opened here would bypass that guarantee.
        """
        text = read(os.path.join(AREA_BUTTON, 'script.py'))
        self.assertNotIn('DB.Transaction(', text)

    def test_sources_layer_always_rolls_back(self):
        text = read(os.path.join(EXTENSION, 'lib', 'area_scheme_sources.py'))
        self.assertIn('DB.Transaction(', text)
        self.assertIn('RollBack()', text)
        # The trial pass must roll back on every path, not just the happy one.
        self.assertIn('finally:', text)

    def test_icon_exists(self):
        self.assertTrue(os.path.isfile(
            os.path.join(AREA_BUTTON, 'icon.png')))


class IconRegistryTests(unittest.TestCase):
    """Guards the trap that has no runtime symptom.

    ``make_icons.build()`` resolves a button's colour with
    ``PANEL_COLORS.get(panel_of(path), INK)``. A panel name that is not in the
    dict does not raise — it silently produces a grey icon that collides with
    Structure's slate, and the only way to notice is to look at the contact
    sheet and know what you expected. Asserting it here turns that into a
    failing test, for every button, not just this one.
    """

    def _source(self):
        return read(MAKE_ICONS)

    def _panel_colors(self):
        source = self._source()
        block = re.search(r'PANEL_COLORS\s*=\s*\{(.*?)\}', source, re.S)
        self.assertIsNotNone(block, 'PANEL_COLORS not found')
        return set(re.findall(r"'([^']+)'\s*:", block.group(1)))

    def _button_paths(self):
        source = self._source()
        block = re.search(r'^BUTTONS\s*=\s*\[(.*?)^\]', source,
                          re.S | re.M)
        self.assertIsNotNone(block, 'BUTTONS not found')
        return re.findall(r"'(MCP_Macros\.tab/[^']+\.pushbutton)'",
                          block.group(1))

    def test_every_registered_panel_has_a_colour(self):
        colors = self._panel_colors()
        missing = []
        for path in self._button_paths():
            panel = path.split('/')[1].replace('.panel', '')
            if panel not in colors:
                missing.append(panel)
        self.assertEqual(
            [], sorted(set(missing)),
            u'這些 panel 不在 PANEL_COLORS，icon 會靜默變灰：{}'.format(
                sorted(set(missing))))

    def test_every_registered_button_folder_exists(self):
        missing = [path for path in self._button_paths()
                   if not os.path.isdir(
                       os.path.join(EXTENSION, *path.split('/')))]
        self.assertEqual([], missing)

    def test_every_button_folder_on_disk_is_registered(self):
        """A button with no icon entry ships as a text-only ribbon item."""
        registered = set(self._button_paths())
        on_disk = []
        for panel in sorted(os.listdir(TAB)):
            if not panel.endswith('.panel'):
                continue
            panel_dir = os.path.join(TAB, panel)
            for name in sorted(os.listdir(panel_dir)):
                if name.endswith('.pushbutton'):
                    on_disk.append(
                        'MCP_Macros.tab/{}/{}'.format(panel, name))
        self.assertEqual(
            [], sorted(set(on_disk) - registered),
            u'這些按鈕沒有登記在 make_icons.BUTTONS，不會有圖示')

    def test_area_button_is_registered(self):
        self.assertIn('MCP_Macros.tab/Area.panel/AutoPlaceAreas.pushbutton',
                      self._button_paths())


if __name__ == '__main__':
    unittest.main()
