# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Resolve auditable room heights for scaffold takeoff."""

from collections import defaultdict
import re

import scaffold_height_logic
try:
    reload(scaffold_height_logic)
except Exception:
    pass

from Autodesk.Revit.DB import (
    BuiltInCategory,
    BuiltInParameter,
    Category,
    ElementCategoryFilter,
    FilteredElementCollector,
    FindReferenceTarget,
    Level,
    ReferenceIntersector,
    View3D,
    XYZ,
)
FT_TO_M = 0.3048
M_TO_FT = 1.0 / FT_TO_M
HEIGHT_STEP_M = 0.05
MIN_HEIGHT_M = 1.50
MAX_HEIGHT_M = 30.00
BOTTOM_RAY_ORIGIN_ABOVE_M = 0.75
BOTTOM_MAX_DROP_M = 5.00
BOTTOM_MAX_RISE_M = 0.30
TOP_SURFACE_TOLERANCE_M = 0.05
SAME_LEVEL_HEIGHT_TOLERANCE_M = 0.10
SAME_LEVEL_DOMINANCE_RATIO = 0.75
CEILING_FINISH_PARAMETER_NAMES = (
    u'天花板塗層', u'天花板', u'天花塗層', u'天花',
    'Ceiling Finish', 'CeilingFinish',
)


def _id_value(element_id):
    if element_id is None:
        return 0
    try:
        return int(element_id.IntegerValue)
    except Exception:
        try:
            return int(element_id.Value)
        except Exception:
            return 0


def _name(element):
    if element is None:
        return u''
    try:
        return u'{}'.format(element.Name)
    except Exception:
        return u''


def _parameter(element, built_in):
    if element is None:
        return None
    try:
        return element.get_Parameter(built_in)
    except Exception:
        return None


def _double_parameter(element, built_in):
    parameter = _parameter(element, built_in)
    if parameter is None:
        return None
    try:
        value = parameter.AsDouble()
        return value if value is not None else None
    except Exception:
        return None


def _lookup_text(element, names):
    if element is None:
        return u''
    for name in names:
        try:
            parameter = element.LookupParameter(name)
        except Exception:
            parameter = None
        if parameter is None:
            continue
        for accessor in ('AsString', 'AsValueString'):
            try:
                value = getattr(parameter, accessor)()
            except Exception:
                value = None
            if value:
                return u'{}'.format(value).strip()
    return u''


def _normalize_ceiling_code(value):
    text = re.sub(r'\s+', '', u'{}'.format(value or u'')).upper()
    match = re.match(r'^C0*(\d+)([A-Z]?)$', text)
    if not match:
        return u''
    return u'C{}{}'.format(int(match.group(1)), match.group(2) or u'')


def _ceiling_codes_from_text(value):
    result = []
    for match in re.finditer(
            r'(?<![A-Z0-9])(C\s*0*\d+[A-Z]?)(?![A-Z0-9])',
            u'{}'.format(value or u''), re.I):
        code = _normalize_ceiling_code(match.group(1))
        if code and code not in result:
            result.append(code)
    return result


def _room_ceiling_codes(room):
    return _ceiling_codes_from_text(
        _lookup_text(room, CEILING_FINISH_PARAMETER_NAMES))


def _ceiling_codes(doc, ceiling):
    evidence = [_name(ceiling)]
    try:
        ceiling_type = doc.GetElement(ceiling.GetTypeId())
    except Exception:
        ceiling_type = None
    evidence.append(_name(ceiling_type))
    evidence.append(_lookup_text(
        ceiling_type, (u'類型標記', u'類型註記', 'Type Mark')))
    result = []
    for value in evidence:
        for code in _ceiling_codes_from_text(value):
            if code not in result:
                result.append(code)
    return result


def _element_id_parameter(element, built_in):
    parameter = _parameter(element, built_in)
    if parameter is None:
        return 0
    try:
        return _id_value(parameter.AsElementId())
    except Exception:
        return 0


def _valid_height(value):
    return value is not None and MIN_HEIGHT_M <= value <= MAX_HEIGHT_M


def _snap_height(value):
    if not _valid_height(value):
        return None
    return round(round(float(value) / HEIGHT_STEP_M) * HEIGHT_STEP_M, 2)


def _bbox(element):
    try:
        return element.get_BoundingBox(None)
    except Exception:
        return None


def _bbox_overlap_xy(left, right):
    if left is None or right is None:
        return False
    return not (
        left.Max.X <= right.Min.X or left.Min.X >= right.Max.X or
        left.Max.Y <= right.Min.Y or left.Min.Y >= right.Max.Y)


def _bbox_overlap_ratio_xy(room_box, element_box):
    if room_box is None or element_box is None:
        return 0.0
    room_width = max(0.0, room_box.Max.X - room_box.Min.X)
    room_depth = max(0.0, room_box.Max.Y - room_box.Min.Y)
    room_area = room_width * room_depth
    if room_area <= 0.0:
        return 0.0
    overlap_width = max(
        0.0, min(room_box.Max.X, element_box.Max.X) -
        max(room_box.Min.X, element_box.Min.X))
    overlap_depth = max(
        0.0, min(room_box.Max.Y, element_box.Max.Y) -
        max(room_box.Min.Y, element_box.Min.Y))
    return (overlap_width * overlap_depth) / room_area


def _bbox_stack_overlap_ratio_xy(left, right):
    if left is None or right is None:
        return 0.0
    left_area = max(0.0, left.Max.X - left.Min.X) * max(
        0.0, left.Max.Y - left.Min.Y)
    right_area = max(0.0, right.Max.X - right.Min.X) * max(
        0.0, right.Max.Y - right.Min.Y)
    smaller_area = min(left_area, right_area)
    if smaller_area <= 0.0:
        return 0.0
    overlap_width = max(
        0.0, min(left.Max.X, right.Max.X) - max(left.Min.X, right.Min.X))
    overlap_depth = max(
        0.0, min(left.Max.Y, right.Max.Y) - max(left.Min.Y, right.Min.Y))
    return (overlap_width * overlap_depth) / smaller_area


def _level_catalog(doc):
    room_level_ids = set()
    try:
        project_rooms = (FilteredElementCollector(doc)
                         .OfCategory(BuiltInCategory.OST_Rooms)
                         .WhereElementIsNotElementType())
        for room in project_rooms:
            level_id = _id_value(room.LevelId)
            if level_id:
                room_level_ids.add(level_id)
    except Exception:
        pass
    entries = []
    by_id = {}
    for level in FilteredElementCollector(doc).OfClass(Level):
        try:
            entry = {
                'id': _id_value(level.Id),
                'name': _name(level),
                'elevation_m': level.Elevation * FT_TO_M,
                'has_room': _id_value(level.Id) in room_level_ids,
            }
        except Exception:
            continue
        entries.append(entry)
        by_id[entry['id']] = entry
    entries.sort(key=lambda item: item['elevation_m'])
    return {'entries': entries, 'by_id': by_id}


def _level_series(value):
    match = re.match(r'^\s*([A-Z]+)\s*-', u'{}'.format(value or u'').upper())
    return match.group(1) if match else u''


def _floor_thickness_m(doc, floor):
    value = _double_parameter(floor, BuiltInParameter.FLOOR_ATTR_THICKNESS_PARAM)
    if not value:
        try:
            floor_type = doc.GetElement(floor.GetTypeId())
        except Exception:
            floor_type = None
        value = _double_parameter(
            floor_type, BuiltInParameter.FLOOR_ATTR_THICKNESS_PARAM)
    if not value:
        box = _bbox(floor)
        if box is not None:
            value = box.Max.Z - box.Min.Z
    thickness = value * FT_TO_M if value else None
    if thickness is not None and 0.05 <= thickness <= 1.50:
        return thickness
    return None


def _floor_level_id(floor):
    try:
        value = _id_value(floor.LevelId)
        if value > 0:
            return value
    except Exception:
        pass
    for built_in in (BuiltInParameter.LEVEL_PARAM,
                     BuiltInParameter.SCHEDULE_LEVEL_PARAM):
        value = _element_id_parameter(floor, built_in)
        if value > 0:
            return value
    return 0


def _floor_thickness_by_level(doc):
    grouped = defaultdict(list)
    floors = (FilteredElementCollector(doc)
              .OfCategory(BuiltInCategory.OST_Floors)
              .WhereElementIsNotElementType())
    for floor in floors:
        thickness = _floor_thickness_m(doc, floor)
        level_id = _floor_level_id(floor)
        if thickness and level_id:
            try:
                floor_type = doc.GetElement(floor.GetTypeId())
            except Exception:
                floor_type = None
            evidence = u'{} {}'.format(_name(floor), _name(floor_type)).upper()
            structural = bool(
                re.search(r'(^|[_\s-])RC([_\s-]|$)', evidence) or
                u'結構' in evidence or u'STRUCT' in evidence)
            grouped[level_id].append((thickness, structural))
    result = {}
    for level_id, values in grouped.items():
        buckets = {}
        for value, structural in values:
            key = round(value, 2)
            if key not in buckets:
                buckets[key] = {'count': 0, 'structural_count': 0}
            buckets[key]['count'] += 1
            if structural:
                buckets[key]['structural_count'] += 1
        selected = sorted(
            buckets.items(),
            key=lambda item: (
                -item[1]['structural_count'], -item[1]['count'], item[0]))[0][0]
        result[level_id] = selected
    return result


def _room_base(room, levels):
    level = levels['by_id'].get(_id_value(room.LevelId))
    if level is None:
        box = _bbox(room)
        return (
            box.Min.Z * FT_TO_M if box is not None else None,
            [u'找不到房間基準樓層，暫以 Room bbox 底部作高度基準'],
        )
    offset = _double_parameter(room, BuiltInParameter.ROOM_LOWER_OFFSET) or 0.0
    offset_m = offset * FT_TO_M
    warnings = []
    # Negative Room lower offsets commonly extend the spatial volume below the
    # finish floor. They are not a construction clear-height datum.
    if offset_m < -0.01:
        warnings.append(
            u'Room 基準偏移 {} m 僅作空間體積延伸；淨高以樓層標高起算'.format(
                u'%.2f' % float(offset_m)))
        offset_m = 0.0
    return level['elevation_m'] + offset_m, warnings


def _room_lower_offset_m(room):
    value = _double_parameter(room, BuiltInParameter.ROOM_LOWER_OFFSET)
    return value * FT_TO_M if value is not None else 0.0


def _room_upper_level(room, levels, base_m):
    upper_id = _element_id_parameter(room, BuiltInParameter.ROOM_UPPER_LEVEL)
    upper = levels['by_id'].get(upper_id)
    if upper is not None and upper['elevation_m'] > base_m + 0.50:
        return upper
    candidates = [candidate for candidate in levels['entries']
                  if candidate['elevation_m'] > base_m + 1.50]
    current = levels['by_id'].get(_id_value(room.LevelId))
    current_series = _level_series(current.get('name')) if current else u''
    if current_series:
        same_series_rooms = [
            candidate for candidate in candidates
            if (_level_series(candidate.get('name')) == current_series and
                candidate.get('has_room'))]
        if same_series_rooms:
            return same_series_rooms[0]
        same_series = [candidate for candidate in candidates
                       if _level_series(candidate.get('name')) == current_series]
        if same_series:
            return same_series[0]
    room_levels = [candidate for candidate in candidates
                   if candidate.get('has_room')]
    if room_levels:
        return room_levels[0]
    if candidates:
        return candidates[0]
    return None


def _nearest_level_fallback(room, levels, base_m):
    """Return one deterministic next level for a level-based last resort.

    Room Upper Limit is useful metadata, but it is also the setting most
    likely to be left unchanged when a room becomes open-to-above.  Physical
    ceiling/floor rays are allowed to override it; if no physical object is
    found, use the nearest level in the same level series so rooms on one
    floor do not acquire different nominal heights from stale Upper Limits.
    """
    current = levels['by_id'].get(_id_value(room.LevelId))
    current_series = _level_series(current.get('name')) if current else u''
    candidates = [candidate for candidate in levels['entries']
                  if candidate['elevation_m'] > base_m + 1.50]
    if current_series:
        same_series = [candidate for candidate in candidates
                       if _level_series(candidate.get('name')) == current_series]
        if same_series:
            return same_series[0]
    return candidates[0] if candidates else None


def _nominal_slab_height(room, levels, thickness_by_level, base_m,
                         upper_override=None, upper_evidence=None):
    upper = upper_override or _nearest_level_fallback(room, levels, base_m)
    if upper is None:
        return None
    thickness = thickness_by_level.get(upper['id'])
    # This is the last fallback only.  If no ceiling or physical upper floor
    # was found by the ray, the requested datum is the level-to-level height;
    # do not subtract a guessed slab thickness a second time.
    raw = upper['elevation_m'] - base_m
    warnings = []
    if upper_evidence:
        warnings.append(upper_evidence)
    source = 'level-height-fallback'
    label = u'樓層高度 fallback：{}'.format(upper['name'])
    if thickness:
        warnings.append(
            u'未偵測到上層天花或樓板，最後採樓層高度；上層板厚 {} m 僅供參考'.format(
                u'%.2f' % float(thickness)))
    else:
        warnings.append(u'找不到上層代表樓板厚度，暫採樓層到樓層高度')
    return {
        'height': _snap_height(raw),
        'raw_height': raw,
        'source': source,
        'label': label,
        'target_level': upper['name'],
        'slab_thickness': thickness,
        'warnings': warnings,
    }


def _top_surface_family(info):
    source = info.get('source') or ''
    if source.startswith('actual-ceiling'):
        return 'ceiling'
    if source == 'upper-floor-bottom-ray':
        return 'floor'
    return 'level'


def _stabilize_same_level_heights(resolved):
    """Reduce stale Room Upper Limit noise without hiding real ceilings.

    Only a clearly dominant sampled height is used as a same-level consensus.
    Real rooms with genuinely different ceiling zones remain separate; a
    fallback room with no physical evidence inherits the dominant physical
    top surface on that level instead of producing an isolated number.
    """
    groups = defaultdict(list)
    for room_id, info in resolved.items():
        level_id = info.get('base_level_id')
        if level_id is None:
            continue
        groups[level_id].append(info)

    for infos in groups.values():
        by_family = defaultdict(list)
        for info in infos:
            family = _top_surface_family(info)
            if _valid_height(info.get('height')):
                by_family[family].append(info)

        physical_consensus = None
        for family in ('ceiling', 'floor'):
            entries = by_family.get(family) or []
            if len(entries) < 2:
                continue
            dominant = _dominant_height(
                [item.get('height') for item in entries], None)
            if (dominant and
                    dominant['hit_count'] / float(len(entries)) >=
                    SAME_LEVEL_DOMINANCE_RATIO):
                physical_consensus = dominant
                break

        if physical_consensus is None:
            level_entries = by_family.get('level') or []
            if len(level_entries) >= 2:
                physical_consensus = _dominant_height(
                    [item.get('height') for item in level_entries], None)
                if physical_consensus and (
                        physical_consensus['hit_count'] / float(len(level_entries)) <
                        SAME_LEVEL_DOMINANCE_RATIO):
                    physical_consensus = None

        if physical_consensus is None:
            continue

        consensus_height = physical_consensus['height']
        for info in infos:
            family = _top_surface_family(info)
            if family == 'level' or (
                    family in ('ceiling', 'floor') and
                    abs((info.get('height') or consensus_height) -
                        consensus_height) <= SAME_LEVEL_HEIGHT_TOLERANCE_M):
                if abs((info.get('height') or consensus_height) -
                       consensus_height) <= SAME_LEVEL_HEIGHT_TOLERANCE_M or family == 'level':
                    if abs((info.get('height') or consensus_height) -
                           consensus_height) > 0.001:
                        info['height'] = consensus_height
                        info['raw_height'] = consensus_height
                        info.setdefault('warnings', []).append(
                            u'同樓層已有主導的實體頂面高度，已統一淨高避免 Room 上限設定造成孤立數值')
                    if family == 'level':
                        info['source'] = 'same-level-physical-consensus'


def _stacked_room_targets(rooms, force_slab, levels):
    candidates = []
    for room in rooms:
        room_id = _id_value(room.Id)
        if room_id not in force_slab:
            continue
        level = levels['by_id'].get(_id_value(room.LevelId))
        box = _bbox(room)
        if level is None or box is None:
            continue
        candidates.append({
            'room': room,
            'id': room_id,
            'level': level,
            'box': box,
        })

    result = {}
    for current in candidates:
        above = []
        current_elevation = current['level']['elevation_m']
        current_series = _level_series(current['level'].get('name'))
        for candidate in candidates:
            if candidate['id'] == current['id']:
                continue
            elevation = candidate['level']['elevation_m']
            if elevation <= current_elevation + 1.50:
                continue
            candidate_series = _level_series(candidate['level'].get('name'))
            if (current_series and candidate_series and
                    current_series != candidate_series):
                continue
            overlap = _bbox_stack_overlap_ratio_xy(
                current['box'], candidate['box'])
            if overlap < 0.50:
                continue
            above.append((elevation, -overlap, candidate))
        if not above:
            continue
        above.sort(key=lambda item: (item[0], item[1], item[2]['id']))
        selected = above[0][2]
        number = _lookup_text(selected['room'], (u'編號', 'Number'))
        label = u'{} {}'.format(_name(selected['room']), number).strip()
        result[current['id']] = {
            'level': selected['level'],
            'room_id': selected['id'],
            'room_label': label,
            'overlap_ratio': -above[0][1],
        }
    return result


def _category_hidden(doc, view, category):
    try:
        revit_category = Category.GetCategory(doc, category)
        return bool(
            revit_category is not None and
            view.GetCategoryHidden(revit_category.Id))
    except Exception:
        return False


def _detector_view(doc, required_categories=None):
    try:
        views = FilteredElementCollector(doc).OfClass(View3D)
        candidates = [view for view in views if not view.IsTemplate]
        required = list(required_categories or [])
        active_view = getattr(doc, 'ActiveView', None)
        active_id = _id_value(active_view.Id) if active_view is not None else 0

        def view_rank(view):
            hidden_count = sum(
                1 for category in required
                if _category_hidden(doc, view, category))
            return (
                hidden_count,
                1 if view.IsSectionBoxActive else 0,
                0 if _id_value(view.Id) == active_id else 1,
                _name(view),
            )

        candidates.sort(key=view_rank)
        return candidates[0] if candidates else None
    except Exception:
        return None


def _intersector(view, category):
    if view is None:
        return None
    try:
        result = ReferenceIntersector(
            ElementCategoryFilter(category), FindReferenceTarget.Face, view)
    except Exception:
        return None
    try:
        result.FindReferencesInRevitLinks = False
    except Exception:
        pass
    return result


def _room_samples(room, base_m):
    box = _bbox(room)
    if box is None:
        return []
    sample_z = (base_m + 0.15) * M_TO_FT
    candidates = []
    try:
        point = room.Location.Point
        candidates.append(XYZ(point.X, point.Y, sample_z))
    except Exception:
        pass
    for x_ratio in (0.25, 0.50, 0.75):
        for y_ratio in (0.25, 0.50, 0.75):
            candidates.append(XYZ(
                box.Min.X + (box.Max.X - box.Min.X) * x_ratio,
                box.Min.Y + (box.Max.Y - box.Min.Y) * y_ratio,
                sample_z))
    result = []
    for point in candidates:
        try:
            if not room.IsPointInRoom(point):
                continue
        except Exception:
            continue
        if all(existing.DistanceTo(point) > 0.01 for existing in result):
            result.append(point)
    return result


def _dominant_height(values, preferred=None):
    buckets = defaultdict(list)
    for value in values:
        snapped = _snap_height(value)
        if snapped is not None:
            buckets[snapped].append(value)
    if not buckets:
        return None
    ranked = []
    for snapped, raw_values in buckets.items():
        distance = abs(snapped - preferred) if preferred is not None else snapped
        ranked.append((-len(raw_values), distance, snapped, raw_values))
    ranked.sort(key=lambda item: (item[0], item[1], item[2]))
    selected = ranked[0]
    return {
        'height': selected[2],
        'raw_height': sum(selected[3]) / float(len(selected[3])),
        'hit_count': len(selected[3]),
    }


def _ceiling_level_id(element):
    try:
        value = _id_value(element.LevelId)
        if value > 0:
            return value
    except Exception:
        pass
    return _element_id_parameter(element, BuiltInParameter.LEVEL_PARAM)


def _ceiling_label(element):
    name = _name(element) or u'未命名天花'
    return u'{} [Id {}]'.format(name, _id_value(element.Id))


def _ceiling_hits(doc, room, samples, intersector, base_m,
                  floor_sample_heights=None):
    if intersector is None:
        return [], [], []
    room_level_id = _id_value(room.LevelId)
    heights = []
    names = []
    warnings = []
    room_codes = set(_room_ceiling_codes(room))
    ceiling_code_cache = {}
    for sample_index, sample in enumerate(samples):
        floor_height = None
        if (floor_sample_heights is not None and
                sample_index < len(floor_sample_heights)):
            floor_height = floor_sample_heights[sample_index]
        candidates = {}
        try:
            hits = intersector.Find(sample, XYZ.BasisZ)
        except Exception:
            continue
        for hit in hits:
            try:
                reference = hit.GetReference()
                ceiling = doc.GetElement(reference.ElementId)
                if ceiling is None:
                    continue
                point = reference.GlobalPoint
                if point is None:
                    continue
                height = point.Z * FT_TO_M - base_m
                # A ceiling above a real floor slab is not part of this
                # room's clear height.  If no floor is hit at this XY point,
                # keep the ceiling candidate so an open-to-above room can
                # continue across one or more levels.
                if (_valid_height(height) and
                        (floor_height is None or
                         height <= floor_height + TOP_SURFACE_TOLERANCE_M)):
                    ceiling_id = _id_value(ceiling.Id)
                    ceiling_codes = ceiling_code_cache.get(ceiling_id)
                    if ceiling_codes is None:
                        ceiling_codes = set(_ceiling_codes(doc, ceiling))
                        ceiling_code_cache[ceiling_id] = ceiling_codes
                    existing = candidates.get(ceiling_id)
                    if existing is None or height < existing['height']:
                        candidates[ceiling_id] = {
                            'element': ceiling,
                            'height': height,
                            'codes': ceiling_codes,
                        }
            except Exception:
                continue
        available = list(candidates.values())
        matching = [item for item in available
                    if room_codes.intersection(item['codes'])]
        if matching:
            rejected = [item for item in available if item not in matching]
            available = matching
            if rejected:
                warning = (
                    u'同一房間取樣點另有非 Room 天花代碼的重疊天花，'
                    u'已依 Room「天花板塗層」{} 排除：{}').format(
                        u'+'.join(sorted(room_codes)),
                        u'、'.join(_ceiling_label(item['element'])
                                  for item in rejected))
                if warning not in warnings:
                    warnings.append(warning)
        elif room_codes and available:
            warning = (
                u'房間天花板塗層 {}，但射線命中的實體天花代碼皆不相符；'
                u'暫採最低實體天花並請查核').format(
                    u'+'.join(sorted(room_codes)))
            if warning not in warnings:
                warnings.append(warning)
        if not available:
            continue
        selected = sorted(available, key=lambda item: item['height'])[0]
        heights.append(selected['height'])
        ceiling = selected['element']
        ceiling_name = _ceiling_label(ceiling)
        if ceiling_name and ceiling_name not in names:
            names.append(ceiling_name)
        ceiling_level_id = _ceiling_level_id(ceiling)
        if (ceiling_level_id and room_level_id and
                ceiling_level_id != room_level_id):
            warning = u'實體天花 Level 與房間 Level 不一致，已依幾何高度採用'
            if warning not in warnings:
                warnings.append(warning)
    return heights, names, warnings


def _ceiling_bbox_fallback(doc, room, samples, base_m, maximum_m, ceilings,
                           floor_sample_heights=None):
    room_box = _bbox(room)
    room_level_id = _id_value(room.LevelId)
    heights = []
    names = []
    warnings = []
    room_codes = set(_room_ceiling_codes(room))
    candidates = []
    for ceiling in ceilings:
        ceiling_level_id = _ceiling_level_id(ceiling)
        ceiling_box = _bbox(ceiling)
        if not _bbox_overlap_xy(room_box, ceiling_box):
            continue
        overlap_ratio = _bbox_overlap_ratio_xy(room_box, ceiling_box)
        covered_indexes = [index for index, point in enumerate(samples)
                           if (ceiling_box.Min.X <= point.X <= ceiling_box.Max.X and
                               ceiling_box.Min.Y <= point.Y <= ceiling_box.Max.Y)]
        covered_samples = [samples[index] for index in covered_indexes]
        if not covered_samples and overlap_ratio < 0.10:
            continue
        height = ceiling_box.Min.Z * FT_TO_M - base_m
        if not _valid_height(height) and ceiling_level_id == room_level_id:
            offset = _double_parameter(
                ceiling, BuiltInParameter.CEILING_HEIGHTABOVELEVEL_PARAM)
            lower_offset = (_double_parameter(
                room, BuiltInParameter.ROOM_LOWER_OFFSET) or 0.0)
            lower_offset = max(0.0, lower_offset)
            height = (offset - lower_offset) * FT_TO_M if offset is not None else height
        floor_limits = []
        if floor_sample_heights is not None:
            floor_limits = [floor_sample_heights[index]
                            for index in covered_indexes
                            if index < len(floor_sample_heights) and
                            floor_sample_heights[index] is not None]
            if not floor_limits:
                floor_limits = [value for value in floor_sample_heights
                                if value is not None]
        if (_valid_height(height) and
                (not floor_limits or
                 height <= min(floor_limits) + TOP_SURFACE_TOLERANCE_M) and
                (maximum_m is None or height <= maximum_m + 0.30)):
            candidates.append({
                'element': ceiling,
                'box': ceiling_box,
                'height': height,
                'codes': set(_ceiling_codes(doc, ceiling)),
                'overlap_ratio': overlap_ratio,
                'coverage_ratio': (
                    float(len(covered_samples)) / float(len(samples))
                    if samples else 0.0),
                'level_id': ceiling_level_id,
            })

    if candidates:
        strongest = max(max(item['overlap_ratio'], item['coverage_ratio'])
                        for item in candidates)
        threshold = max(0.10, strongest * 0.50)
        candidates = [
            item for item in candidates
            if max(item['overlap_ratio'], item['coverage_ratio']) >= threshold]

    matching = [item for item in candidates
                if room_codes.intersection(item['codes'])]
    if matching:
        rejected = [item for item in candidates if item not in matching]
        candidates = matching
        if rejected:
            warnings.append(
                u'BBox 備援偵測到重疊天花，已依 Room「天花板塗層」{} '
                u'排除非相符天花：{}'.format(
                    u'+'.join(sorted(room_codes)),
                    u'、'.join(_ceiling_label(item['element'])
                              for item in rejected)))
    elif room_codes and candidates:
        warnings.append(
            u'房間天花板塗層 {}，但 BBox 候選天花代碼皆不相符；'
            u'暫採房間內最低候選並請查核'.format(
                u'+'.join(sorted(room_codes))))

    selected_candidates = []
    for sample in samples:
        covered = [item for item in candidates if (
            item['box'].Min.X <= sample.X <= item['box'].Max.X and
            item['box'].Min.Y <= sample.Y <= item['box'].Max.Y)]
        if covered:
            selected = sorted(covered, key=lambda item: item['height'])[0]
            heights.append(selected['height'])
            if selected not in selected_candidates:
                selected_candidates.append(selected)
    if not heights and candidates:
        selected = sorted(
            candidates,
            key=lambda item: (-item['overlap_ratio'], item['height']))[0]
        heights.append(selected['height'])
        selected_candidates.append(selected)
        warnings.append(
            u'實體天花未命中房間取樣點，但 XY bbox 覆蓋房間 '
            u'{}%，已依幾何重疊採用 {}'.format(
                int(round(selected['overlap_ratio'] * 100.0)),
                _ceiling_label(selected['element'])))

    for selected in selected_candidates:
        ceiling_name = _ceiling_label(selected['element'])
        if ceiling_name not in names:
            names.append(ceiling_name)
        if (selected['level_id'] and room_level_id and
                selected['level_id'] != room_level_id):
            warning = u'實體天花 Level 與房間 Level 不一致，已依幾何高度採用'
            if warning not in warnings:
                warnings.append(warning)
    return heights, names, warnings


def _floor_sample_heights(samples, intersector, base_m):
    """Return the nearest upward floor hit for each XY sample.

    There is intentionally no nominal-level distance filter here.  A missing
    slab at the next level is how an open-to-above room is represented; the
    ray must be allowed to reach the next actual slab above it.
    """
    heights = []
    for sample in samples:
        height = None
        if intersector is not None:
            try:
                hit = intersector.FindNearest(sample, XYZ.BasisZ)
                reference = hit.GetReference() if hit is not None else None
                point = reference.GlobalPoint if reference is not None else None
                if point is not None:
                    candidate = point.Z * FT_TO_M - base_m
                    if _valid_height(candidate):
                        height = candidate
            except Exception:
                pass
        heights.append(height)
    return heights


def _floor_hits(samples, intersector, base_m, nominal_m=None):
    """Return upward floor hits without stopping at the nominal next level."""
    return [height for height in _floor_sample_heights(
        samples, intersector, base_m) if height is not None]


def _bottom_ray_hit(doc, sample, intersector, reference_base_m, category):
    if intersector is None:
        return None
    try:
        origin = XYZ(
            sample.X,
            sample.Y,
            (reference_base_m + BOTTOM_RAY_ORIGIN_ABOVE_M) * M_TO_FT)
        hit = intersector.FindNearest(origin, XYZ(0.0, 0.0, -1.0))
        reference = hit.GetReference() if hit is not None else None
        point = reference.GlobalPoint if reference is not None else None
        if point is None:
            return None
        elevation_m = point.Z * FT_TO_M
        offset_m = elevation_m - reference_base_m
        if (offset_m < -BOTTOM_MAX_DROP_M or
                offset_m > BOTTOM_MAX_RISE_M):
            return None
        element = doc.GetElement(reference.ElementId)
        return {
            'elevation_m': elevation_m,
            'element_id': _id_value(reference.ElementId),
            'element_name': _name(element),
            'category': category,
        }
    except Exception:
        return None


def _resolve_room_bottom(doc, room, samples, reference_base_m,
                         floor_intersector, foundation_intersector):
    hits = []
    for sample_index, sample in enumerate(samples):
        candidates = []
        floor_hit = _bottom_ray_hit(
            doc, sample, floor_intersector, reference_base_m, 'Floor')
        if floor_hit is not None:
            candidates.append(floor_hit)
        foundation_hit = _bottom_ray_hit(
            doc, sample, foundation_intersector, reference_base_m,
            'StructuralFoundation')
        if foundation_hit is not None:
            candidates.append(foundation_hit)
        if not candidates:
            continue
        selected = sorted(
            candidates, key=lambda item: item['elevation_m'], reverse=True)[0]
        selected['is_location_sample'] = sample_index == 0
        hits.append(selected)

    lower_offset_m = _room_lower_offset_m(room)
    selected = scaffold_height_logic.select_bottom_surface(
        hits, reference_base_m, lower_offset_m)
    warnings = []
    reliable, rejection_reason = (
        scaffold_height_logic.bottom_surface_is_reliable(
            selected, len(samples)))
    if selected is not None and not reliable:
        if rejection_reason == 'insufficient-coverage':
            warnings.append(
                u'Physical bottom evidence covered only {}/{} Room samples; '
                u'using Room fallback'.format(
                    selected.get('hit_count', 0), len(samples)))
        elif rejection_reason == 'insufficient-dominance':
            warnings.append(
                u'Multiple floor elevations lack a two-thirds dominant level; '
                u'using Room fallback')
        selected = None
    if selected is not None:
        reported_base_m = reference_base_m + min(0.0, lower_offset_m)
        mismatch_m = selected['elevation_m'] - reported_base_m
        if abs(mismatch_m) > 0.05:
            warnings.append(
                u'Physical floor top differs from Room base offset by {} m; '
                u'height uses physical geometry'.format(
                    u'%.2f' % float(mismatch_m)))
        if selected.get('ambiguous'):
            warnings.append(
                u'Multiple floor elevations were detected inside the Room '
                u'(spread {} m); using the dominant sampled elevation'.format(
                    u'%.2f' % float(selected.get('spread_m') or 0.0)))
        selected['warnings'] = warnings
        selected['sample_count'] = len(samples)
        return selected

    fallback_base_m = reference_base_m + min(0.0, lower_offset_m)
    source = ('room-lower-offset-fallback'
              if lower_offset_m < -0.01 else 'room-level-fallback')
    if source == 'room-lower-offset-fallback':
        warnings.append(
            u'No physical floor/foundation top found below; '
            u'using Room lower offset')
    else:
        warnings.append(
            u'No physical floor/foundation top found below; '
            u'using Room level elevation')
    return {
        'elevation_m': fallback_base_m,
        'offset_m': fallback_base_m - reference_base_m,
        'source': source,
        'hit_count': 0,
        'total_hit_count': 0,
        'bucket_count': 0,
        'spread_m': 0.0,
        'ambiguous': False,
        'element_ids': [],
        'element_names': [],
        'categories': [],
        'warnings': warnings,
        'sample_count': len(samples),
    }


def resolve_room_heights(doc, room_ids, force_slab_ids=None,
                         detect_lower_floor=False):
    wanted = set(int(value) for value in room_ids if value is not None)
    force_slab = set(int(value) for value in (force_slab_ids or []))
    levels = _level_catalog(doc)
    thickness_by_level = _floor_thickness_by_level(doc)
    view = _detector_view(
        doc, (BuiltInCategory.OST_Ceilings, BuiltInCategory.OST_Floors))
    bottom_view = _detector_view(
        doc, (BuiltInCategory.OST_Floors,
              BuiltInCategory.OST_StructuralFoundation))
    ceiling_intersector = _intersector(view, BuiltInCategory.OST_Ceilings)
    floor_intersector = _intersector(view, BuiltInCategory.OST_Floors)
    bottom_floor_intersector = _intersector(
        bottom_view, BuiltInCategory.OST_Floors)
    foundation_intersector = (
        _intersector(bottom_view, BuiltInCategory.OST_StructuralFoundation)
        if detect_lower_floor else None)
    ceilings = list(FilteredElementCollector(doc)
                    .OfCategory(BuiltInCategory.OST_Ceilings)
                    .WhereElementIsNotElementType())
    resolved = {}
    counts = defaultdict(int)
    bottom_counts = defaultdict(int)

    rooms = list(FilteredElementCollector(doc)
                 .OfCategory(BuiltInCategory.OST_Rooms)
                 .WhereElementIsNotElementType())
    stacked_targets = _stacked_room_targets(rooms, force_slab, levels)
    for room in rooms:
        room_id = _id_value(room.Id)
        room_level_id = _id_value(room.LevelId)
        if wanted and room_id not in wanted:
            continue
        reference_base_m, base_warnings = _room_base(room, levels)
        if reference_base_m is None:
            continue
        samples = _room_samples(room, reference_base_m)
        if detect_lower_floor:
            bottom = _resolve_room_bottom(
                doc, room, samples, reference_base_m,
                bottom_floor_intersector, foundation_intersector)
        else:
            bottom = {
                'elevation_m': reference_base_m,
                'offset_m': 0.0,
                'source': 'room-reference-base',
                'hit_count': 0,
                'total_hit_count': 0,
                'bucket_count': 0,
                'spread_m': 0.0,
                'ambiguous': False,
                'element_ids': [],
                'element_names': [],
                'categories': [],
                'warnings': [],
                'sample_count': len(samples),
            }
        base_m = bottom['elevation_m']
        reference_to_bottom_m = reference_base_m - base_m
        stacked = stacked_targets.get(room_id) if room_id in force_slab else None
        upper_override = stacked.get('level') if stacked else None
        upper_evidence = None
        if stacked:
            upper_evidence = (
                u'樓梯／電梯垂直堆疊：採上方重疊 Room {} [Id {}] 的樓層 {}，'
                u'XY 重疊 {}%').format(
                    stacked.get('room_label') or u'未命名房間',
                    stacked['room_id'], stacked['level']['name'],
                    int(round(stacked['overlap_ratio'] * 100.0)))
        nominal = _nominal_slab_height(
            room, levels, thickness_by_level, reference_base_m,
            upper_override, upper_evidence)
        nominal = scaffold_height_logic.shift_height_info(
            nominal, reference_to_bottom_m, _snap_height)
        nominal_height = nominal.get('height') if nominal else None
        info = None
        floor_sample_heights = []
        selected = None
        surface_source = 'level'

        if room_id not in force_slab:
            floor_sample_heights = _floor_sample_heights(
                samples, floor_intersector, base_m)
            ceiling_values, ceiling_names, ceiling_warnings = _ceiling_hits(
                doc, room, samples, ceiling_intersector,
                base_m, floor_sample_heights)
            ceiling_basis = 'actual-ceiling-ray'
            if not ceiling_values:
                ceiling_values, ceiling_names, ceiling_warnings = _ceiling_bbox_fallback(
                    doc, room, samples, base_m, None, ceilings,
                    floor_sample_heights)
                ceiling_basis = 'actual-ceiling-bbox-fallback'
            floor_values = [height for height in floor_sample_heights
                            if height is not None]
            surface_source, surface_values = (
                scaffold_height_logic.choose_top_surface(
                    ceiling_values, floor_values))
            selected = _dominant_height(surface_values, nominal_height)
            if selected and surface_source == 'ceiling':
                info = {
                    'height': selected['height'],
                    'raw_height': selected['raw_height'],
                    'source': ceiling_basis,
                    'label': (u'實體天花（幾何射線）' if
                              ceiling_basis == 'actual-ceiling-ray' else
                              u'實體天花（邊界交集備援）'),
                    'target_level': u'',
                    'slab_thickness': None,
                    'warnings': ceiling_warnings,
                    'ceiling_names': ceiling_names,
                    'hit_count': selected['hit_count'],
                }

        if selected and surface_source == 'floor':
                info = {
                    'height': selected['height'],
                    'raw_height': selected['raw_height'],
                    'source': 'upper-floor-bottom-ray',
                    'label': u'上層樓板底（幾何射線）',
                    'target_level': nominal.get('target_level') if nominal else u'',
                    'slab_thickness': nominal.get('slab_thickness') if nominal else None,
                    'warnings': [],
                    'ceiling_names': [],
                    'hit_count': selected['hit_count'],
                }

        if info is None and nominal is not None:
            info = nominal
            info['ceiling_names'] = []
            info['hit_count'] = 0

        if info is None:
            box = _bbox(room)
            fallback = (box.Max.Z * FT_TO_M - base_m
                        if box is not None else None)
            info = {
                'height': _snap_height(fallback),
                'raw_height': fallback,
                'source': 'room-bounding-box-fallback',
                'label': u'Revit Room 高度備援',
                'target_level': u'',
                'slab_thickness': None,
                'warnings': [u'無法取得實體天花或上層樓板底，使用 Room 高度備援'],
                'ceiling_names': [],
                'hit_count': 0,
            }

        for warning in base_warnings:
            if warning not in info.setdefault('warnings', []):
                info['warnings'].append(warning)
        for warning in bottom.get('warnings') or []:
            if warning not in info.setdefault('warnings', []):
                info['warnings'].append(warning)

        info['bottom_source'] = bottom.get('source')
        info['bottom_elevation_m'] = bottom.get('elevation_m')
        info['bottom_offset_m'] = bottom.get('offset_m')
        info['bottom_hit_count'] = bottom.get('hit_count') or 0
        info['bottom_total_hit_count'] = bottom.get('total_hit_count') or 0
        info['bottom_sample_count'] = bottom.get('sample_count') or 0
        info['bottom_spread_m'] = bottom.get('spread_m') or 0.0
        info['bottom_ambiguous'] = bool(bottom.get('ambiguous'))
        info['bottom_element_ids'] = bottom.get('element_ids') or []
        info['bottom_element_names'] = bottom.get('element_names') or []
        info['bottom_categories'] = bottom.get('categories') or []
        level_entry = levels['by_id'].get(room_level_id)
        info['base_level_id'] = room_level_id
        info['base_level_name'] = (
            level_entry.get('name') if level_entry else u'')

        if room_id in force_slab:
            info.setdefault('warnings', []).append(
                u'樓梯／電梯類不採天花高度，固定使用上層樓板底')
        counts[info.get('source') or 'missing'] += 1
        bottom_counts[bottom.get('source') or 'missing'] += 1
        resolved[str(room_id)] = info

    _stabilize_same_level_heights(resolved)

    return {
        'rooms': resolved,
        'counts': dict(counts),
        'bottom_counts': dict(bottom_counts),
        'has_3d_view': view is not None,
        'detector_view': _name(view),
        'bottom_detector_view': _name(bottom_view),
    }
