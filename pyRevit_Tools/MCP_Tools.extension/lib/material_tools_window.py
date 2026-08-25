# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""One host window for the three pyRevit material workflows.

The feature controllers stay in their existing pushbutton scripts so their
tested Revit read/write contracts remain unchanged.  This host loads them as
modules, detaches each page from its private WPF shell, and keeps the page alive
inside one fixed three-tab window.  Pages are created lazily on first visit.
"""

import imp
import os

from pyrevit import forms, revit

from System.Windows import GridLength, Visibility
from System.Windows.Controls import Grid


LIB_DIR = os.path.dirname(os.path.abspath(__file__))
EXTENSION_DIR = os.path.dirname(LIB_DIR)
PANEL_DIR = os.path.join(
    EXTENSION_DIR, 'MCP_Macros.tab', 'Material.panel')
XAML_PATH = os.path.join(LIB_DIR, 'material_tools_window.xaml')

TAB_ORDER = ('reverse', 'batch', 'room')
FEATURES = {
    'reverse': {
        'module': '_revitmcp_material_reverse_ui',
        'folder': 'MaterialReverseLookup.pushbutton',
        'script': 'script.py',
        'xaml': 'MaterialReverseLookup.xaml',
        'window': 'MaterialReverseLookupWindow',
        'host': 'reverseHost'
    },
    'batch': {
        'module': '_revitmcp_material_batch_ui',
        'folder': 'MaterialBatchEditor.pushbutton',
        'script': 'script.py',
        'xaml': 'MaterialBatchEditor.xaml',
        'window': 'MaterialBatchEditorWindow',
        'host': 'batchHost'
    },
    'room': {
        'module': '_revitmcp_room_material_ui',
        'folder': 'RoomMaterialDetail.pushbutton',
        'script': 'script.py',
        'xaml': 'RoomMaterialDetail.xaml',
        'window': 'RoomMaterialDetailWindow',
        'host': 'roomHost'
    }
}


def _feature_path(feature, filename_key):
    return os.path.join(PANEL_DIR, feature['folder'], feature[filename_key])


def _load_feature_module(feature):
    return imp.load_source(
        feature['module'], _feature_path(feature, 'script'))


def _hide_embedded_header(content):
    """The shared shell owns the title; remove the former per-window banner."""
    try:
        if content.RowDefinitions.Count:
            content.RowDefinitions[0].Height = GridLength(0.0)
        for child in content.Children:
            try:
                if Grid.GetRow(child) == 0:
                    child.Visibility = Visibility.Collapsed
            except Exception:
                pass
    except Exception:
        pass


class MaterialToolsWindow(forms.WPFWindow):
    def __init__(self, doc, uidoc, initial_tab='reverse'):
        forms.WPFWindow.__init__(self, XAML_PATH)
        self.doc = doc
        self.uidoc = uidoc
        self._controllers = {}
        self.mainTabs.SelectionChanged += self._on_tab_changed
        self.Closed += self._on_closed
        try:
            selected_index = TAB_ORDER.index(initial_tab)
        except ValueError:
            selected_index = 0
        self.mainTabs.SelectedIndex = selected_index
        self._ensure_tab(TAB_ORDER[selected_index])

    def _make_controller(self, tab_key):
        feature = FEATURES[tab_key]
        module = _load_feature_module(feature)
        window_type = getattr(module, feature['window'])
        xaml_path = _feature_path(feature, 'xaml')
        if tab_key == 'batch':
            controller = window_type(xaml_path, self.doc)
        else:
            controller = window_type(xaml_path, self.doc, self.uidoc)
        controller._unified_host = self
        return controller

    def _ensure_tab(self, tab_key):
        if tab_key in self._controllers:
            return
        controller = self._make_controller(tab_key)
        content = controller.Content
        controller.Content = None
        _hide_embedded_header(content)
        host = getattr(self, FEATURES[tab_key]['host'])
        host.Content = content
        self._controllers[tab_key] = controller

    def _on_tab_changed(self, sender, args):
        try:
            original = args.OriginalSource
            if (original != self.mainTabs and
                    getattr(original, 'Name', u'') != u'mainTabs'):
                return
        except Exception:
            pass
        index = self.mainTabs.SelectedIndex
        if index >= 0 and index < len(TAB_ORDER):
            self._ensure_tab(TAB_ORDER[index])

    def _on_closed(self, sender, args):
        for controller in self._controllers.values():
            try:
                controller.Close()
            except Exception:
                pass
        self._controllers = {}


def show(initial_tab='reverse'):
    doc = revit.doc
    uidoc = revit.uidoc
    if doc is None or uidoc is None:
        forms.alert(
            u'請先開啟 Revit 專案文件，再執行材質管理。',
            title=u'材質管理', warn_icon=True)
        return
    window = MaterialToolsWindow(doc, uidoc, initial_tab=initial_tab)
    window.ShowDialog()
