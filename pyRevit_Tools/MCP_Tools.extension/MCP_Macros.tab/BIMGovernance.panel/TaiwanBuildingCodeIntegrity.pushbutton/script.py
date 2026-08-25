# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""台灣建築法規模型資料完整性檢查器（pyRevit + WPF/XAML）。

檢核走 RevitMCP 的唯讀 audit_code_inputs；填值只在使用者確認後，
以一個 Revit Transaction 寫入 Project Information 與 Area 參數。
本按鈕不推導法規數值，也不把檢核 Gate 當成法規合規結論。
"""

import os

from Autodesk.Revit import DB
from pyrevit import forms, revit

import mcp_bridge as mcp
import code_integrity_excel as integrity_excel


__title__ = u'台灣法規\n模型檢核'
_TITLE = u'台灣建築法規模型資料完整性檢查器'

PROJECT_PARAMETER_NAMES = [
    u'Law_地籍基地面積',
    u'Law_法定開挖率%',
    u'Law_法定建蔽率%',
    u'Law_法定容積率%',
    u'Law_機電設備容積乘積%',
    u'Law_停車檢討適用法規',
    u'Law_供公眾建築物',
    u'Law_防火構造',
    u'Law_都市計畫區域',
]

AREA_PARAMETER_NAMES = [
    u'Law_建管-用途類組',
    u'Law_技規-法定名稱',
]

EMPTY_SENTINELS = set([
    u'', u'(無)', u'（無）', u'<空白>', u'<無>', u'-',
])


def _text(value):
    if value is None:
        return u''
    try:
        return unicode(value)
    except Exception:
        return u'{}'.format(value)


def _id_value(element_or_id):
    value = getattr(element_or_id, 'Id', element_or_id)
    for property_name in ('Value', 'IntegerValue'):
        try:
            return int(getattr(value, property_name))
        except Exception:
            pass
    try:
        return int(value)
    except Exception:
        return 0


def _parameter_value(parameter):
    if parameter is None:
        return u''
    try:
        value = parameter.AsValueString()
        if value is not None:
            return _text(value)
    except Exception:
        pass
    try:
        return _text(parameter.AsString())
    except Exception:
        return u''


def _parameter_has_value(parameter):
    try:
        return bool(parameter is not None and parameter.HasValue)
    except Exception:
        return bool(parameter is not None)


def _meaningful(value):
    return _text(value).strip() not in EMPTY_SENTINELS


def _value_status(parameter, value):
    if parameter is None:
        return u'PARAMETER_NOT_FOUND'
    if _parameter_has_value(parameter) and _meaningful(value):
        return u'VALUE'
    if _text(value).strip() in EMPTY_SENTINELS:
        return u'EMPTY_SENTINEL'
    return u'EMPTY'


def _storage_name(parameter):
    if parameter is None:
        return u''
    try:
        return _text(parameter.StorageType)
    except Exception:
        return u''


def _find_parameter(element, name):
    if element is None:
        return None
    try:
        return element.LookupParameter(name)
    except Exception:
        return None


def _make_row(scope, element_id, element_name, parameter_name, parameter):
    current = _parameter_value(parameter)
    return {
        'scope': scope,
        'element_id': element_id,
        'element_name': element_name,
        'parameter_name': parameter_name,
        'parameter': parameter,
        'exists': parameter is not None,
        'readonly': bool(parameter is not None and parameter.IsReadOnly),
        'storage': _storage_name(parameter),
        'current': current,
        'has_value': _parameter_has_value(parameter),
        'proposed': current,
        'value_status': _value_status(parameter, current),
        'textbox': None,
    }


def _configured_names(audit, key, fallback):
    try:
        inputs = audit.get('AuditInputs') or {}
        names = inputs.get(key) or []
        names = [_text(item).strip() for item in names if _text(item).strip()]
        return names or list(fallback)
    except Exception:
        return list(fallback)


def _load_input_rows(audit=None):
    project_rows = []
    area_rows = []
    project_names = _configured_names(
        audit or {}, 'RequiredProjectParameters', PROJECT_PARAMETER_NAMES)
    area_names = _configured_names(
        audit or {}, 'RequiredAreaParameters', AREA_PARAMETER_NAMES)
    project_info = revit.doc.ProjectInformation
    for name in project_names:
        project_rows.append(_make_row(
            u'ProjectInformation', 0, u'Project Information', name,
            _find_parameter(project_info, name)))

    areas = (DB.FilteredElementCollector(revit.doc)
             .OfCategory(DB.BuiltInCategory.OST_Areas)
             .WhereElementIsNotElementType()
             .ToElements())
    areas = sorted(list(areas), key=lambda item: _id_value(item))
    for area in areas:
        area_id = _id_value(area)
        area_name = _text(getattr(area, 'Name', u''))
        for name in area_names:
            area_rows.append(_make_row(
                u'Areas', area_id, area_name, name,
                _find_parameter(area, name)))
    return project_rows, area_rows


def _run_audit():
    return mcp.run('audit_code_inputs', {
        'rulePackId': 'taiwan-building-code-model-integrity',
        'checkNamedViews': True,
        'checkAreaPlanContent': True,
        'includeElementSamples': False,
    })


def _audit_summary(audit):
    summary = audit.get('Summary') if isinstance(audit, dict) else {}
    summary = summary if isinstance(summary, dict) else {}
    findings = audit.get('Findings') if isinstance(audit, dict) else []
    findings = findings if isinstance(findings, list) else []
    fail = int(summary.get('Fail', 0) or 0)
    warning = int(summary.get('Warning', 0) or 0)
    unknown = int(summary.get('Unknown', 0) or 0)
    passed = int(summary.get('Pass', 0) or 0)
    if not summary.get('GateStatus'):
        fail = fail or len([item for item in findings
                            if item.get('Status') == 'FAIL'])
        warning = warning or len([item for item in findings
                                  if item.get('Status') == 'WARNING'])
        unknown = unknown or len([item for item in findings
                                  if item.get('Status') == 'UNKNOWN'])
        passed = passed or len([item for item in findings
                               if item.get('Status') == 'PASS'])
    gate = summary.get('GateStatus')
    if not gate:
        gate = u'BLOCKED' if fail else u'CONDITIONAL' if (warning or unknown) else u'READY'
    return {
        'gate': _text(gate),
        'pass': passed,
        'fail': fail,
        'warning': warning,
        'unknown': unknown,
    }


def _row_has_existing_value(row):
    return bool(row.get('has_value')) and _meaningful(row.get('current'))


def _parse_integer(value):
    normalized = _text(value).strip()
    if normalized.endswith(u'%'):
        normalized = normalized[:-1].strip()
    try:
        return int(normalized)
    except Exception:
        return None


def _describe_row(row):
    if row.get('scope') == u'ProjectInformation':
        return row.get('parameter_name')
    return u'Area {0}／{1}'.format(
        row.get('element_id'), row.get('parameter_name'))


def _build_plan(rows, overwrite):
    candidates = []
    skipped = []
    errors = []
    for row in rows:
        proposed = _text(row.get('proposed')).strip()
        if (not row.get('exists') or
                proposed == _text(row.get('current')) or not proposed):
            continue
        if not overwrite and _row_has_existing_value(row):
            skipped.append(_describe_row(row))
            continue
        candidates.append(row)

    for row in candidates:
        label = _describe_row(row)
        if row.get('parameter') is None:
            errors.append(u'{0}：找不到參數。'.format(label))
        elif row.get('readonly'):
            errors.append(u'{0}：參數是唯讀。'.format(label))
        elif row.get('storage') == u'Integer' and _parse_integer(row.get('proposed')) is None:
            errors.append(u'{0}：整數欄位請輸入整數；百分比可寫成 60 或 60%。'.format(label))
        elif row.get('storage') not in (u'String', u'Integer', u'Double'):
            errors.append(u'{0}：不支援 {1} 參數類型。'.format(label, row.get('storage')))
    return candidates, skipped, errors


def _plan_text(candidates, skipped, errors, operation=u'預覽'):
    lines = [
        u'{0}：可寫入 {1} 列。'.format(operation, len(candidates)),
        u'只填空白模式保留既有值：{0} 列。'.format(len(skipped)),
    ]
    if candidates:
        lines.append(u'即將處理：')
        lines.extend(u'・{0} ← {1}'.format(
            _describe_row(row), _text(row.get('proposed')).strip())
                     for row in candidates[:8])
        if len(candidates) > 8:
            lines.append(u'・…其餘 {0} 列'.format(len(candidates) - 8))
    if errors:
        lines.append(u'錯誤：')
        lines.extend(u'・{0}'.format(item) for item in errors[:8])
        if len(errors) > 8:
            lines.append(u'・…其餘 {0} 項錯誤'.format(len(errors) - 8))
    return u'\n'.join(lines)


class WarningSwallower(DB.IFailuresPreprocessor):
    def PreprocessFailures(self, failures_accessor):
        for failure in failures_accessor.GetFailureMessages():
            if failure.GetSeverity() == DB.FailureSeverity.Warning:
                failures_accessor.DeleteWarning(failure)
        return DB.FailureProcessingResult.Continue


class TaiwanBuildingCodeIntegrityWindow(forms.WPFWindow):
    def __init__(self):
        xaml_path = os.path.join(os.path.dirname(__file__),
                                 'TaiwanBuildingCodeIntegrity.xaml')
        forms.WPFWindow.__init__(self, xaml_path)
        self.Title = _TITLE
        self.project_rows = []
        self.area_rows = []
        self.audit = None
        self.excel_path = u''
        self._load_controls()
        self._load_and_render()

    def _load_controls(self):
        from System.Windows import (GridLength, GridUnitType, HorizontalAlignment,
                                    TextWrapping, Thickness, VerticalAlignment)
        from System.Windows.Controls import (Border, ColumnDefinition, Grid,
                                             TextBlock, TextBox)
        from System.Windows.Media import Brushes
        from System.Windows import FontWeights
        self._GridLength = GridLength
        self._GridUnitType = GridUnitType
        self._HorizontalAlignment = HorizontalAlignment
        self._VerticalAlignment = VerticalAlignment
        self._TextWrapping = TextWrapping
        self._Thickness = Thickness
        self._Border = Border
        self._ColumnDefinition = ColumnDefinition
        self._Grid = Grid
        self._TextBlock = TextBlock
        self._TextBox = TextBox
        self._Brushes = Brushes
        self._FontWeights = FontWeights
        self._border_brush = self.FindResource('BorderBrush')
        self.refreshButton.Click += self.refresh_clicked
        self.closeButton.Click += self.cancel_clicked
        self.previewButton.Click += self.preview_clicked
        self.applyButton.Click += self.apply_clicked
        self.importExcelButton.Click += self.import_excel_clicked
        self.exportExcelButton.Click += self.export_excel_clicked

    def _load_and_render(self):
        self.audit = _run_audit()
        self.project_rows, self.area_rows = _load_input_rows(self.audit)
        self._render_audit()
        self._render_headers()
        self._render_rows()
        self.statusText.Text = (
            u'已完成唯讀盤點。可在「Project Information 輸入」或「Area 輸入」'
            u'編輯新值，再按預覽；目前尚未修改模型。')

    def _render_audit(self):
        summary = _audit_summary(self.audit)
        self.documentText.Text = _text(
            (self.audit.get('Document') or {}).get('Title') or u'目前 Revit 專案')
        self.gateStatusText.Text = summary['gate']
        self.summaryText.Text = u'PASS {0}　FAIL {1}　WARNING {2}　UNKNOWN {3}'.format(
            summary['pass'], summary['fail'], summary['warning'], summary['unknown'])
        if summary['fail']:
            self.gateHintText.Text = (
                u'目前有 FAIL；請先補齊必要模型資料，再進入專用法規規則檢討。')
            self.gateStatusText.Foreground = self._Brushes.Red
        elif summary['warning'] or summary['unknown']:
            self.gateHintText.Text = (
                u'可進入專用法規規則檢討，但 WARNING／UNKNOWN 仍需人工決策；'
                u'這不代表現行法規合規。')
            self.gateStatusText.Foreground = self._Brushes.DarkOrange
        else:
            self.gateHintText.Text = (
                u'模型輸入完整性閘門通過；仍不代表現行法規合規。')
            self.gateStatusText.Foreground = self._Brushes.Green
        self.auditRunText.Text = u'AuditRunId：{0}　{1}'.format(
            _text(self.audit.get('AuditRunId')), _text(self.audit.get('CheckedAtUtc')))

        self.findingsPanel.Children.Clear()
        findings = self.audit.get('Findings') or []
        for finding in findings:
            self._add_finding_row(finding)

    def _render_headers(self):
        self._make_header(self.projectHeader, [
            (u'參數名稱', 260), (u'類型', 90), (u'目前值', 180),
            (u'新值（可編輯）', 230), (u'欄位狀態', 140), (u'存在／唯讀', 110)])
        self._make_header(self.areaHeader, [
            (u'Area', 230), (u'參數名稱', 230), (u'目前值', 180),
            (u'新值（可編輯）', 230), (u'欄位狀態', 140), (u'存在／唯讀', 110)])

    def _render_rows(self):
        self.projectRowsPanel.Children.Clear()
        self.areaRowsPanel.Children.Clear()
        for row in self.project_rows:
            self._add_input_row(self.projectRowsPanel, row, False)
        for row in self.area_rows:
            self._add_input_row(self.areaRowsPanel, row, True)

    def _make_header(self, panel, columns):
        panel.Children.Clear()
        panel.ColumnDefinitions.Clear()
        for title, width in columns:
            column = self._ColumnDefinition()
            column.Width = self._GridLength(width, self._GridUnitType.Pixel)
            panel.ColumnDefinitions.Add(column)
        for index, item in enumerate(columns):
            title, unused_width = item
            text = self._TextBlock()
            text.Text = title
            text.FontWeight = self._FontWeights.SemiBold
            text.VerticalAlignment = self._VerticalAlignment.Center
            text.Margin = self._Thickness(8, 0, 4, 0)
            self._add_cell(panel, text, index, 0)

    def _add_input_row(self, parent, row, is_area):
        grid = self._Grid()
        widths = [230, 230, 180, 230, 140, 110] if is_area else [260, 90, 180, 230, 140, 110]
        for width in widths:
            column = self._ColumnDefinition()
            column.Width = self._GridLength(width, self._GridUnitType.Pixel)
            grid.ColumnDefinitions.Add(column)

        first = (u'Area {0} ｜ {1}'.format(row['element_id'], row['element_name'])
                 if is_area else row['parameter_name'])
        second = row['parameter_name'] if is_area else row['storage']
        values = [first, second, row['current'], None,
                  row['value_status'],
                  (u'不存在' if not row['exists'] else
                   u'唯讀' if row['readonly'] else u'可寫入')]
        for index, value in enumerate(values):
            if index == 3:
                control = self._TextBox()
                control.Text = _text(row['proposed'])
                control.IsEnabled = bool(row['exists'] and not row['readonly'])
                control.Tag = row
                control.TextChanged += self.input_changed
            else:
                control = self._TextBlock()
                control.Text = _text(value)
                control.VerticalAlignment = self._VerticalAlignment.Center
                control.TextWrapping = self._TextWrapping.Wrap
                if index == 5 and row['readonly']:
                    control.Foreground = self._Brushes.DarkOrange
            self._add_cell(grid, control, index, 1)
        parent.Children.Add(grid)

    def _add_finding_row(self, finding):
        grid = self._Grid()
        widths = [90, 255, 1, 300]
        for width in widths:
            column = self._ColumnDefinition()
            column.Width = (self._GridLength(width, self._GridUnitType.Star)
                            if width == 1 else
                            self._GridLength(width, self._GridUnitType.Pixel))
            grid.ColumnDefinitions.Add(column)
        status = _text(finding.get('Status'))
        values = [status, finding.get('Id'), finding.get('Message'),
                  finding.get('Reference')]
        for index, value in enumerate(values):
            control = self._TextBlock()
            control.Text = _text(value)
            control.VerticalAlignment = self._VerticalAlignment.Center
            control.TextWrapping = self._TextWrapping.Wrap
            if index == 0:
                control.FontWeight = self._FontWeights.SemiBold
                control.Foreground = (self._Brushes.Green if status == u'PASS' else
                                      self._Brushes.Red if status == u'FAIL' else
                                      self._Brushes.DarkOrange)
            self._add_cell(grid, control, index, 1)
        self.findingsPanel.Children.Add(grid)

    def _add_cell(self, row, control, column_index, row_index):
        cell = self._Border()
        cell.BorderBrush = self._border_brush
        cell.BorderThickness = self._Thickness(0, 0, 1, 1)
        cell.Padding = self._Thickness(4, 3, 4, 3)
        cell.Child = control
        self._Grid.SetColumn(cell, column_index)
        row.Children.Add(cell)

    def input_changed(self, sender, args):
        row = sender.Tag
        if row is not None:
            row['proposed'] = _text(sender.Text)

    def refresh_clicked(self, sender, args):
        try:
            self._load_and_render()
        except Exception as error:
            forms.alert(u'重新檢核失敗：\n{}'.format(_text(error)), title=_TITLE)

    def _plan(self):
        overwrite = bool(self.overwriteCheck.IsChecked)
        return _build_plan(self.project_rows + self.area_rows, overwrite)

    def preview_clicked(self, sender, args):
        try:
            candidates, skipped, errors = self._plan()
            text = _plan_text(candidates, skipped, errors)
            self.statusText.Text = text
            if errors:
                forms.alert(text, title=_TITLE)
            else:
                forms.alert(text + u'\n\n預覽不會修改模型。', title=_TITLE)
        except Exception as error:
            forms.alert(u'預覽失敗：\n{}'.format(_text(error)), title=_TITLE)

    def _default_excel_name(self):
        title = _text(getattr(revit.doc, 'Title', u'目前模型'))
        for character in u'<>:"/\\|?*':
            title = title.replace(character, u'_')
        title = title.strip().rstrip(u'.') or u'目前模型'
        return u'台灣建築法規模型資料完整性檢查_{}.xlsx'.format(title[:60])

    def _excel_result_text(self, result, prefix):
        lines = [prefix]
        changes = result.get('changes') or []
        warnings = result.get('warnings') or []
        errors = result.get('errors') or []
        lines.append(u'可匯入變更：{} 列。'.format(len(changes)))
        if warnings:
            lines.append(u'警告：')
            lines.extend(u'・{}'.format(item) for item in warnings[:8])
            if len(warnings) > 8:
                lines.append(u'・…其餘 {} 項警告'.format(len(warnings) - 8))
        if errors:
            lines.append(u'阻擋匯入：')
            lines.extend(u'・{}'.format(item) for item in errors[:12])
            if len(errors) > 12:
                lines.append(u'・…其餘 {} 項錯誤'.format(len(errors) - 12))
        return u'\n'.join(lines)

    def export_excel_clicked(self, sender, args):
        path = forms.save_file(
            file_ext='xlsx', default_name=self._default_excel_name())
        if not path:
            return
        try:
            sheets, unused_metadata = integrity_excel.build_workbook(
                self.project_rows,
                self.area_rows,
                self.audit,
                _text(getattr(revit.doc, 'Title', u'目前模型')),
                _text(getattr(revit.app, 'VersionNumber', u'')))
            # Lazy import keeps the pure contract module CPython-testable and
            # loads System.IO.Compression only when the user actually exports.
            import xlsx_writer
            xlsx_writer.write_workbook(path, sheets)
            self.excel_path = path
            self.statusText.Text = (
                u'Excel 已匯出：{}\n請只編輯「新值（可編輯）」欄，'
                u'再按「匯入 Excel...」；匯入後仍需預覽與套用。'.format(path))
            forms.alert(
                u'匯出完成。\n\n檔案：{}\n\n活頁簿包含「說明、專案輸入、Area輸入、檢核結果」四個分頁。\n'
                u'請勿修改 Key 與識別欄位。'.format(path), title=_TITLE)
        except Exception as error:
            forms.alert(u'匯出 Excel 失敗：\n{}'.format(_text(error)), title=_TITLE)

    def import_excel_clicked(self, sender, args):
        path = forms.pick_file(
            files_filter='Excel workbook (*.xlsx)|*.xlsx')
        if not path:
            return
        try:
            result = integrity_excel.import_workbook(
                path,
                self.project_rows,
                self.area_rows,
                expected_model_title=_text(getattr(revit.doc, 'Title', u'')),
                expected_revit_version=_text(
                    getattr(revit.app, 'VersionNumber', u'')))
            message = self._excel_result_text(result, u'Excel 匯入驗證完成。')
            if result.get('errors'):
                self.statusText.Text = message
                forms.alert(message + u'\n\n模型沒有修改，畫面也沒有套用 Excel 變更。',
                             title=_TITLE)
                return
            applied = integrity_excel.merge_changes(
                self.project_rows + self.area_rows, result.get('changes'))
            self.excel_path = path
            self._render_rows()
            self.statusText.Text = (
                message + u'\n已載入 {} 列至畫面預覽；模型尚未修改，請再按「預覽變更」或「套用變更」。'
                .format(applied))
            forms.alert(self.statusText.Text, title=_TITLE)
        except Exception as error:
            forms.alert(u'匯入 Excel 失敗：\n{}'.format(_text(error)), title=_TITLE)

    def apply_clicked(self, sender, args):
        try:
            candidates, skipped, errors = self._plan()
            preview_text = _plan_text(candidates, skipped, errors)
            self.statusText.Text = preview_text
            if errors:
                forms.alert(preview_text, title=_TITLE)
                return
            if not candidates:
                forms.alert(preview_text + u'\n\n沒有需要套用的變更。', title=_TITLE)
                return
            if not forms.alert(
                    preview_text + u'\n\n確定要以單一 Transaction 寫入模型嗎？',
                    title=_TITLE, yes=True, no=True):
                return

            transaction = DB.Transaction(revit.doc, _TITLE + u'｜填入')
            transaction.Start()
            options = transaction.GetFailureHandlingOptions()
            options.SetFailuresPreprocessor(WarningSwallower())
            transaction.SetFailureHandlingOptions(options)
            try:
                for row in candidates:
                    self._apply_row(row)
                transaction.Commit()
            except Exception:
                transaction.RollBack()
                raise

            self._load_and_render()
            self.statusText.Text = u'已寫入 {0} 列，並重新執行模型資料完整性檢查。'.format(
                len(candidates))
            forms.alert(self.statusText.Text, title=_TITLE)
        except Exception as error:
            forms.alert(
                u'套用失敗；交易已回復，模型沒有留下部分寫入：\n{}'.format(
                    _text(error)), title=_TITLE)

    def _apply_row(self, row):
        if row['scope'] == u'ProjectInformation':
            element = revit.doc.ProjectInformation
        else:
            element = revit.doc.GetElement(DB.ElementId(row['element_id']))
        parameter = _find_parameter(element, row['parameter_name'])
        if parameter is None:
            raise RuntimeError(u'{0}：找不到參數。'.format(_describe_row(row)))
        if parameter.IsReadOnly:
            raise RuntimeError(u'{0}：參數是唯讀。'.format(_describe_row(row)))

        value = _text(row['proposed']).strip()
        storage = _storage_name(parameter)
        if storage == u'String':
            success = parameter.Set(value)
        elif storage == u'Integer':
            integer_value = _parse_integer(value)
            if integer_value is None:
                raise RuntimeError(u'{0}：整數解析失敗。'.format(_describe_row(row)))
            success = parameter.Set(integer_value)
        elif storage == u'Double':
            # 交給 Revit 依目前專案單位解析，避免在 UI 層重複換算。
            success = parameter.SetValueString(value)
        else:
            raise RuntimeError(u'{0}：不支援 {1} 參數類型。'.format(
                _describe_row(row), storage))
        if not success:
            raise RuntimeError(u'{0}：Revit 拒絕寫入新值。'.format(_describe_row(row)))

    def cancel_clicked(self, sender, args):
        self.Close()


def main():
    if revit.doc is None:
        forms.alert(u'請先開啟 Revit 專案檔，再執行本按鈕。',
                    title=_TITLE, exitscript=True)
    window = TaiwanBuildingCodeIntegrityWindow()
    window.ShowDialog()


try:
    main()
except mcp.MCPBridgeError as error:
    mcp.show_error(error, _TITLE)
except Exception as error:
    forms.alert(u'執行失敗：\n{}'.format(_text(error)),
                title=_TITLE, exitscript=True)
