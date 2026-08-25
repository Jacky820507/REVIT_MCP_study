# -*- coding: utf-8 -*-
__title__ = u'停車位\n編號'
__author__ = 'RevitMCP'

import os

from Autodesk.Revit import DB
from pyrevit import forms, revit, script

from parking_numbering import rotate_to_start, sort_bays


TITLE = u'停車位編號'
MM_PER_FOOT = 304.8

VEHICLES = [
    (u'汽車停車位', 'car'),
    (u'機車停車位', 'motorcycle'),
]

ORDERS = [
    (u'由上到下，每排左到右', 'y', True, False, False),
    (u'由上到下，每排右到左', 'y', True, True, False),
    (u'由下到上，每排左到右', 'y', False, False, False),
    (u'由下到上，每排右到左', 'y', False, True, False),
    (u'由左到右，每欄上到下', 'x', False, True, False),
    (u'由左到右，每欄下到上', 'x', False, False, False),
    (u'由右到左，每欄上到下', 'x', True, True, False),
    (u'由右到左，每欄下到上', 'x', True, False, False),
    (u'蛇行：由上到下，首排左到右', 'y', True, False, True),
    (u'蛇行：由上到下，首排右到左', 'y', True, True, True),
    (u'蛇行：由下到上，首排左到右', 'y', False, False, True),
    (u'蛇行：由下到上，首排右到左', 'y', False, True, True),
    (u'蛇行：由左到右，首欄上到下', 'x', False, True, True),
    (u'蛇行：由左到右，首欄下到上', 'x', False, False, True),
    (u'蛇行：由右到左，首欄上到下', 'x', True, True, True),
    (u'蛇行：由右到左，首欄下到上', 'x', True, False, True),
]


def _id_value(element_id):
    if element_id is None:
        return -1
    try:
        return int(element_id.Value)
    except Exception:
        try:
            return int(element_id.IntegerValue)
        except Exception:
            return -1


def _element_name(element):
    try:
        return DB.Element.Name.GetValue(element) or u''
    except Exception:
        try:
            return element.Name or u''
        except Exception:
            return u''


def _parking_names(element):
    family_name = u''
    type_name = u''
    try:
        symbol = element.Symbol
        family_name = _element_name(symbol.Family)
        type_name = _element_name(symbol)
    except Exception:
        type_element = revit.doc.GetElement(element.GetTypeId())
        type_name = _element_name(type_element) if type_element else u''
    return family_name, type_name, _element_name(element)


def _parking_kind(element):
    names = _parking_names(element)
    combined = u' '.join(names).lower()
    motorcycle_words = (u'機車', u'motorcycle', u'scooter', u'moto')
    bus_words = (u'大客車', u'巴士', u'客車', u'bus')
    car_words = (u'汽車', u'小車', u'大車', u'car', u'auto', u'vehicle')
    if any(word in combined for word in motorcycle_words):
        return 'motorcycle'
    if any(word in combined for word in bus_words):
        return 'bus'
    if any(word in combined for word in car_words):
        return 'car'
    return 'unknown'


def _level_id(element):
    try:
        value = _id_value(element.LevelId)
        if value >= 0:
            return value
    except Exception:
        pass

    parameter_names = (
        'INSTANCE_REFERENCE_LEVEL_PARAM',
        'INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM',
        'FAMILY_LEVEL_PARAM',
        'SCHEDULE_LEVEL_PARAM',
        'LEVEL_PARAM',
    )
    for name in parameter_names:
        built_in = getattr(DB.BuiltInParameter, name, None)
        if built_in is None:
            continue
        try:
            parameter = element.get_Parameter(built_in)
            if parameter and parameter.StorageType == DB.StorageType.ElementId:
                value = _id_value(parameter.AsElementId())
                if value >= 0:
                    return value
        except Exception:
            pass
    return -1


def _location(element):
    point = None
    try:
        if isinstance(element.Location, DB.LocationPoint):
            point = element.Location.Point
    except Exception:
        pass
    if point is None:
        try:
            box = element.get_BoundingBox(None)
            if box:
                point = DB.XYZ(
                    (box.Min.X + box.Max.X) / 2.0,
                    (box.Min.Y + box.Max.Y) / 2.0,
                    (box.Min.Z + box.Max.Z) / 2.0)
        except Exception:
            pass
    if point is None:
        return None

    # Use the active plan's visual axes so left/right and top/bottom still
    # match the screen when Project North or the view is rotated.
    view = revit.doc.ActiveView
    return (point.DotProduct(view.RightDirection),
            point.DotProduct(view.UpDirection))


def _parameter(element, parameter_name):
    parameter = element.LookupParameter(parameter_name)
    if not parameter and parameter_name.lower() in (u'備註', 'comments'):
        parameter = element.get_Parameter(
            DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    return parameter


def _selected_parking_id():
    ids = list(revit.uidoc.Selection.GetElementIds())
    if len(ids) != 1:
        return u''
    element = revit.doc.GetElement(ids[0])
    if not element or not element.Category:
        return u''
    if _id_value(element.Category.Id) != int(
            DB.BuiltInCategory.OST_Parking):
        return u''
    return str(_id_value(element.Id))


def _collect(level_id, vehicle_kind):
    elements = (DB.FilteredElementCollector(revit.doc)
                .OfCategory(DB.BuiltInCategory.OST_Parking)
                .WhereElementIsNotElementType()
                .ToElements())
    bays = []
    unknown_count = 0
    no_location_count = 0
    for element in elements:
        if _level_id(element) != level_id:
            continue
        kind = _parking_kind(element)
        if kind == 'unknown':
            unknown_count += 1
            continue
        if kind != vehicle_kind:
            continue
        location = _location(element)
        if not location:
            no_location_count += 1
            continue
        family_name, type_name, element_name = _parking_names(element)
        bays.append({
            'id': _id_value(element.Id),
            'element': element,
            'x': location[0],
            'y': location[1],
            'family': family_name,
            'type': type_name or element_name,
        })
    return bays, unknown_count, no_location_count


class ParkingNumberingWindow(forms.WPFWindow):
    def __init__(self, levels):
        xaml = os.path.join(os.path.dirname(__file__), 'ParkingNumbering.xaml')
        forms.WPFWindow.__init__(self, xaml)
        self.levels = levels
        self.result = None
        for label, unused in VEHICLES:
            self.vehicleCombo.Items.Add(label)
        for level in levels:
            self.levelCombo.Items.Add(_element_name(level))
        for order in ORDERS:
            self.orderCombo.Items.Add(order[0])
        self.vehicleCombo.SelectedIndex = 0
        self.levelCombo.SelectedIndex = 0
        self.orderCombo.SelectedIndex = 0
        self.startElementText.Text = _selected_parking_id()

    def cancel_clicked(self, sender, args):
        self.Close()

    def preview_clicked(self, sender, args):
        try:
            start_number = int(self.startNumberText.Text.strip())
            tolerance = float(self.toleranceText.Text.strip())
            if tolerance <= 0:
                raise ValueError()
        except Exception:
            forms.alert(u'起始編號必須是整數，容差必須是大於 0 的數字。',
                        title=TITLE)
            return
        parameter_name = self.parameterText.Text.strip()
        if not parameter_name:
            forms.alert(u'請輸入要寫入的參數名稱。', title=TITLE)
            return
        start_element = self.startElementText.Text.strip()
        if start_element:
            try:
                int(start_element)
            except Exception:
                forms.alert(u'起始 Element ID 必須是整數或留空。', title=TITLE)
                return
        self.result = {
            'vehicle': VEHICLES[self.vehicleCombo.SelectedIndex],
            'level': self.levels[self.levelCombo.SelectedIndex],
            'start_number': start_number,
            'parameter_name': parameter_name,
            'order': ORDERS[self.orderCombo.SelectedIndex],
            'tolerance_mm': tolerance,
            'start_element': start_element,
        }
        self.Close()


class WarningSwallower(DB.IFailuresPreprocessor):
    def PreprocessFailures(self, failures_accessor):
        for failure in failures_accessor.GetFailureMessages():
            if failure.GetSeverity() == DB.FailureSeverity.Warning:
                failures_accessor.DeleteWarning(failure)
        return DB.FailureProcessingResult.Continue


def _preview(rows, settings, unknown_count, no_location_count):
    output = script.get_output()
    output.print_md(u'## 停車位編號 dry-run 預覽')
    output.print_md(
        u'樓層：**{}**　車種：**{}**　排列：**{}**　寫入：`{}`'
        .format(_element_name(settings['level']), settings['vehicle'][0],
                settings['order'][0], settings['parameter_name']))
    table = []
    writable = 0
    for index, bay in enumerate(rows):
        parameter = _parameter(bay['element'], settings['parameter_name'])
        status = u'可寫入'
        if not parameter:
            status = u'查無參數'
        elif parameter.IsReadOnly:
            status = u'唯讀'
        elif parameter.StorageType != DB.StorageType.String:
            status = u'非文字參數'
        else:
            writable += 1
        table.append([
            str(index + 1),
            str(settings['start_number'] + index),
            output.linkify(bay['element'].Id),
            bay['family'],
            bay['type'],
            str(bay.get('_group', '')),
            status,
        ])
    output.print_table(
        table_data=table,
        columns=[u'順序', u'新編號', u'Element ID', u'族群', u'類型',
                 u'排／欄', u'參數狀態'])
    lines = [
        u'符合條件：{} 個'.format(len(rows)),
        u'可寫入：{} 個'.format(writable),
    ]
    if unknown_count:
        lines.append(u'同樓層未能辨識車種：{} 個（已略過）'.format(unknown_count))
    if no_location_count:
        lines.append(u'無座標：{} 個（已略過）'.format(no_location_count))
    lines.append(u'編號範圍：{} ～ {}'.format(
        settings['start_number'],
        settings['start_number'] + len(rows) - 1))
    return u'\n'.join(lines), writable


def _apply(rows, settings):
    transaction = DB.Transaction(revit.doc, u'停車位編號')
    transaction.Start()
    options = transaction.GetFailureHandlingOptions()
    options.SetFailuresPreprocessor(WarningSwallower())
    transaction.SetFailureHandlingOptions(options)
    successes = []
    try:
        for index, bay in enumerate(rows):
            number = str(settings['start_number'] + index)
            parameter = _parameter(bay['element'], settings['parameter_name'])
            if not parameter.Set(number):
                raise RuntimeError(
                    u'Element ID {} 的參數拒絕寫入'.format(bay['id']))
            successes.append((bay['id'], number))
        transaction.Commit()
        return successes, None
    except Exception as error:
        transaction.RollBack()
        return [], u'{}'.format(error)


def main():
    if revit.doc is None:
        forms.alert(u'請先開啟 Revit 專案文件，再執行停車位編號。',
                    title=TITLE, exitscript=True)

    if not isinstance(revit.doc.ActiveView, DB.ViewPlan):
        forms.alert(
            u'請先切換到平面視圖，再執行停車位編號。\n\n'
            u'左右與上下方向會依目前平面視圖判定。',
            title=TITLE, exitscript=True)

    levels = sorted(
        DB.FilteredElementCollector(revit.doc)
        .OfClass(DB.Level)
        .WhereElementIsNotElementType()
        .ToElements(),
        key=lambda level: (level.Elevation, _element_name(level)))
    if not levels:
        forms.alert(u'目前專案沒有可用樓層。', title=TITLE, exitscript=True)

    window = ParkingNumberingWindow(levels)
    window.ShowDialog()
    settings = window.result
    if not settings:
        return

    bays, unknown_count, no_location_count = _collect(
        _id_value(settings['level'].Id), settings['vehicle'][1])
    if not bays:
        forms.alert(
            u'所選樓層沒有可辨識的{}。\n\n'
            u'請確認停車位位於 Parking 類別，且族群或類型名稱含有車種關鍵字。'
            .format(settings['vehicle'][0]),
            title=TITLE)
        return

    order = settings['order']
    tolerance_feet = settings['tolerance_mm'] / MM_PER_FOOT
    rows = sort_bays(
        bays, order[1], order[2], order[3], order[4], tolerance_feet)
    try:
        rows = rotate_to_start(rows, settings['start_element'])
    except ValueError:
        forms.alert(
            u'指定的起始 Element ID 不在所選樓層與車種內，未執行編號。',
            title=TITLE)
        return

    summary, writable = _preview(
        rows, settings, unknown_count, no_location_count)
    if writable != len(rows):
        forms.alert(
            u'【dry-run 預覽】\n\n{}\n\n'
            u'部分停車位的目標參數不存在、唯讀或不是文字參數。\n'
            u'為避免跳號，本次不提供套用；請先修正完整預覽中的參數狀態。'
            .format(summary), title=TITLE)
        return
    if not forms.alert(
            u'【dry-run 預覽】\n\n{}\n\n'
            u'完整順序已列在 pyRevit 輸出視窗。\n'
            u'確定要寫入目前模型嗎？'.format(summary),
            title=TITLE, yes=True, no=True):
        return

    successes, error = _apply(rows, settings)
    if error:
        forms.alert(
            u'寫入失敗，交易已完整回復，模型沒有留下部分編號。\n\n{}'
            .format(error), title=TITLE)
        return
    forms.alert(u'已寫入 {} 個停車位。'.format(len(successes)), title=TITLE)


try:
    main()
except Exception as error:
    forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
