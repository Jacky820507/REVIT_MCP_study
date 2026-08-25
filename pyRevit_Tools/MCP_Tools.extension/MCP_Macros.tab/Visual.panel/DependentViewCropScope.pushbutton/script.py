# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os

from Autodesk.Revit import DB
from pyrevit import forms, revit

import dependent_view_scope_logic as logic
import mcp_bridge as mcp


TITLE = u'從屬視圖裁切'
PLAN_VIEW_TYPES = ('FloorPlan', 'CeilingPlan', 'EngineeringPlan', 'AreaPlan')
MODE_SOURCE = 'source'
MODE_GRID = 'grid'


def _id_value(element_id):
    try:
        return int(element_id.Value)
    except Exception:
        try:
            return int(element_id.IntegerValue)
        except Exception:
            return -1


def _view_name(view):
    try:
        return view.Name or u''
    except Exception:
        return u''


def _view_label(view):
    name = _view_name(view)
    try:
        level = view.GenLevel
        if level is not None and level.Name and level.Name not in name:
            return u'{} [{}]'.format(name, level.Name)
    except Exception:
        pass
    return name


def _eligible_views(doc):
    views = []
    collector = DB.FilteredElementCollector(doc).OfClass(DB.View)
    for view in collector:
        try:
            if view.IsTemplate:
                continue
            if view.ViewType.ToString() not in PLAN_VIEW_TYPES:
                continue
            if view.GetPrimaryViewId() != DB.ElementId.InvalidElementId:
                continue
            if not view.CanViewBeDuplicated(DB.ViewDuplicateOption.AsDependent):
                continue
            views.append(view)
        except Exception:
            continue
    views.sort(key=lambda item: _view_name(item).lower())
    return views


def _dependent_count(view):
    try:
        return len(list(view.GetDependentViewIds()))
    except Exception:
        return 0


def _grid_names(result):
    grids = result.get('Grids') if isinstance(result, dict) else None
    names = []
    for grid in grids or []:
        name = grid.get('Name') if isinstance(grid, dict) else None
        if name and name not in names:
            names.append(name)
    names.sort(key=lambda value: value.lower())
    return names


def _scope_boxes(result):
    boxes = result.get('ScopeBoxes') if isinstance(result, dict) else None
    choices = []
    seen_names = set()
    for box in boxes or []:
        if not isinstance(box, dict):
            continue
        name = box.get('Name')
        element_id = box.get('ElementId')
        if name and element_id is not None and name not in seen_names:
            seen_names.add(name)
            choices.append((name, element_id))
    choices.sort(key=lambda item: item[0].lower())
    return choices


class DependentViewCropWindow(forms.WPFWindow):
    def __init__(self, views, active_view_id, grid_names, scope_boxes):
        xaml = os.path.join(os.path.dirname(__file__),
                            'DependentViewCropScope.xaml')
        forms.WPFWindow.__init__(self, xaml)
        self.result = None
        # Read the enum values from controls created by XAML.  Importing
        # System.Windows.Visibility at module load is unreliable in some
        # pyRevit IronPython hosts because PresentationFramework is loaded
        # only when WPFWindow is initialized.
        self._visible_value = self.sourcePanel.Visibility
        self._collapsed_value = self.gridPanel.Visibility
        self.views = list(views)
        self.grid_names = list(grid_names)
        self.scope_boxes = list(scope_boxes)
        self.view_counts = {}
        self.selected_target_ids = set()
        self.visible_target_views = []
        self.target_by_label = {}
        self.last_risk_ids = set()
        self.suppress_events = True

        for view in self.views:
            self.view_counts[_id_value(view.Id)] = _dependent_count(view)
            self.sourceCombo.Items.Add(self._source_label(view))

        source_index = 0
        for index, view in enumerate(self.views):
            if _id_value(view.Id) == active_view_id:
                source_index = index
                break
        self.sourceCombo.SelectedIndex = source_index

        self.scopeBoxCombo.Items.Add(u'不套用（使用各視圖 CropBox）')
        for name, unused_id in self.scope_boxes:
            self.scopeBoxCombo.Items.Add(name)
        self.scopeBoxCombo.SelectedIndex = 0

        if self.grid_names:
            shown = self.grid_names[:24]
            suffix = (u'，另有 {} 條'.format(len(self.grid_names) - len(shown))
                      if len(self.grid_names) > len(shown) else u'')
            self.gridHintText.Text = u'可用網格：{}{}'.format(
                u'、'.join(shown), suffix)
        else:
            self.gridHintText.Text = u'目前模型找不到可用網格線。'

        self.sourceModeRadio.Checked += self.mode_changed
        self.gridModeRadio.Checked += self.mode_changed
        self.sourceCombo.SelectionChanged += self.source_changed
        self.targetFilterBox.TextChanged += self.target_filter_changed
        self.targetList.SelectionChanged += self.target_selection_changed
        self.selectAllButton.Click += self.select_all_clicked
        self.clearTargetsButton.Click += self.clear_targets_clicked
        self.xGridText.TextChanged += self.settings_changed
        self.yGridText.TextChanged += self.settings_changed
        self.offsetText.TextChanged += self.settings_changed
        self.scopeBoxCombo.SelectionChanged += self.settings_changed
        self.acknowledgeCheck.Checked += self.settings_changed
        self.acknowledgeCheck.Unchecked += self.settings_changed
        self.executeButton.Click += self.execute_clicked
        self.cancelButton.Click += self.cancel_clicked

        self.suppress_events = False
        self._sync_mode()
        self._sync_source_hint()
        self._refresh_targets(False)
        self._update_state()

    def _mode(self):
        return MODE_GRID if self.gridModeRadio.IsChecked else MODE_SOURCE

    def _source_view(self):
        index = int(self.sourceCombo.SelectedIndex)
        if index < 0 or index >= len(self.views):
            return None
        return self.views[index]

    def _source_dependent_count(self):
        source = self._source_view()
        return _dependent_count(source) if source is not None else 0

    def _source_label(self, view):
        count = _dependent_count(view)
        if count:
            return u'{}  ｜  來源模板 {} 張從屬視圖'.format(
                _view_label(view), count)
        return u'{}  ｜  沒有從屬視圖（使用母圖 CropBox）'.format(
            _view_label(view))

    def _sync_source_hint(self):
        count = self._source_dependent_count()
        if count:
            self.sourceHintText.Text = (
                u'將複製此母圖下的 {} 張從屬視圖，逐張套用 CropBox／Crop Shape。'
                u'命名沿用來源從屬視圖在來源母圖名稱後的後綴，例如 A-1～A-4 → B-1～B-4。'
            ).format(count)
        else:
            self.sourceHintText.Text = (
                u'此母圖目前沒有從屬視圖，將只複製母圖 CropBox，'
                u'每個目標建立 1 張從屬視圖。')

    def _target_label(self, view):
        count = self.view_counts.get(_id_value(view.Id), 0)
        if count:
            return u'{}  ｜  既有 {} 張'.format(_view_label(view), count)
        return _view_label(view)

    def _capture_visible_selection(self):
        if self.suppress_events:
            return
        visible_ids = set(_id_value(view.Id)
                          for view in self.visible_target_views)
        selected_labels = set(u'{}'.format(item)
                              for item in self.targetList.SelectedItems)
        selected_ids = set()
        for label in selected_labels:
            view = self.target_by_label.get(label)
            if view is not None:
                selected_ids.add(_id_value(view.Id))
        self.selected_target_ids.difference_update(visible_ids)
        self.selected_target_ids.update(selected_ids)

    def _refresh_targets(self, capture_selection=True):
        if capture_selection:
            self._capture_visible_selection()
        source_id = None
        if self._mode() == MODE_SOURCE:
            source = self._source_view()
            source_id = _id_value(source.Id) if source is not None else None
            if source_id is not None:
                self.selected_target_ids.discard(source_id)

        filter_text = u'{}'.format(self.targetFilterBox.Text or u'').strip().lower()
        candidates = []
        for view in self.views:
            view_id = _id_value(view.Id)
            if source_id is not None and view_id == source_id:
                continue
            if filter_text and filter_text not in _view_label(view).lower():
                continue
            candidates.append(view)

        self.suppress_events = True
        try:
            self.targetList.Items.Clear()
            self.visible_target_views = candidates
            self.target_by_label = {}
            for view in candidates:
                label = self._target_label(view)
                self.target_by_label[label] = view
                self.targetList.Items.Add(label)
                if _id_value(view.Id) in self.selected_target_ids:
                    self.targetList.SelectedItems.Add(label)
        finally:
            self.suppress_events = False

    def _selected_views(self):
        selected = self.selected_target_ids
        return [view for view in self.views
                if _id_value(view.Id) in selected]

    def _sync_mode(self):
        source_mode = self._mode() == MODE_SOURCE
        self.sourcePanel.Visibility = (self._visible_value if source_mode
                                       else self._collapsed_value)
        self.gridPanel.Visibility = (self._collapsed_value if source_mode
                                     else self._visible_value)

    def _update_target_summary(self, target_views):
        if not target_views:
            self.targetSummaryText.Text = u'尚未選取目標母圖'
            return
        names = [_view_name(view) for view in target_views]
        preview = u'、'.join(names[:3])
        if len(names) > 3:
            preview += u'…'
        self.targetSummaryText.Text = u'已選 {} 張：{}'.format(
            len(target_views), preview)

    def _update_rebuild_warning(self, target_views):
        risk_ids = set()
        existing_total = 0
        existing_parents = 0
        for view in target_views:
            view_id = _id_value(view.Id)
            count = self.view_counts.get(view_id, 0)
            if count:
                risk_ids.add(view_id)
                existing_total += count
                existing_parents += 1

        if risk_ids != self.last_risk_ids:
            self.acknowledgeCheck.IsChecked = False
            self.last_risk_ids = risk_ids

        if existing_total:
            self.rebuildTitleText.Text = u'重跑策略：先清除舊從屬視圖，再重建'
            self.rebuildDetailText.Text = (
                u'所選母圖中有 {} 張含既有從屬視圖，共會先清除 {} 張。'
                u'若舊視圖已放在圖紙上，其視口也可能一併移除。').format(
                    existing_parents, existing_total)
            self.acknowledgeCheck.Content = (
                u'我了解將清除 {} 張既有從屬視圖，然後重建').format(
                    existing_total)
            self.acknowledgeCheck.Visibility = self._visible_value
        else:
            self.rebuildTitleText.Text = u'重跑策略：自動取代既有從屬視圖'
            self.rebuildDetailText.Text = (
                u'目前選取的母圖沒有既有從屬視圖，將直接建立新視圖。'
                if target_views else
                u'選取目標後，這裡會顯示即將清除與重建的數量。')
            self.acknowledgeCheck.Visibility = self._collapsed_value
        return existing_total

    def _settings(self):
        target_views = self._selected_views()
        if not target_views:
            return None, u'請選取至少一張目標母圖。'

        source_view = None
        grid_settings = None
        if self._mode() == MODE_SOURCE:
            source_view = self._source_view()
            if source_view is None:
                return None, u'請選取裁切來源母圖。'
        else:
            grid_settings, error = logic.validate_grid_settings(
                self.xGridText.Text, self.yGridText.Text,
                self.offsetText.Text, self.grid_names)
            if error:
                return None, error

        existing_total = sum(
            self.view_counts.get(_id_value(view.Id), 0)
            for view in target_views)
        if existing_total and not self.acknowledgeCheck.IsChecked:
            return None, u'請勾選下方重建提醒，確認已了解舊視圖與圖紙視口風險。'

        scope_index = int(self.scopeBoxCombo.SelectedIndex)
        scope_name = None
        scope_box_id = None
        if scope_index > 0 and scope_index <= len(self.scope_boxes):
            scope_name, scope_box_id = self.scope_boxes[scope_index - 1]

        return {
            'mode': self._mode(),
            'source_view': source_view,
            'target_views': target_views,
            'source_dependent_count': (
                _dependent_count(source_view) if source_view is not None else 0),
            'grid_settings': grid_settings,
            'scope_name': scope_name,
            'scope_box_id': scope_box_id,
        }, None

    def _update_state(self):
        if self.suppress_events:
            return
        target_views = self._selected_views()
        self._update_target_summary(target_views)
        self._update_rebuild_warning(target_views)
        settings, error = self._settings()
        if error:
            self.statusText.Foreground = self.FindResource('ErrorBrush')
            self.statusText.Text = error
            self.executeButton.IsEnabled = False
            return
        self.statusText.Foreground = self.FindResource('SuccessBrush')
        self.statusText.Text = u'設定完成：將建立／重建 {} 張從屬視圖。'.format(
            len(settings['target_views']) *
            (settings.get('source_dependent_count') or 1))
        self.executeButton.IsEnabled = True

    def mode_changed(self, sender, args):
        if self.suppress_events:
            return
        self._capture_visible_selection()
        self._sync_mode()
        self._refresh_targets(False)
        self._update_state()

    def source_changed(self, sender, args):
        if self.suppress_events:
            return
        self._capture_visible_selection()
        self._sync_source_hint()
        self._refresh_targets(False)
        self._update_state()

    def target_filter_changed(self, sender, args):
        if self.suppress_events:
            return
        self._refresh_targets(True)
        self._update_state()

    def target_selection_changed(self, sender, args):
        if self.suppress_events:
            return
        self._capture_visible_selection()
        self._update_state()

    def select_all_clicked(self, sender, args):
        for view in self.visible_target_views:
            self.selected_target_ids.add(_id_value(view.Id))
        self._refresh_targets(False)
        self._update_state()

    def clear_targets_clicked(self, sender, args):
        self.selected_target_ids.clear()
        self._refresh_targets(False)
        self._update_state()

    def settings_changed(self, sender, args):
        self._update_state()

    def execute_clicked(self, sender, args):
        settings, error = self._settings()
        if error:
            self.statusText.Foreground = self.FindResource('ErrorBrush')
            self.statusText.Text = error
            self.executeButton.IsEnabled = False
            return
        self.result = settings
        self.Close()

    def cancel_clicked(self, sender, args):
        self.result = None
        self.Close()


def _run():
    if revit.doc is None:
        forms.alert(u'請先開啟 Revit 專案文件。', title=TITLE)
        return

    views = _eligible_views(revit.doc)
    if not views:
        forms.alert(
            u'找不到可建立從屬視圖的平面母圖。\n'
            u'請在非從屬的平面視圖中執行。', title=TITLE)
        return

    grids_result = mcp.run('get_all_grids', {})
    scope_result = mcp.run('list_scope_boxes', {})
    window = DependentViewCropWindow(
        views, _id_value(revit.doc.ActiveView.Id),
        _grid_names(grids_result), _scope_boxes(scope_result))
    window.ShowDialog()
    settings = window.result
    if settings is None:
        return

    target_views = settings['target_views']
    target_ids = [_id_value(view.Id) for view in target_views]
    scope_box_id = settings['scope_box_id']
    scope_name = settings['scope_name']
    source_view = settings['source_view']

    if settings['mode'] == MODE_SOURCE:
        source_dependent_count = settings.get('source_dependent_count') or 0
        crop = None
        if not source_dependent_count:
            source_crop = mcp.run(
                'get_view_crop_box', {'viewId': _id_value(source_view.Id)})
            crop = (source_crop.get('CropBox')
                    if isinstance(source_crop, dict) else None)
            if not crop or not crop.get('min') or not crop.get('max'):
                forms.alert(u'來源母圖沒有可讀取的 CropBox。', title=TITLE)
                return
        mode_name = (u'複製指定母圖的從屬視圖模板'
                     if source_dependent_count else
                     u'複製指定母圖 CropBox')
        params = {
            'parentViewIds': target_ids,
            'sourceCropViewId': _id_value(source_view.Id),
            'suffixName': '',
            'copyCropShape': True,
            'copyCropVisibility': False,
            'copySourceDependents': True,
            'replaceExistingDependentViews': True,
        }
        if crop:
            params['min'] = crop.get('min')
            params['max'] = crop.get('max')
        command = 'create_dependent_views'
    else:
        grid_settings = settings['grid_settings']
        mode_name = u'依網格線計算 CropBox'
        params = {
            'parentViewIds': target_ids,
            'x_grid_names': grid_settings['x_names'],
            'y_grid_names': grid_settings['y_names'],
            'offset_mm': grid_settings['offset_mm'],
            'suffixName': '',
            'replaceExistingDependentViews': True,
        }
        command = 'create_grid_cropped_views_batch'

    if scope_box_id is not None:
        params['scopeBoxId'] = scope_box_id

    result = mcp.run(command, params)
    forms.alert(
        logic.result_summary(
            result, mode_name, len(target_views),
            _view_name(source_view) if source_view else None,
            scope_name,
            settings.get('source_dependent_count') if source_view else None),
        title=TITLE)


try:
    _run()
except mcp.MCPBridgeError as error:
    mcp.show_error(error, TITLE)
except Exception as error:
    forms.alert(u'執行失敗：\n{}'.format(error), title=TITLE)
