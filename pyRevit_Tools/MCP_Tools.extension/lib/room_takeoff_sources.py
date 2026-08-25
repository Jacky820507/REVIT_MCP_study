# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Collect auditable room quantities from host and selected Revit links."""

import room_takeoff_sources_logic as logic


FT_TO_M = 0.3048
SQFT_TO_SQM = FT_TO_M * FT_TO_M


def _id_value(value):
    target = getattr(value, 'Id', value)
    for name in ('Value', 'IntegerValue'):
        try:
            return int(getattr(target, name))
        except Exception:
            pass
    return int(target)


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value).strip()
    except Exception:
        return str(value).strip()


def _parameter_double(element, built_in):
    try:
        parameter = element.get_Parameter(built_in)
    except Exception:
        parameter = None
    if parameter is None:
        return None
    try:
        return float(parameter.AsDouble())
    except Exception:
        return None


def _parameter_text(element, built_in):
    try:
        parameter = element.get_Parameter(built_in)
    except Exception:
        parameter = None
    if parameter is None:
        return u''
    for reader in ('AsString', 'AsValueString'):
        try:
            value = _text(getattr(parameter, reader)())
        except Exception:
            value = u''
        if value:
            return value
    return u''


def _room_name(room, DB=None):
    if DB is not None:
        value = _parameter_text(
            room, DB.BuiltInParameter.ROOM_NAME)
        if value:
            return value
    try:
        return _text(room.Name)
    except Exception:
        return u''


def _room_number(room):
    try:
        return _text(room.Number)
    except Exception:
        return u''


def _boundary_quantity(room, DB):
    options = DB.SpatialElementBoundaryOptions()
    options.SpatialElementBoundaryLocation = (
        DB.SpatialElementBoundaryLocation.Finish)
    loops = room.GetBoundarySegments(options)
    perimeter_ft = 0.0
    loop_count = 0
    segment_count = 0
    points = []
    for loop in loops or []:
        loop_count += 1
        for segment in loop or []:
            curve = segment.GetCurve()
            if curve is None:
                continue
            perimeter_ft += float(curve.Length)
            segment_count += 1
            try:
                tessellated = list(curve.Tessellate())
            except Exception:
                tessellated = [curve.GetEndPoint(0), curve.GetEndPoint(1)]
            for point in tessellated:
                points.append((float(point.X), float(point.Y)))
    return perimeter_ft * FT_TO_M, loop_count, segment_count, points


def _room_dimensions(room, boundary_points):
    length_ft, width_ft = logic.oriented_dimensions(boundary_points)
    if length_ft and width_ft:
        return (
            length_ft * FT_TO_M,
            width_ft * FT_TO_M,
            u'Finish boundary 最小旋轉包絡',
        )
    try:
        box = room.get_BoundingBox(None)
    except Exception:
        box = None
    if box is None:
        return None, None, u''
    length = max(0.0, float(box.Max.X - box.Min.X)) * FT_TO_M
    width = max(0.0, float(box.Max.Y - box.Min.Y)) * FT_TO_M
    return (
        (length or None), (width or None),
        u'軸對齊 BoundingBox 備援（請稽核旋轉房間）')


def collect_document_rooms(source_doc, source_key, source_label,
                           allowed_level_ids=None, link_instance_id=None):
    """Collect one selected document using Finish boundary quantities."""
    from Autodesk.Revit import DB

    rooms = (DB.FilteredElementCollector(source_doc)
             .OfCategory(DB.BuiltInCategory.OST_Rooms)
             .WhereElementIsNotElementType())
    records = []
    skipped = []
    for room in rooms:
        local_id = _id_value(room.Id)
        level_id = _id_value(room.LevelId)
        if not logic.level_is_allowed(level_id, allowed_level_ids):
            continue
        number = _room_number(room)
        name = _room_name(room, DB)
        area_ft2 = _parameter_double(
            room, DB.BuiltInParameter.ROOM_AREA)
        if area_ft2 is None:
            try:
                area_ft2 = float(room.Area)
            except Exception:
                area_ft2 = 0.0
        if not number or not area_ft2 or area_ft2 <= 0.0:
            skipped.append({
                'ElementId': local_id,
                'CompositeId': logic.composite_room_id(
                    source_key, local_id),
                'Number': number,
                'Name': name,
                'SourceKey': source_key,
                'SourceLabel': source_label,
                'Reason': u'房號空白或房間未放置／未封閉',
            })
            continue
        try:
            (perimeter_m, loop_count, segment_count,
             boundary_points) = _boundary_quantity(room, DB)
            boundary_warning = u''
        except Exception as error:
            perimeter_m = 0.0
            loop_count = 0
            segment_count = 0
            boundary_points = []
            boundary_warning = u'Finish boundary 讀取失敗：{}'.format(error)

        level = source_doc.GetElement(room.LevelId)
        level_name = _text(getattr(level, 'Name', u''))
        length_m, width_m, dimension_source = _room_dimensions(
            room, boundary_points)
        height_ft = _parameter_double(
            room, DB.BuiltInParameter.ROOM_HEIGHT)
        if not height_ft:
            try:
                height_ft = float(room.UnboundedHeight)
            except Exception:
                height_ft = None
        record = {
            'ElementId': local_id,
            'LocalElementId': local_id,
            'CompositeId': logic.composite_room_id(source_key, local_id),
            'SourceKey': source_key,
            'SourceLabel': source_label,
            'LinkInstanceId': link_instance_id,
            'LevelId': level_id,
            'Level': level_name,
            'Number': number,
            'Name': name,
            'PerimeterM': float(perimeter_m),
            'AreaM2': float(area_ft2) * SQFT_TO_SQM,
            'LengthM': length_m,
            'WidthM': width_m,
            'DimensionSource': dimension_source,
            'HeightM': (
                float(height_ft) * FT_TO_M if height_ft else None),
            'BoundaryLoopCount': loop_count,
            'BoundarySegmentCount': segment_count,
            'BoundaryWarning': boundary_warning,
        }
        records.append(record)
    records.sort(key=logic.room_sort_key)
    return records, skipped


def collect_selected_rooms(host_doc, options):
    """Collect the shared UI selection and retain per-source identity."""
    import takeoff_entry

    records = []
    skipped = []
    source_rows = []
    for (source_key, source_label, source_doc, allowed_level_ids,
         link_instance_id) in takeoff_entry.iter_sources(host_doc, options):
        source_records, source_skipped = collect_document_rooms(
            source_doc,
            source_key,
            source_label,
            allowed_level_ids=allowed_level_ids,
            link_instance_id=link_instance_id)
        records.extend(source_records)
        skipped.extend(source_skipped)
        source_rows.append({
            'source_key': source_key,
            'source_label': source_label,
            'source_doc': source_doc,
            'allowed_level_ids': allowed_level_ids,
            'link_instance_id': link_instance_id,
            'records': source_records,
        })
    records.sort(key=logic.room_sort_key)
    return {
        'Rooms': records,
        'SkippedRooms': skipped,
        'Sources': source_rows,
        'Parameters': {
            'BoundaryLocation': 'Finish',
            'SourceCount': len(source_rows),
        },
    }


def space_standalone_tables(records, skipped=None):
    """Return the three standard workbook table payloads."""
    detail_headers = [
        u'來源Key', u'來源模型', u'連結實體Id', u'ElementId', u'複合識別',
        u'樓層', u'房號', u'房名', u'Finish周長(m)', u'面積(m2)',
        u'邊界迴圈', u'邊界段', u'備註',
    ]
    detail_rows = []
    for record in records or []:
        detail_rows.append([
            record.get('SourceKey'), record.get('SourceLabel'),
            record.get('LinkInstanceId'), record.get('LocalElementId'),
            record.get('CompositeId'), record.get('Level'),
            record.get('Number'), record.get('Name'),
            record.get('PerimeterM'), record.get('AreaM2'),
            record.get('BoundaryLoopCount'),
            record.get('BoundarySegmentCount'),
            record.get('BoundaryWarning'),
        ])
    last_row = max(2, len(detail_rows) + 1)
    formula_headers = [u'項目', u'公式／依據', u'數值', u'單位']
    formula_rows = [
        [u'有效房間數', u'數量明細逐房列數',
         u"=COUNTA('數量明細'!E2:E{})".format(last_row), u'間'],
        [u'Finish周長合計', u'GetBoundarySegments(Finish) 全迴圈加總',
         u"=SUM('數量明細'!I2:I{})".format(last_row), u'm'],
        [u'面積合計', u'Revit ROOM_AREA',
         u"=SUM('數量明細'!J2:J{})".format(last_row), u'm2'],
    ]
    audit_headers = [
        u'狀態', u'來源Key', u'複合識別', u'房號', u'訊息',
    ]
    audit_rows = []
    for record in records or []:
        warning = _text(record.get('BoundaryWarning'))
        audit_rows.append([
            u'WARN' if warning else u'PASS',
            record.get('SourceKey'), record.get('CompositeId'),
            record.get('Number'), warning or u'Finish boundary 已取得',
        ])
    for record in skipped or []:
        audit_rows.append([
            u'SKIP', record.get('SourceKey'), record.get('CompositeId'),
            record.get('Number'), record.get('Reason'),
        ])
    return {
        'detail_headers': detail_headers,
        'detail_rows': detail_rows,
        'formula_headers': formula_headers,
        'formula_rows': formula_rows,
        'audit_headers': audit_headers,
        'audit_rows': audit_rows,
    }
