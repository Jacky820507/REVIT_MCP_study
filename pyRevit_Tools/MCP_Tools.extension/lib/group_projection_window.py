# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
from Autodesk.Revit import DB, UI
from pyrevit import forms
from System import TimeSpan
from System.Windows import Thickness, Visibility, TextWrapping
from System.Windows.Controls import CheckBox, ComboBoxItem, StackPanel, TextBlock, Border, Orientation
from System.Windows.Media import BrushConverter
from System.Windows.Threading import DispatcherTimer

import group_projection_source as source
from group_projection_logic import ALL_LEVELS, assign_colors, interleave_coincident, level_options
from group_projection_server import ProjectionServer

_window = None


class Handler(UI.IExternalEventHandler):
    def __init__(self, window):
        self.window = window
        self.action = None

    def GetName(self):
        return 'MCP detail group projection'

    def Execute(self, app):
        window = self.window
        action, self.action = self.action, None
        try:
            if window.closed:
                return
            uidoc = app.ActiveUIDocument
            if uidoc is None:
                raise ValueError('請先開啟專案模型。')
            if action == 'refresh':
                window.load(uidoc)
            elif action == 'clear':
                window.remove_projection()
                window.legend.Children.Clear()
                window.projection_report = None
                window.diagnostic_report = None
                window.status.Text = '投影已清除。'
            elif action == 'apply':
                if window.doc is None or not uidoc.Document.Equals(window.doc):
                    window.load(uidoc)
                    window.status.Text = '已切換專案；群組清單已重讀，請勾選要投影的群組。'
                    return
                if source.id_value(uidoc.ActiveView.Id) != window.view_id:
                    # Retarget from the view that is active at the moment the
                    # user presses Apply. Keep matching source-group checks.
                    window.load(uidoc)
                window.project(uidoc)
            elif action == 'diagnostic':
                if not uidoc.Document.Equals(window.doc) or source.id_value(uidoc.ActiveView.Id) != window.view_id:
                    window.load(uidoc)
                window.diagnostic(uidoc)
        except source.ExtractionCancelled:
            window.status.Text = '已取消；保留先前投影。'
        except Exception as exc:
            window.status.Text = '未完成：{}'.format(exc)
            window.report.Text = str(exc)
        finally:
            window.busy = False
            window.controls(True)
            if window.closed:
                try:
                    window.cleanup()
                except Exception as exc:
                    window.report.Text = '投影已停用，但清理未完成：{}'.format(exc)


class ProjectionWindow(forms.WPFWindow):
    def __init__(self, app):
        forms.WPFWindow.__init__(self, os.path.join(os.path.dirname(__file__), 'GroupProjection.xaml'))
        self.app = app
        self.doc = None
        self.view_id = None
        self.server = None
        self.closed = False
        self.busy = False
        self.needs_reload = False
        self.records = []
        self.diagnostic_report = None
        self.projection_report = None
        self.checks = []
        self.handler = Handler(self)
        self.event = UI.ExternalEvent.Create(self.handler)
        self.event_disposed = False
        self.Closed += self.on_closed
        self.app.ViewActivated += self.on_view
        self.app.Application.DocumentClosing += self.on_document_closing
        self.app.Application.DocumentChanged += self.on_document_changed
        self.timer = DispatcherTimer()
        self.timer.Interval = TimeSpan.FromSeconds(1)
        self.timer.Tick += self.on_tick
        self.timer.Start()
        try:
            self.load(app.ActiveUIDocument)
        except Exception:
            self.cleanup()
            raise

    def controls(self, enabled):
        self.applyButton.IsEnabled = enabled
        self.clearButton.IsEnabled = enabled
        self.refreshButton.IsEnabled = enabled
        self.picker.IsEnabled = enabled
        self.levelBox.IsEnabled = enabled
        self.levelButton.IsEnabled = enabled

    def queue(self, action):
        if self.busy:
            return
        self.busy = True
        self.controls(False)
        self.handler.action = action
        self.status.Text = '等待 Revit 讀取…'
        result = self.event.Raise()
        if result not in (UI.ExternalEventRequest.Accepted, UI.ExternalEventRequest.Pending):
            self.busy = False
            self.controls(True)
            self.status.Text = 'Revit 暫時無法執行，請結束目前命令後重試。'

    def load(self, uidoc):
        target = uidoc.ActiveView
        target_error = source.target_view_error(target)
        if target_error:
            raise ValueError(target_error)
        selected = set(r['id'] for check, r in self.checks if check.IsChecked)
        if self.doc is not None and not self.doc.Equals(uidoc.Document):
            selected = set()
        records = source.collect_groups(uidoc.Document, target)
        self.remove_projection()
        self.diagnostic_report = None
        self.projection_report = None
        self.doc = uidoc.Document
        self.view_id = source.id_value(target.Id)
        self.records = records
        self.needs_reload = False
        level, elevation = source.level_of(target)
        self.colors = assign_colors(records, elevation)
        self.targetLabel.Text = '{}\n{} · 目標視圖 {}'.format(target.Name, level, self.view_id)
        self.choices.Children.Clear()
        self.legend.Children.Clear()
        self.checks = []
        for record in self.records:
            color = self.colors[record['id']]
            check = CheckBox()
            check.Content = '{}  {} | {} | #{}'.format(color['label'], record['name'], record['level'], record['id'])
            check.ToolTip = '{}\n{}\n色票 {}'.format(record['view_name'], check.Content, color['hex'])
            check.Margin = Thickness(0, 5, 0, 5)
            check.IsChecked = record['id'] in selected
            check.Checked += self.selection_changed
            check.Unchecked += self.selection_changed
            self.checks.append((check, record))
            self.choices.Children.Add(check)
        self.fill_levels()
        self.search_changed(None, None)
        self.selection_changed(None, None)
        self.status.Text = '找到 {} 個其他視圖的詳圖群組。'.format(len(records))
        self.report.Text = ('依來源視圖／樓層實際高程區分上下；平面圖保留 XY，'
                            '其他視圖投影到目前視圖平面。請先選取群組。')

    def fill_levels(self):
        previous = self.selected_level()
        self.levelBox.Items.Clear()
        chosen = 0
        for index, (key, label) in enumerate(level_options(self.records)):
            item = ComboBoxItem()
            item.Content = label
            item.Tag = key
            self.levelBox.Items.Add(item)
            if key is not ALL_LEVELS and key == previous:
                chosen = index
        self.levelBox.SelectedIndex = chosen

    def selected_level(self):
        item = self.levelBox.SelectedItem
        return ALL_LEVELS if item is None else item.Tag

    def level_changed(self, sender, args):
        self.search_changed(None, None)

    def selection_changed(self, sender, args):
        count = sum(1 for check, record in self.checks if check.IsChecked)
        self.picker.Content = '已勾選 {} 個群組 ▾'.format(count)

    def search_changed(self, sender, args):
        if not hasattr(self, 'checks'):
            return
        text = self.search.Text.lower().strip()
        level = self.selected_level()
        for check, record in self.checks:
            label = '{} {} {} {}'.format(record['name'], record['view_name'], record['level'], record['id']).lower()
            shown = text in label and (level is ALL_LEVELS or record['level'] == level)
            check.Visibility = Visibility.Visible if shown else Visibility.Collapsed

    def project_level_clicked(self, sender, args):
        level = self.selected_level()
        if level is ALL_LEVELS:
            self.status.Text = '請先在「來源樓層」選一個樓層。'
            return
        for check, record in self.checks:
            check.IsChecked = record['level'] == level
        self.apply_clicked(sender, args)

    def select_filtered(self, sender, args):
        for check, record in self.checks:
            if check.Visibility == Visibility.Visible:
                check.IsChecked = True

    def select_none(self, sender, args):
        for check, record in self.checks:
            check.IsChecked = False

    def apply_clicked(self, sender, args):
        self.picker.IsChecked = False
        if not any(check.IsChecked for check, record in self.checks):
            self.status.Text = '請先勾選至少一個群組。'
            return
        self.queue('apply')

    def clear_clicked(self, sender, args):
        self.queue('clear')

    def refresh_clicked(self, sender, args):
        self.queue('refresh')

    def diagnostic_clicked(self, sender, args):
        self.picker.IsChecked = False
        self.queue('diagnostic')

    def diagnostic(self, uidoc):
        target = uidoc.ActiveView
        active_ui_view = None
        for ui_view in uidoc.GetOpenUIViews():
            if source.id_value(ui_view.ViewId) == self.view_id:
                active_ui_view = ui_view
                break
        if active_ui_view is None:
            raise ValueError('找不到目前視圖的畫布，請重新開啟此視圖。')
        segments = source.diagnostic_segments(target, active_ui_view.GetZoomCorners())
        self.remove_projection()
        self.server = ProjectionServer(self.doc, self.view_id, segments)
        if not self.server.add_server():
            raise RuntimeError(self.server.error)
        uidoc.RefreshActiveView()
        self.legend.Children.Clear()
        if source.is_plan_view(target):
            self.status.Text = ('診斷 v3：左紫紅＝頂部內側，中綠＝剖切面，'
                                '右藍＝底部內側；共 {} 線段。'.format(len(segments)))
        else:
            self.status.Text = '診斷 v3：紫紅色十字與菱形；共 {} 線段。'.format(len(segments))
        self.diagnostic_report = '此圖不讀取群組；目標視圖類型：{}。'.format(target.ViewType)
        self.report.Text = self.diagnostic_report

    def project(self, uidoc):
        self.diagnostic_report = None
        if not uidoc.Document.Equals(self.doc):
            self.load(uidoc)
            raise ValueError('已切換專案；群組清單已重讀，請勾選要投影的群組。')
        if source.id_value(uidoc.ActiveView.Id) != self.view_id:
            self.load(uidoc)
        if self.needs_reload:
            self.load(uidoc)
        selected = [record for check, record in self.checks if check.IsChecked]
        if not selected:
            raise ValueError('原選取群組已不存在，請重新選取。')
        warnings = []
        target = uidoc.ActiveView
        with forms.ProgressBar(title='讀取群組投影 {value}/{max_value}', cancellable=True) as progress:
            def cancelled():
                return progress.cancelled or self.closed

            def report_progress(value, maximum):
                progress.update_progress(value, maximum)
                if progress.cancelled or self.closed:
                    raise source.ExtractionCancelled()

            readers = source.extract_selected_groups(
                self.doc, target, selected, self.colors,
                cancelled=cancelled, progress=report_progress)
        results = []
        segments = []
        for record in selected:
            color = self.colors[record['id']]
            reader = readers[record['id']]
            segments.extend(reader.segments)
            warnings.extend(reader.warnings)
            results.append((record, color, reader))
            if len(segments) > 300000:
                raise ValueError('合計超過 300,000 線段，請減少群組數量。')
        if not segments:
            self.report.Text = '\n'.join(warnings)
            self.status.Text = '選取群組沒有可投影的線形；保留先前投影，請查看讀取結果。'
            return
        plain = [((a.X, a.Y, a.Z), (b.X, b.Y, b.Z), rgb) for a, b, rgb in segments]
        segments = [(DB.XYZ(*a), DB.XYZ(*b), rgb) for a, b, rgb in interleave_coincident(plain)]
        self.remove_projection()
        self.server = ProjectionServer(self.doc, self.view_id, segments)
        if not self.server.add_server():
            raise RuntimeError(self.server.error)
        zoomed = None
        active_ui_view = None
        for ui_view in uidoc.GetOpenUIViews():
            if source.id_value(ui_view.ViewId) == self.view_id:
                active_ui_view = ui_view
                break
        if active_ui_view is not None:
            zoomed = source.ensure_projection_visible(active_ui_view, target, segments)
        uidoc.RefreshActiveView()
        self.legend.Children.Clear()
        report = []
        for record, color, reader in results:
            detail = '{} | {} | {} | #{} | {}\n來源：{}\n{} 個元素，{} 線段，{} 個 UP/DN 符號'.format(
                color['label'], record['level'], record['name'], record['id'], color['hex'],
                record['view_name'], reader.element_count, len(reader.segments), len(reader.symbols))
            row = StackPanel()
            row.Orientation = Orientation.Horizontal
            row.Margin = Thickness(0, 0, 0, 12)
            row.ToolTip = detail
            swatch = Border()
            swatch.Width, swatch.Height = 16, 16
            swatch.Background = BrushConverter().ConvertFromString(color['hex'])
            swatch.Margin = Thickness(0, 2, 10, 0)
            label = TextBlock()
            label.TextWrapping = TextWrapping.Wrap
            label.MaxWidth = 320
            label.Text = '{} {} · {}\n{} · #{} · {} 線段'.format(color['label'], record['level'],
                record['name'], color['hex'], record['id'], len(reader.segments))
            row.Children.Add(swatch)
            row.Children.Add(label)
            self.legend.Children.Add(row)
            report.append(detail)
            for symbol in reader.symbols:
                report.append('  符號 #{}：UP={} / DN={}'.format(symbol['id'], symbol['UP'], symbol['DN']))
        self.report.Text = '\n'.join(report + ['\n讀取提醒：'] + warnings)
        self.projection_report = self.report.Text
        if zoomed is True:
            visible_note = '；已自動調整畫面範圍（顯示仍受 DC3D 裁切／深度影響）'
        elif zoomed is False:
            visible_note = '；投影座標範圍在畫布內（實際顯示請看 DC3D 裁切診斷）'
        elif zoomed == 'crop':
            visible_note = '；部分投影超出目標視圖裁切框，未自動改動裁切設定'
        else:
            visible_note = '；無法自動縮放此畫布，請檢查視圖裁切／透視設定'
        self.status.Text = '已投影至目前視圖：{} 個群組／{} 線段{}。滑鼠停留色票列可看來源。'.format(
            len(results), len(segments), visible_note)
        self.status.ToolTip = '\n\n'.join(report)
        low, high = self.server._bounds
        self.renderStatus.Text = ('DirectContext3D：等待回呼；投影座標 X {:.0f}–{:.0f} mm，'
                                  'Y {:.0f}–{:.0f} mm，Z {:.0f} mm。'
                                  .format(low.X * 304.8, high.X * 304.8,
                                          low.Y * 304.8, high.Y * 304.8,
                                          low.Z * 304.8))

    def remove_projection(self, refresh=True):
        if self.server is not None:
            self.server.enabled = False
            if not self.server.remove_server():
                raise RuntimeError(self.server.error)
            self.server = None
        uidoc = self.app.ActiveUIDocument if self.app is not None else None
        if refresh and uidoc is not None:
            uidoc.RefreshActiveView()

    def on_view(self, sender, args):
        if self.closed:
            return
        view = args.CurrentActiveView
        matches = self.doc is not None and view.Document.Equals(self.doc) and source.id_value(view.Id) == self.view_id
        if not matches:
            level, unused_elevation = source.level_of(view)
            self.targetLabel.Text = '{}\n{} · 目前視圖 {}（按更新後作為投影目標）'.format(
                view.Name, level, source.id_value(view.Id))
            target_error = source.target_view_error(view)
            self.status.Text = (target_error if target_error else
                                '已切換視圖；按「更新投影」會自動以此視圖為目標。')
        else:
            level, unused_elevation = source.level_of(view)
            self.targetLabel.Text = '{}\n{} · 目標視圖 {}'.format(
                view.Name, level, source.id_value(view.Id))
            if self.server is not None:
                self.status.Text = '已回到投影目標視圖。'

    def on_document_closing(self, sender, args):
        if self.doc is not None and args.Document.Equals(self.doc):
            try:
                self.cleanup(refresh=False)
            except Exception as exc:
                self.report.Text = '投影已停用，但清理未完成：{}'.format(exc)
            finally:
                self.Close()

    def on_document_changed(self, sender, args):
        if not self.closed and self.doc is not None and args.GetDocument().Equals(self.doc):
            self.needs_reload = True
            if self.server is not None:
                self.server.enabled = False
            self.status.Text = '模型已變更，舊投影已停用；按「更新投影」會重新讀取並顯示。'

    def on_tick(self, sender, args):
        if self.server is None:
            return
        clip_report = getattr(self.server, 'clip_report', None)
        if clip_report:
            base_report = (getattr(self, 'diagnostic_report', None) or
                           getattr(self, 'projection_report', None) or
                           self.report.Text)
            if clip_report not in base_report:
                self.report.Text = (base_report + '\n\nDC3D 裁切平面診斷：\n' +
                                    clip_report)
        low, high = self.server._bounds
        extent = ('XYZ 範圍 X {:.0f}–{:.0f}、Y {:.0f}–{:.0f}、Z {:.0f} mm。'
                  .format(low.X * 304.8, high.X * 304.8,
                          low.Y * 304.8, high.Y * 304.8,
                          low.Z * 304.8))
        if not self.server.enabled:
            self.renderStatus.Text = ('目前投影已停用；RenderScene {} 次／目標視圖 {} 次是停用前的舊計數。'
                                      '請按「更新投影」重新讀取。{}'.format(
                                          self.server.render_calls,
                                          self.server.matching_render_calls, extent))
        elif self.server.error:
            self.renderStatus.Text = ('DirectContext3D 繪製失敗：{}（RenderScene {} 次；'
                                      '目標視圖 {} 次；FlushBuffer {} 次；外框 {} 次）。{}'.format(
                                          self.server.error, self.server.render_calls,
                                          self.server.matching_render_calls,
                                          self.server.flush_calls,
                                          self.server.bounding_box_calls, extent))
        elif self.server.render_calls:
            self.renderStatus.Text = ('DirectContext3D 回呼：RenderScene {} 次，其中符合目標視圖 {} 次；'
                                      'FlushBuffer {} 次；外框查詢 {} 次；CanExecute {} 次（目標視圖 #{}）。{}'
                                      .format(
                                          self.server.render_calls,
                                          self.server.matching_render_calls,
                                          self.server.flush_calls,
                                          self.server.bounding_box_calls,
                                          self.server.can_execute_calls,
                                          self.server.view_id, extent))
        else:
            self.renderStatus.Text = ('DirectContext3D 尚未收到 RenderScene；外框查詢 {} 次，'
                                      'CanExecute {} 次（目標視圖 #{}）。若目前視圖相同仍為 0，'
                                      '代表 Revit 尚未呼叫此投影伺服器。{}'.format(
                                          self.server.bounding_box_calls,
                                          self.server.can_execute_calls,
                                          self.server.view_id, extent))

    def on_closed(self, sender, args):
        self.closed = True
        if self.server is not None:
            self.server.enabled = False
        self.timer.Stop()
        if self.app is not None:
            self.handler.action = 'close'
            self.event.Raise()  # modeless close is not an API context

    def cleanup(self, refresh=True):
        self.closed = True
        self.timer.Stop()
        try:
            self.remove_projection(refresh)
        finally:
            if self.app is not None:
                self.app.ViewActivated -= self.on_view
                self.app.Application.DocumentClosing -= self.on_document_closing
                self.app.Application.DocumentChanged -= self.on_document_changed
                self.app = None
            if not self.event_disposed:
                self.timer.Tick -= self.on_tick
                self.event.Dispose()
                self.event_disposed = True


def open_window(app):
    global _window
    if _window is not None and not _window.closed:
        _window.Activate()
        return
    _window = ProjectionWindow(app)
    _window.Show()
