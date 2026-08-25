# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""無障礙樓梯數量檢核（JAC 10.05）— read-only.

建築技術規則建築設計施工編 §167-2：建築物設置之直通樓梯，至少應有一座為
無障礙樓梯。

Five things have to be settled before a verdict means anything, and each one is
asked because answering it wrongly produces a confident, wrong legal result:

* **本棟是否適用第十章** — §167 exempts 透天、公寓大廈專有部分, and small
  non-public buildings. On an exempt building the check has no meaning.
* **避難層** — §93 makes a 直通樓梯 one that reaches 避難層, so a stair running
  only between upper floors is not what §167-2 counts.
* **哪個參數、哪個值代表無障礙樓梯** — there is no Revit-native flag; every
  office marks it with its own parameter. Guessing is forbidden by
  domain/user-specified-runtime-parameters.md.
* **304.1 還是 304.4** — 304.4's looser 18/24 pair applies only to 公寓大廈 with
  ≦240m² floors. The model cannot tell, and quietly assuming the looser pair is
  how a checker comes to bless a non-compliant building.
* **分棟方式** — §167-2 is per 建築物, and Revit has no 棟.

All five live in one window rather than a chain of dialogs. That is not only
comfort: the answers interact — a different 避難層 changes which stairs are in
the denominator, a different rule changes which of them qualify — so being able
to change one and re-run is how the tool actually gets used. A dialog chain
makes every adjustment a restart from question one.

Nothing is written. The only side effect offered is selecting the stairs that
carry the 無障礙 marker but do not meet the dimensions — the row that actually
matters on a real project.
"""

__title__ = u'無障礙樓梯\n數量檢核'
__author__ = 'RevitMCP'

import os

from Autodesk.Revit import DB
from pyrevit import forms, revit, script
from System.Collections.Generic import List

import accessible_stair_logic as logic


TITLE = u'無障礙樓梯數量檢核'
MM_PER_FOOT = 304.8
NO_GROUPING = u'（整個模型視為一棟）'

DETAIL_COLUMNS = (
    (u'樓梯', 210), (u'段數', 50), (u'通達避難層', 80), (u'已標示', 60),
    (u'標示值', 90), (u'級高(mm)', 75), (u'級深(mm)', 75),
    (u'梯段淨寬(mm)', 95), (u'尺寸判定', 90), (u'說明', 260),
)

OUTCOME_COLORS = {
    logic.BUILDING_PASS: '#1B7F4B',
    logic.BUILDING_FAIL: '#B3261E',
    logic.BUILDING_UNDECIDED: '#B26B00',
    logic.BUILDING_NO_STAIR: '#68737D',
}


def _id_value(element_id):
    if element_id is None:
        return -1
    # Revit 2025+ exposes .Value; 2020-2024 only .IntegerValue.
    try:
        return int(element_id.Value)
    except Exception:
        try:
            return int(element_id.IntegerValue)
        except Exception:
            return -1


def _element_name(element):
    if element is None:
        return u''
    try:
        return DB.Element.Name.GetValue(element) or u''
    except Exception:
        try:
            return element.Name or u''
        except Exception:
            return u''


def _built_in_parameter(element, name):
    built_in = getattr(DB.BuiltInParameter, name, None)
    if built_in is None:
        return None
    try:
        return element.get_Parameter(built_in)
    except Exception:
        return None


def _parameter_text(parameter):
    if parameter is None:
        return u''
    try:
        storage = parameter.StorageType
    except Exception:
        return u''
    try:
        if storage == DB.StorageType.String:
            return (parameter.AsString() or u'').strip()
        if storage == DB.StorageType.Integer:
            return u'{}'.format(parameter.AsInteger())
        return (parameter.AsValueString() or u'').strip()
    except Exception:
        return u''


def _named_value(element, element_type, name):
    """Instance parameter first, then the type — either can carry the marker."""
    if not name:
        return u''
    for holder in (element, element_type):
        if holder is None:
            continue
        try:
            parameter = holder.LookupParameter(name)
        except Exception:
            parameter = None
        text = _parameter_text(parameter)
        if text:
            return text
    return u''


def _stairs(doc):
    architecture = getattr(DB, 'Architecture', None)
    stairs_class = getattr(architecture, 'Stairs', None) if architecture \
        else None
    if stairs_class is None:
        return []
    try:
        return list(DB.FilteredElementCollector(doc)
                    .OfClass(stairs_class)
                    .WhereElementIsNotElementType()
                    .ToElements())
    except Exception:
        return []


def _levels(doc):
    found = list(DB.FilteredElementCollector(doc)
                 .OfClass(DB.Level)
                 .WhereElementIsNotElementType()
                 .ToElements())
    found.sort(key=lambda level: level.Elevation)
    return found


def _level_id_from(element, parameter_name):
    parameter = _built_in_parameter(element, parameter_name)
    if parameter is None:
        return None
    try:
        value = _id_value(parameter.AsElementId())
    except Exception:
        return None
    return value if value > 0 else None


def _elevation_mm(doc, level_id):
    if level_id is None:
        return None
    try:
        level = doc.GetElement(DB.ElementId(int(level_id)))
        return float(level.Elevation) * MM_PER_FOOT
    except Exception:
        return None


def _run_facts(stairs):
    """``(min_run_width_mm, [style names])`` across every flight."""
    widths = []
    styles = []
    try:
        run_ids = list(stairs.GetStairsRuns())
    except Exception:
        run_ids = []
    doc = stairs.Document
    for run_id in run_ids:
        try:
            run = doc.GetElement(run_id)
        except Exception:
            continue
        if run is None:
            continue
        try:
            widths.append(float(run.ActualRunWidth) * MM_PER_FOOT)
        except Exception:
            pass
        try:
            styles.append(u'{}'.format(run.StairsRunStyle))
        except Exception:
            pass
    return (min(widths) if widths else None), styles


def _risers_present(stairs_type):
    """規範 302.1 露空式樓梯. ``None`` means unreadable, not 'open'."""
    parameter = _built_in_parameter(stairs_type, 'STAIRS_ATTR_RISERS_PRESENT')
    if parameter is None:
        return None
    try:
        return bool(parameter.AsInteger())
    except Exception:
        return None


def _multistory_levels(doc, multistory_id):
    if multistory_id <= 0:
        return []
    try:
        group = doc.GetElement(DB.ElementId(int(multistory_id)))
        return [_id_value(level_id)
                for level_id in group.GetAllConnectedLevels()]
    except Exception:
        return []


def _centre_mm(stairs):
    try:
        box = stairs.get_BoundingBox(None)
    except Exception:
        box = None
    if box is None:
        return 0.0, 0.0
    try:
        return ((float(box.Min.X) + float(box.Max.X)) * 0.5 * MM_PER_FOOT,
                (float(box.Min.Y) + float(box.Max.Y)) * 0.5 * MM_PER_FOOT)
    except Exception:
        return 0.0, 0.0


def _readable_parameters(doc, stairs):
    """``[(name, sample)]`` — parameters that could hold a marker or a 棟別."""
    found = {}
    # One stair is enough to enumerate the parameter set; a handful more only
    # improves the example value shown beside each name.
    for element in list(stairs)[:5]:
        try:
            element_type = doc.GetElement(element.GetTypeId())
        except Exception:
            element_type = None
        for holder in (element, element_type):
            if holder is None:
                continue
            try:
                parameters = list(holder.Parameters)
            except Exception:
                continue
            for parameter in parameters:
                try:
                    definition = parameter.Definition
                    name = definition.Name if definition is not None else None
                except Exception:
                    name = None
                if not name:
                    continue
                try:
                    storage = parameter.StorageType
                except Exception:
                    continue
                if storage not in (DB.StorageType.String,
                                   DB.StorageType.Integer,
                                   DB.StorageType.ElementId):
                    continue
                sample = _parameter_text(parameter)
                if name not in found or (sample and not found[name]):
                    found[name] = sample
    return sorted(found.items())


def _distinct_marker_values(doc, stairs, name):
    """``[(value, count)]`` for one parameter across every stair."""
    if not name:
        return []
    values = {}
    for element in stairs:
        try:
            element_type = doc.GetElement(element.GetTypeId())
        except Exception:
            element_type = None
        text = _named_value(element, element_type, name)
        if text:
            values[text] = values.get(text, 0) + 1
    return sorted(values.items())


def _collect(doc, stairs, marker_name, marker_values, building_name):
    records = []
    for element in stairs:
        try:
            element_type = doc.GetElement(element.GetTypeId())
        except Exception:
            element_type = None

        base_level_id = _level_id_from(element, 'STAIRS_BASE_LEVEL_PARAM')
        top_level_id = _level_id_from(element, 'STAIRS_TOP_LEVEL_PARAM')
        if top_level_id is None:
            top_level_id = _level_id_from(
                element, 'STAIRS_MULTISTORY_TOP_LEVEL_PARAM')

        try:
            multistory_id = _id_value(element.MultistoryStairsId)
        except Exception:
            multistory_id = -1

        try:
            riser_mm = float(element.ActualRiserHeight) * MM_PER_FOOT
        except Exception:
            riser_mm = None
        try:
            tread_mm = float(element.ActualTreadDepth) * MM_PER_FOOT
        except Exception:
            tread_mm = None

        width_mm, styles = _run_facts(element)
        centre_x, centre_y = _centre_mm(element)
        marker = _named_value(element, element_type, marker_name)
        building = _named_value(element, element_type, building_name) \
            if building_name else u''

        records.append({
            'id': _id_value(element.Id),
            'element_id': element.Id,
            'name': _element_name(element),
            'type_name': _element_name(element_type),
            'base_level_id': base_level_id,
            'top_level_id': top_level_id,
            'base_elevation_mm': _elevation_mm(doc, base_level_id),
            'top_elevation_mm': _elevation_mm(doc, top_level_id),
            'multistory_id': multistory_id,
            'multistory_level_ids': _multistory_levels(doc, multistory_id),
            'riser_mm': riser_mm,
            'tread_mm': tread_mm,
            'min_run_width_mm': width_mm,
            'run_styles': styles,
            'risers_present': _risers_present(element_type),
            'designated': marker in marker_values,
            'designation_value': marker,
            'building': building or logic.SINGLE_BUILDING,
            'centre_x_mm': centre_x,
            'centre_y_mm': centre_y,
        })
    return records


def _fmt(value):
    if value is None:
        return u''
    return u'{:.0f}'.format(value)


class AccessibleStairWindow(forms.WPFWindow):
    """One window for all five inputs, because the answers interact."""

    def __init__(self, doc):
        xaml = os.path.join(os.path.dirname(__file__),
                            'AccessibleStairCount.xaml')
        forms.WPFWindow.__init__(self, xaml)
        from System.Windows import (CornerRadius, FontWeights, GridLength,
                                     TextWrapping, Thickness)
        from System.Windows.Controls import (Border, ColumnDefinition, Grid,
                                             StackPanel, TextBlock)
        from System.Windows.Media import BrushConverter, Brushes
        self._CornerRadius = CornerRadius
        self._FontWeights = FontWeights
        self._GridLength = GridLength
        self._Thickness = Thickness
        self._Wrap = TextWrapping.Wrap
        self._Border = Border
        self._ColumnDefinition = ColumnDefinition
        self._Grid = Grid
        self._StackPanel = StackPanel
        self._TextBlock = TextBlock
        self._brush = BrushConverter()
        self._Brushes = Brushes

        self.doc = doc
        self.stairs = _stairs(doc)
        self.result = None
        self.failed_ids = []
        self._ready = False

        try:
            name = os.path.basename(doc.PathName) or u'（未存檔）'
        except Exception:
            name = u'（未存檔）'
        self.documentText.Text = u'{}　樓梯 {} 座'.format(name,
                                                          len(self.stairs))

        self._fill_levels()
        self._fill_parameter_combos()
        self.toleranceText.Text = u'{:.0f}'.format(
            logic.DEFAULT_CHAIN_TOLERANCE_MM)
        self._build_detail_header()

        self.runButton.Click += self.run_clicked
        self.selectButton.Click += self.select_clicked
        self.closeButton.Click += self.close_clicked
        self.markerCombo.SelectionChanged += self.marker_changed

        self._ready = True
        self._fill_marker_values()
        self.statusText.Text = u'設定好上面的條件後按「執行檢核」。'

    # --- population -----------------------------------------------------

    def _fill_levels(self):
        # Listed by elevation, not by name: sorting 1F/2F/10F as text puts
        # 10F between 1F and 2F.
        self.level_ids = []
        best_index = 0
        best_distance = None
        for index, level in enumerate(_levels(self.doc)):
            try:
                elevation = float(level.Elevation) * MM_PER_FOOT
            except Exception:
                elevation = 0.0
            self.refugeCombo.Items.Add(u'{}　（{:+.0f} mm）'.format(
                _element_name(level), elevation))
            self.level_ids.append(_id_value(level.Id))
            if best_distance is None or abs(elevation) < best_distance:
                best_distance = abs(elevation)
                best_index = index
        if self.level_ids:
            # The level nearest ±0 is the usual 避難層 — offered, not assumed.
            self.refugeCombo.SelectedIndex = best_index

    def _fill_parameter_combos(self):
        self.parameter_names = [u'']
        self.buildingCombo.Items.Add(NO_GROUPING)
        self.markerCombo.Items.Add(u'（尚未選擇）')
        for name, sample in _readable_parameters(self.doc, self.stairs):
            label = u'{}　（範例：{}）'.format(name, sample or u'空白')
            self.buildingCombo.Items.Add(label)
            self.markerCombo.Items.Add(label)
            self.parameter_names.append(name)
        self.buildingCombo.SelectedIndex = 0
        self.markerCombo.SelectedIndex = 0

    def _fill_marker_values(self):
        self.markerValueList.Items.Clear()
        self.marker_values = []
        self.value_by_label = {}
        name = self._selected_parameter(self.markerCombo)
        if not name:
            return
        for value, count in _distinct_marker_values(self.doc, self.stairs,
                                                    name):
            label = u'{}　（{} 座）'.format(value, count)
            self.markerValueList.Items.Add(label)
            self.value_by_label[label] = value
            self.marker_values.append(value)

    def _selected_parameter(self, combo):
        index = combo.SelectedIndex
        if index is None or index < 0 or index >= len(self.parameter_names):
            return u''
        return self.parameter_names[index]

    # --- rendering ------------------------------------------------------

    def _colour(self, hex_value):
        try:
            return self._brush.ConvertFromString(hex_value)
        except Exception:
            return self._Brushes.Black

    def _text(self, text, bold=False, colour=None, margin=None):
        block = self._TextBlock()
        block.Text = text or u''
        block.TextWrapping = self._Wrap
        block.Margin = margin or self._Thickness(6, 4, 6, 4)
        if bold:
            block.FontWeight = self._FontWeights.Bold
        if colour:
            block.Foreground = self._colour(colour)
        return block

    def _row_grid(self, values):
        grid = self._Grid()
        for unused_label, width in DETAIL_COLUMNS:
            column = self._ColumnDefinition()
            column.Width = self._GridLength(width)
            grid.ColumnDefinitions.Add(column)
        for index, text in enumerate(values):
            block = self._text(text)
            self._Grid.SetColumn(block, index)
            grid.Children.Add(block)
        return grid

    def _build_detail_header(self):
        self.detailHeader.ColumnDefinitions.Clear()
        self.detailHeader.Children.Clear()
        for index, (label, width) in enumerate(DETAIL_COLUMNS):
            column = self._ColumnDefinition()
            column.Width = self._GridLength(width)
            self.detailHeader.ColumnDefinitions.Add(column)
            block = self._text(label, bold=True,
                               margin=self._Thickness(6, 6, 6, 6))
            self._Grid.SetColumn(block, index)
            self.detailHeader.Children.Add(block)

    def _message(self, text, colour='#42505C'):
        self.resultPanel.Children.Clear()
        self.detailPanel.Children.Clear()
        self.resultPanel.Children.Add(
            self._text(text, colour=colour,
                       margin=self._Thickness(4, 6, 4, 6)))

    def _render(self, result):
        self.resultPanel.Children.Clear()
        self.detailPanel.Children.Clear()

        self.resultPanel.Children.Add(self._text(
            u'{}　｜　共 {} 座樓梯元素，歸併為 {} 組'.format(
                result['rule_label'], result['total_stairs'],
                len(result['chains'])),
            colour='#5B6770', margin=self._Thickness(4, 0, 4, 10)))

        for entry in result['buildings']:
            border = self._Border()
            border.BorderBrush = self._colour('#D8E0EA')
            border.BorderThickness = self._Thickness(1)
            border.CornerRadius = self._CornerRadius(4)
            border.Padding = self._Thickness(12, 10, 12, 10)
            border.Margin = self._Thickness(4, 0, 4, 8)

            stack = self._StackPanel()
            title = self._text(
                u'{}　—　{}'.format(entry['building'],
                                                 entry['outcome']),
                bold=True,
                colour=OUTCOME_COLORS.get(entry['outcome'], '#42505C'),
                margin=self._Thickness(0))
            title.FontSize = 16
            stack.Children.Add(title)

            for line in self._building_lines(entry):
                stack.Children.Add(
                    self._text(line, margin=self._Thickness(0, 4, 0, 0)))

            border.Child = stack
            self.resultPanel.Children.Add(border)

        for chain in result['chains']:
            self.detailPanel.Children.Add(self._row_grid([
                chain['name'] or u'(未命名)',
                u'{}'.format(len(chain['ids'])),
                u'○' if chain['serves_refuge'] else u'—',
                u'○' if chain['designated'] else u'',
                u'、'.join(chain['designation_values']),
                _fmt(chain.get('riser_mm')),
                _fmt(chain.get('tread_mm')),
                _fmt(chain.get('min_run_width_mm')),
                chain['verdict'],
                u'；'.join(chain['failures'] + chain['reviews']),
            ]))

    def _building_lines(self, entry):
        designated = (len(entry['qualified'])
                      + len(entry['designated_failing'])
                      + len(entry['designated_review']))
        lines = [u'通達避難層的樓梯 {} 組，其中已標示為無障礙 {} 組。'.format(
            len(entry['direct']), designated)]
        if entry['outcome'] == logic.BUILDING_PASS:
            lines.append(u'✓ 有 {} 組同時已標示且尺寸符合。'.format(
                len(entry['qualified'])))
        elif entry['outcome'] == logic.BUILDING_NO_STAIR:
            lines.append(u'找不到通達避難層的樓梯，無法就本條檢核。')
        elif entry['outcome'] == logic.BUILDING_UNDECIDED:
            lines.append(u'? 已標示的樓梯尚無法判定，本條未能認定符合。')
        else:
            lines.append(u'✗ 沒有任何一組同時已標示且尺寸符合。')

        for label, chains in ((u'已標示為無障礙但尺寸不符（不計入本條）',
                               entry['designated_failing']),
                              (u'已標示為無障礙但需人工確認',
                               entry['designated_review'])):
            if not chains:
                continue
            lines.append(u'{}：'.format(label))
            for chain in chains[:8]:
                lines.append(u'　{}　{}'.format(
                    chain['name'] or u'(未命名)',
                    u'；'.join(chain['failures'] + chain['reviews'])))
        if not entry['qualified'] and entry['candidates']:
            lines.append(u'未標示但尺寸符合、可考慮指定為無障礙樓梯：{} 組'
                         .format(len(entry['candidates'])))
        if entry['not_direct']:
            lines.append(u'未通達避難層、不列入本條計算：{} 組'.format(
                len(entry['not_direct'])))
        return lines

    # --- handlers -------------------------------------------------------

    def marker_changed(self, sender, args):
        if not self._ready:
            return
        self._fill_marker_values()

    def close_clicked(self, sender, args):
        self.Close()

    def select_clicked(self, sender, args):
        if not self.failed_ids:
            return
        ids = List[DB.ElementId]()
        for value in self.failed_ids:
            ids.Add(DB.ElementId(int(value)))
        revit.uidoc.Selection.SetElementIds(ids)
        self.statusText.Text = u'已選取 {} 座「已標示但尺寸不符」的樓梯。'.format(
            len(self.failed_ids))

    def run_clicked(self, sender, args):
        if not self.appliesCheck.IsChecked:
            self._message(
                u'依 §167 但書，本棟不適用第十章，§167-2 的無障礙樓梯數量規定'
                u'亦不適用，因此沒有可檢核的項目。\n\n'
                u'（但 §167 第 2 項仍要求該類建築物的地面層設置無障礙通路，'
                u'那不在本工具範圍。）', '#B26B00')
            self.failed_ids = []
            self.selectButton.IsEnabled = False
            self.statusText.Text = u'本棟不適用第十章，未進行檢核。'
            return

        marker_name = self._selected_parameter(self.markerCombo)
        if not marker_name:
            forms.alert(u'請先選擇「無障礙標示參數」。', title=TITLE)
            return
        picked = [self.value_by_label[label]
                  for label in self.markerValueList.SelectedItems
                  if label in self.value_by_label]
        if not picked:
            forms.alert(u'請至少選一個代表無障礙樓梯的值。', title=TITLE)
            return

        index = self.refugeCombo.SelectedIndex
        if index is None or index < 0:
            forms.alert(u'請選擇避難層。', title=TITLE)
            return
        refuge_level_id = self.level_ids[index]

        try:
            tolerance = float((self.toleranceText.Text or u'').strip())
        except ValueError:
            forms.alert(u'樓梯合併容差必須是數字。', title=TITLE)
            return
        if tolerance <= 0:
            forms.alert(u'樓梯合併容差必須大於 0。', title=TITLE)
            return

        rule = logic.RULE_APARTMENT if self.ruleApartmentRadio.IsChecked \
            else logic.RULE_GENERAL
        building_name = self._selected_parameter(self.buildingCombo)

        # Re-read the model on every run: the answer must reflect the document
        # as it is now, not as it was when the window opened.
        self.stairs = _stairs(self.doc)
        records = _collect(self.doc, self.stairs, marker_name, set(picked),
                           building_name)
        result = logic.evaluate(records, rule=rule,
                                refuge_level_id=refuge_level_id,
                                tolerance_mm=tolerance)
        self.result = result
        self.failed_ids = list(result['failed_ids'])
        self._render(result)
        self.selectButton.IsEnabled = bool(self.failed_ids)

        outcomes = [entry['outcome'] for entry in result['buildings']]
        if outcomes and all(value == logic.BUILDING_PASS for value in outcomes):
            self.statusText.Text = u'檢核完成：全部符合 §167-2。'
        else:
            self.statusText.Text = (
                u'檢核完成：{} 棟中有 {} 棟未認定符合。'.format(
                    len(outcomes),
                    len([v for v in outcomes if v != logic.BUILDING_PASS])))


def main():
    doc = revit.doc
    if doc is None:
        forms.alert(u'請先開啟 Revit 專案文件，再執行檢核。',
                    title=TITLE, exitscript=True)
    if not _stairs(doc):
        forms.alert(u'這個專案沒有樓梯（Stairs）元素。', title=TITLE)
        return
    AccessibleStairWindow(doc).ShowDialog()


try:
    main()
except Exception as error:
    forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
