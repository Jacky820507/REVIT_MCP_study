# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import ast
import io
import os
import unittest
import xml.etree.ElementTree as ET


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
EXTENSION = os.path.join(ROOT, 'MCP_Tools.extension')
TAB = os.path.join(EXTENSION, 'MCP_Macros.tab')
PANEL = os.path.join(TAB, 'Material.panel')
LIB = os.path.join(EXTENSION, 'lib')

BUTTONS = (
    'MaterialReverseLookup.pushbutton',
    'MaterialBatchEditor.pushbutton',
    'RoomMaterialDetail.pushbutton',
)
UNIFIED_MODULE = os.path.join(LIB, 'material_tools_window.py')
UNIFIED_XAML = os.path.join(LIB, 'material_tools_window.xaml')


def read(path):
    with io.open(path, 'r', encoding='utf-8') as stream:
        return stream.read()


class MaterialButtonBundleTests(unittest.TestCase):
    def test_panel_and_complete_button_bundles_exist(self):
        self.assertTrue(os.path.isfile(os.path.join(PANEL, 'bundle.yaml')))
        for name in BUTTONS:
            folder = os.path.join(PANEL, name)
            self.assertTrue(os.path.isdir(folder), name)
            xaml_name = name.replace('.pushbutton', '.xaml')
            for filename in ('bundle.yaml', 'script.py', xaml_name, 'icon.png'):
                self.assertTrue(
                    os.path.isfile(os.path.join(folder, filename)),
                    '{} missing {}'.format(name, filename))

    def test_bundles_do_not_use_unverified_availability_metadata(self):
        for name in BUTTONS:
            text = read(os.path.join(PANEL, name, 'bundle.yaml'))
            self.assertIn('title:', text)
            self.assertIn('tooltip:', text)
            self.assertNotIn('context:', text)
            self.assertNotIn('availability:', text)

    def test_scripts_parse_and_declare_no_context(self):
        for name in BUTTONS:
            text = read(os.path.join(PANEL, name, 'script.py'))
            ast.parse(text)
            self.assertNotIn('__context__', text)
            self.assertIn('material_tools_logic', text)
            self.assertIn('material_tools_revit', text)

    def test_read_only_buttons_open_no_transaction(self):
        for name in ('MaterialReverseLookup.pushbutton',
                     'RoomMaterialDetail.pushbutton'):
            text = read(os.path.join(PANEL, name, 'script.py'))
            self.assertNotIn('DB.Transaction(', text)

    def test_batch_button_delegates_the_only_write(self):
        text = read(os.path.join(
            PANEL, 'MaterialBatchEditor.pushbutton', 'script.py'))
        self.assertIn('apply_material_patch', text)
        self.assertIn('collect_material_usage', text)
        self.assertIn('referencing_type_count', text)
        self.assertNotIn('DB.Transaction(', text)

    def test_room_button_does_not_call_side_effecting_room_surface_entry(self):
        text = read(os.path.join(
            PANEL, 'RoomMaterialDetail.pushbutton', 'script.py'))
        self.assertNotIn('GetRoomSurfaceAreas', text)
        self.assertNotIn('get_room_surface_areas', text)
        self.assertNotIn('includeFinishLayers', text)
        self.assertNotIn('mcp_bridge', text)

    def test_each_window_uses_a_sortable_data_grid(self):
        for name in BUTTONS:
            xaml_name = name.replace('.pushbutton', '.xaml')
            text = read(os.path.join(PANEL, name, xaml_name))
            self.assertIn('<DataGrid', text)
            self.assertNotIn('CanUserSortColumns="False"', text)
            self.assertTrue(
                'CanUserAddRows="False"' in text or
                'Property="CanUserAddRows" Value="False"' in text)
            self.assertTrue(
                'CanUserDeleteRows="False"' in text or
                'Property="CanUserDeleteRows" Value="False"' in text)

    def test_reverse_lookup_passes_the_selected_scope_to_type_scanning(self):
        text = read(os.path.join(
            PANEL, 'MaterialReverseLookup.pushbutton', 'script.py'))
        self.assertIn('elements, scope=scope', text)

    def test_room_quality_keeps_fallback_distinct_from_estimated(self):
        text = read(os.path.join(
            PANEL, 'RoomMaterialDetail.pushbutton', 'script.py'))
        fallback = text.index("if 'fallback_boundarysegments' in method.lower()")
        estimated = text.index("elif _bool_value(_get(record, 'estimated'")
        self.assertLess(fallback, estimated)

    def test_three_wrappers_open_the_same_window_on_the_matching_tab(self):
        expected = {
            'MaterialReverseLookup.pushbutton': "material_tools_window.show('reverse')",
            'MaterialBatchEditor.pushbutton': "material_tools_window.show('batch')",
            'RoomMaterialDetail.pushbutton': "material_tools_window.show('room')",
        }
        for name, call in expected.items():
            text = read(os.path.join(PANEL, name, 'script.py'))
            self.assertIn('import material_tools_window', text)
            self.assertIn(call, text)

    def test_unified_window_has_fixed_three_main_tabs(self):
        self.assertTrue(os.path.isfile(UNIFIED_MODULE))
        self.assertTrue(os.path.isfile(UNIFIED_XAML))
        module_text = read(UNIFIED_MODULE)
        ast.parse(module_text)
        self.assertNotIn('DB.Transaction(', module_text)
        self.assertIn("TAB_ORDER = ('reverse', 'batch', 'room')", module_text)
        self.assertIn('Pages are created lazily on first visit.', module_text)

        root = ET.parse(UNIFIED_XAML).getroot()
        namespace = {'w': 'http://schemas.microsoft.com/winfx/2006/xaml/presentation'}
        tabs = root.findall('.//w:TabControl[@x:Name="mainTabs"]/w:TabItem', {
            'w': namespace['w'],
            'x': 'http://schemas.microsoft.com/winfx/2006/xaml'
        })
        self.assertEqual(3, len(tabs))
        self.assertEqual(
            [u'材質反查', u'材質批次編輯', u'房間材質明細'],
            [item.attrib['Header'] for item in tabs])

    def test_material_lists_show_swatch_and_rgb_text(self):
        for name in ('MaterialReverseLookup.pushbutton',
                     'MaterialBatchEditor.pushbutton'):
            xaml_name = name.replace('.pushbutton', '.xaml')
            xaml_text = read(os.path.join(PANEL, name, xaml_name))
            script_text = read(os.path.join(PANEL, name, 'script.py'))
            self.assertIn('<DataGridTemplateColumn Header="顏色 RGB"', xaml_text)
            self.assertIn('Background="{Binding [RgbBrush]}"', xaml_text)
            self.assertIn('Text="{Binding [Rgb]}"', xaml_text)
            self.assertIn("('RgbBrush', String)", script_text)
            self.assertIn("row['RgbBrush'] = _rgb_brush(rgb_text)", script_text)

    def test_batch_rgb_inputs_have_live_swatches(self):
        folder = os.path.join(PANEL, 'MaterialBatchEditor.pushbutton')
        xaml_text = read(os.path.join(folder, 'MaterialBatchEditor.xaml'))
        script_text = read(os.path.join(folder, 'script.py'))
        for name in ('colorSwatch', 'surfaceColorSwatch', 'cutColorSwatch'):
            self.assertIn('x:Name="{}"'.format(name), xaml_text)
        for name in ('colorBox', 'surfaceColorBox', 'cutColorBox'):
            self.assertIn('self.{}.TextChanged +='.format(name), script_text)
        self.assertIn('invalid text keeps the last color', script_text)
        self.assertIn('_parse_rgb(text_box.Text, label)', script_text)

    def test_batch_direct_editor_loads_one_selected_material_and_has_apply_gate(self):
        folder = os.path.join(PANEL, 'MaterialBatchEditor.pushbutton')
        xaml_text = read(os.path.join(folder, 'MaterialBatchEditor.xaml'))
        script_text = read(os.path.join(folder, 'script.py'))
        for control in ('directNameBox', 'directClassBox',
                        'directCategoryBox', 'directDescriptionBox',
                        'directColorBox', 'directTransparencyBox',
                        'directShininessBox', 'directSmoothnessBox',
                        'directSurfaceColorBox', 'directCutColorBox',
                        'directApplyButton'):
            self.assertIn('x:Name="{}"'.format(control), xaml_text)
        for required in ('self._load_direct_material(material)',
                         'self.direct_snapshot = values.copy()',
                         'def _prepare_direct_preview',
                         'api.apply_material_patch(self.doc, [material], patch)',
                         '目前選取材質沒有任何變更'):
            self.assertIn(required, script_text)
        self.assertNotIn('DB.Transaction(', script_text)

    def test_batch_direct_editor_keeps_appearance_read_only(self):
        folder = os.path.join(PANEL, 'MaterialBatchEditor.pushbutton')
        xaml_text = read(os.path.join(folder, 'MaterialBatchEditor.xaml'))
        self.assertIn('渲染外觀資產（唯讀）', xaml_text)
        self.assertIn('x:Name="assetNameBox" IsReadOnly="True"', xaml_text)
        self.assertIn('外觀資產仍維持唯讀', xaml_text)


class MaterialAdapterSafetyTests(unittest.TestCase):
    def test_revit_adapter_owns_one_transaction_and_rollback(self):
        text = read(os.path.join(LIB, 'material_tools_revit.py'))
        self.assertEqual(1, text.count('DB.Transaction('))
        self.assertIn('RollBack()', text)
        self.assertIn('GetMaterialIds(False)', text)
        self.assertIn('GetMaterialIds(True)', text)
        self.assertNotIn('AppearanceAssetEditScope', text)
        self.assertNotIn('doc.Delete(', text)

    def test_room_collector_is_not_a_publisher(self):
        text = read(os.path.join(LIB, 'room_material_revit.py'))
        self.assertNotIn('DB.Transaction(', text)
        for forbidden in ('ViewSchedule.CreateSchedule',
                          'Export(',
                          'SetRoomSurfaceAreaParameters',
                          'GetMaterialArea('):
            self.assertNotIn(forbidden, text)
        for required in ('SpatialElementGeometryCalculator(',
                         'GetBoundingElementFace',
                         'GetPaintedMaterial',
                         'Fallback_BoundarySegments',
                         'skipped_room_ids',
                         u'保守不扣'):
            self.assertIn(required, text)

    def test_type_reference_counts_have_distinct_semantics(self):
        text = read(os.path.join(LIB, 'material_tools_revit.py'))
        self.assertIn("summary[u'type_reference_count'] = len(type_slot_keys", text)
        self.assertIn("summary[u'referencing_type_count'] = len(type_ids", text)
        self.assertIn("u'partial_failures': partial_failures", text)

    def test_material_adapter_reexports_room_collectors(self):
        text = read(os.path.join(LIB, 'material_tools_revit.py'))
        self.assertIn('room_material_revit', text)
        self.assertIn('collect_rooms', text)
        self.assertIn('collect_room_material_details', text)

    def test_logic_layer_has_no_revit_dependency(self):
        text = read(os.path.join(LIB, 'material_tools_logic.py'))
        self.assertNotIn('Autodesk.Revit', text)
        self.assertNotIn('from pyrevit', text)


if __name__ == '__main__':
    unittest.main()
