# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Shared preflight window and Revit source iterator for takeoff buttons.

``pyrevit`` and ``Autodesk.Revit`` are imported lazily.  This keeps the module
importable by ordinary CPython tests while preserving IronPython 2.7 runtime
compatibility inside pyRevit.
"""

import os

import takeoff_entry_logic as logic

try:
    text_type = unicode
except NameError:  # CPython 3 tests
    text_type = str


HOST_SOURCE = logic.HOST_SOURCE


def _text(value):
    if value is None:
        return ''
    if isinstance(value, text_type):
        return value
    return text_type(value)


def _element_id_value(element_or_id):
    value = getattr(element_or_id, 'Id', element_or_id)
    for attribute in ('Value', 'IntegerValue'):
        try:
            return int(getattr(value, attribute))
        except Exception:
            pass
    return int(value)


def _all_link_instances(doc):
    from Autodesk.Revit import DB
    return list(DB.FilteredElementCollector(doc)
                .OfClass(DB.RevitLinkInstance)
                .WhereElementIsNotElementType()
                .ToElements())


def _link_base_label(instance, link_doc):
    title = _text(getattr(link_doc, 'Title', '')).strip()
    if title:
        return title
    name = _text(getattr(instance, 'Name', '')).strip()
    return name or 'Revit link'


def _loaded_link_records(doc):
    records = []
    for instance in _all_link_instances(doc):
        link_doc = instance.GetLinkDocument()
        if link_doc is None:
            continue
        instance_id = _element_id_value(instance)
        records.append({
            'id': instance_id,
            'instance': instance,
            'doc': link_doc,
            'base_label': _link_base_label(instance, link_doc),
        })
    records.sort(key=lambda row: (
        row['base_label'].lower(), row['id']))
    labels = logic.disambiguate_labels(
        [(row['id'], row['base_label']) for row in records])
    for row, label in zip(records, labels):
        row['label'] = label
    return records


def _host_label(doc):
    title = _text(getattr(doc, 'Title', '')).strip()
    return 'Host - {}'.format(title) if title else 'Host model'


def _levels_in_document(source_doc):
    from Autodesk.Revit import DB
    levels = list(DB.FilteredElementCollector(source_doc)
                  .OfClass(DB.Level)
                  .WhereElementIsNotElementType()
                  .ToElements())
    levels.sort(key=lambda level: (
        float(getattr(level, 'Elevation', 0.0)),
        _text(getattr(level, 'Name', '')).lower(),
        _element_id_value(level)))
    return levels


def _level_records(doc, include_host, selected_link_ids):
    sources = []
    if include_host:
        sources.append((HOST_SOURCE, _host_label(doc), doc))
    wanted = set(int(value) for value in (selected_link_ids or []))
    for row in _loaded_link_records(doc):
        if row['id'] in wanted:
            sources.append((
                logic.link_source_key(row['id']), row['label'], row['doc']))

    result = []
    for source_key, source_label, source_doc in sources:
        for level in _levels_in_document(source_doc):
            level_id = _element_id_value(level)
            level_name = (_text(getattr(level, 'Name', '')).strip()
                          or 'Unnamed level')
            result.append({
                'key': logic.level_key(source_key, level_id),
                'level_id': level_id,
                'base_label': '{} - {}'.format(source_label, level_name),
            })
    # The ListBox binds plain strings and maps a selection back by label.
    # Disambiguation therefore must cover the entire list, not merely each
    # source.  The composite key is both unique and useful in the rare suffix.
    labels = logic.disambiguate_labels(
        [(row['key'], row['base_label']) for row in result])
    for row, label in zip(result, labels):
        row['label'] = label
    return result


def _make_window_class(forms):
    class TakeoffEntryWindow(forms.WPFWindow):
        def __init__(self, doc, title, allow_host, host_required):
            xaml_path = os.path.abspath(os.path.join(
                os.path.dirname(__file__), 'TakeoffEntry.xaml'))
            forms.WPFWindow.__init__(self, xaml_path)
            self.Title = title
            self.doc = doc
            self.result = None
            self.allow_host = bool(allow_host)
            self.host_required = bool(host_required)
            self.links = _loaded_link_records(doc)
            self.levels = []
            self.link_checks = []
            self.level_checks = []
            self.selected_link_ids = []
            self.selected_level_keys = []
            self._refreshing = False

            self.includeHostCheckBox.IsChecked = bool(allow_host)
            self.includeHostCheckBox.IsEnabled = bool(
                allow_host and not host_required)

            self.includeHostCheckBox.Click += self.host_changed
            self.browseButton.Click += self.browse_clicked
            self.clearButton.Click += self.clear_clicked
            self.continueButton.Click += self.continue_clicked
            self.cancelButton.Click += self.cancel_clicked
            self._refresh_link_checks()
            self._refresh_levels()
            self._sync_summary()

        def _include_host(self):
            return bool(self.includeHostCheckBox.IsChecked)

        def _new_check_box(self, label, checked, handler):
            from System.Windows import Thickness
            from System.Windows.Controls import CheckBox
            check_box = CheckBox()
            check_box.Content = label
            check_box.Margin = Thickness(4)
            check_box.IsChecked = bool(checked)
            check_box.Checked += handler
            check_box.Unchecked += handler
            return check_box

        def _refresh_link_checks(self):
            selected = set(self.selected_link_ids)
            self.link_checks = []
            self.linkList.Items.Clear()
            for row in self.links:
                check_box = self._new_check_box(
                    row['label'], row['id'] in selected,
                    self.links_changed)
                self.linkList.Items.Add(check_box)
                self.link_checks.append((row, check_box))

        def _sync_summary(self):
            source_count = (
                (1 if self._include_host() else 0)
                + len(self.selected_link_ids))
            self.sourceSummaryText.Text = (
                '已選 {} 個來源：目前模型{}，連結模型 {} 個。'.format(
                    source_count,
                    '已包含' if self._include_host() else '未包含',
                    len(self.selected_link_ids)))
            if self.selected_level_keys:
                self.levelSummaryText.Text = (
                    '已勾選 {} 個樓層；某個來源若沒有勾選樓層，'
                    '該來源仍採用全部樓層。'.format(
                        len(self.selected_level_keys)))
            else:
                self.levelSummaryText.Text = (
                    '未勾選樓層：每個已選來源都採用全部樓層。')

        def _refresh_levels(self):
            include_host = self._include_host()
            self.selected_level_keys = logic.prune_level_keys(
                self.selected_level_keys, include_host,
                self.selected_link_ids)
            levels = _level_records(
                self.doc, include_host, self.selected_link_ids)
            available = set(row['key'] for row in levels)
            self.selected_level_keys = logic.prune_level_keys(
                self.selected_level_keys, include_host,
                self.selected_link_ids, available)
            self.levels = levels

            self._refreshing = True
            try:
                selected = set(self.selected_level_keys)
                self.level_checks = []
                self.levelList.Items.Clear()
                for row in self.levels:
                    check_box = self._new_check_box(
                        row['label'], row['key'] in selected,
                        self.levels_changed)
                    self.levelList.Items.Add(check_box)
                    self.level_checks.append((row, check_box))
            finally:
                self._refreshing = False

        def host_changed(self, sender, args):
            if self.host_required:
                self.includeHostCheckBox.IsChecked = True
            self._refresh_levels()
            self._sync_summary()

        def links_changed(self, sender, args):
            if self._refreshing:
                return
            self.selected_link_ids = [
                row['id'] for row, check_box in self.link_checks
                if bool(check_box.IsChecked)]
            self._refresh_levels()
            self._sync_summary()

        def levels_changed(self, sender, args):
            if self._refreshing:
                return
            self.selected_level_keys = [
                row['key'] for row, check_box in self.level_checks
                if bool(check_box.IsChecked)]
            self._sync_summary()

        def browse_clicked(self, sender, args):
            path = forms.pick_file(
                files_filter=(
                    'Excel workbooks (*.xlsx;*.xlsm;*.xlsb;*.xls)|'
                    '*.xlsx;*.xlsm;*.xlsb;*.xls'))
            if path:
                self.pathBox.Text = path

        def clear_clicked(self, sender, args):
            self.pathBox.Text = ''

        def continue_clicked(self, sender, args):
            if self.host_required:
                self.includeHostCheckBox.IsChecked = True
            include_host = self._include_host()
            if not include_host and not self.selected_link_ids:
                forms.alert(
                    '請至少選擇目前模型或一個已載入的連結模型。',
                    title=self.Title)
                return
            path = _text(self.pathBox.Text).strip()
            if path and not os.path.isfile(path):
                forms.alert(
                    '選擇的主要 Excel 不存在：\n\n{}'
                    .format(path), title=self.Title)
                return
            available = set(row['key'] for row in self.levels)
            level_keys = logic.prune_level_keys(
                self.selected_level_keys, include_host,
                self.selected_link_ids, available)
            self.result = {
                'selected_link_ids': list(self.selected_link_ids),
                'selected_level_keys': level_keys,
                'workbook_path': path or None,
                'include_host': include_host,
            }
            self.Close()

        def cancel_clicked(self, sender, args):
            self.result = None
            self.Close()

    return TakeoffEntryWindow


def choose_options(doc, title, allow_host=True, host_required=True):
    """Show the shared preflight UI and return its selection or ``None``.

    Return keys:

    ``selected_link_ids``
        Loaded RevitLinkInstance ids as integers.
    ``selected_level_keys``
        Composite source/level keys.  No keys for a source means all levels.
    ``workbook_path``
        Optional existing main Excel workbook path.
    ``include_host``
        Whether the host document is a source.
    """
    if host_required and not allow_host:
        raise ValueError('host_required=True requires allow_host=True')
    if doc is None:
        raise ValueError('A Revit document is required')
    from pyrevit import forms
    window_class = _make_window_class(forms)
    window = window_class(
        doc, _text(title), bool(allow_host), bool(host_required))
    window.ShowDialog()
    return window.result


def iter_sources(doc, options):
    """Yield selected Revit source tuples.

    Each item is ``(source_key, source_label, source_doc,
    allowed_level_ids, link_instance_id)``.  ``allowed_level_ids`` is ``None``
    when that source has no selected level keys, meaning all levels.
    """
    if doc is None:
        raise ValueError('A Revit document is required')
    options = options or {}
    selected_level_keys = list(options.get('selected_level_keys') or [])
    include_host = bool(options.get('include_host', True))
    selected_ids = []
    seen = set()
    for raw_id in options.get('selected_link_ids') or []:
        link_id = int(raw_id)
        if link_id not in seen:
            selected_ids.append(link_id)
            seen.add(link_id)

    if not include_host and not selected_ids:
        raise ValueError('No Revit source was selected')

    if include_host:
        yield (
            HOST_SOURCE,
            _host_label(doc),
            doc,
            logic.level_ids_for_source(
                HOST_SOURCE, selected_level_keys),
            None,
        )

    instances = dict(
        (_element_id_value(instance), instance)
        for instance in _all_link_instances(doc))
    loaded_labels = dict(
        (row['id'], row['label']) for row in _loaded_link_records(doc))
    for link_id in selected_ids:
        instance = instances.get(link_id)
        if instance is None:
            raise Exception(
                'Selected Revit link instance was not found (id {}).'
                .format(link_id))
        link_doc = instance.GetLinkDocument()
        if link_doc is None:
            name = _link_base_label(instance, None)
            raise Exception(
                'Selected Revit link is unloaded: {} (id {}). '
                'Reload it and try again.'.format(name, link_id))
        source_key = logic.link_source_key(link_id)
        yield (
            source_key,
            loaded_labels.get(
                link_id, _link_base_label(instance, link_doc)),
            link_doc,
            logic.level_ids_for_source(
                source_key, selected_level_keys),
            link_id,
        )
