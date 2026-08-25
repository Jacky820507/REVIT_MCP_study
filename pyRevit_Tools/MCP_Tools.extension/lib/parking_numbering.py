# -*- coding: utf-8 -*-
"""Pure-Python parking-space ordering helpers."""


def _id_key(item):
    value = item.get('id')
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _coordinate(item, axis):
    return float(item.get(axis, 0.0))


def _cluster(items, axis, descending, tolerance):
    ordered = sorted(
        items,
        key=lambda item: (
            -_coordinate(item, axis) if descending
            else _coordinate(item, axis),
            _id_key(item)))
    groups = []
    anchors = []
    for item in ordered:
        value = _coordinate(item, axis)
        if not groups or abs(value - anchors[-1]) > tolerance:
            groups.append([item])
            anchors.append(value)
        else:
            groups[-1].append(item)
    return groups


def sort_bays(items, primary_axis, primary_descending,
              secondary_descending, serpentine, tolerance):
    """Sort parking dictionaries by clustered rows or columns.

    Each item must contain x, y, and id. ``primary_axis`` is ``y`` for
    row-major ordering or ``x`` for column-major ordering.
    """
    if primary_axis not in ('x', 'y'):
        raise ValueError('primary_axis must be x or y')
    if tolerance <= 0:
        raise ValueError('tolerance must be greater than zero')

    secondary_axis = 'x' if primary_axis == 'y' else 'y'
    groups = _cluster(items, primary_axis, primary_descending, tolerance)
    result = []
    for index, group in enumerate(groups):
        descending = secondary_descending
        if serpentine and index % 2 == 1:
            descending = not descending
        group.sort(
            key=lambda item: (
                -_coordinate(item, secondary_axis) if descending
                else _coordinate(item, secondary_axis),
                _id_key(item)))
        for item in group:
            item['_group'] = index + 1
            result.append(item)
    return result


def rotate_to_start(items, start_element_id):
    """Rotate an ordered list so the requested Element ID is first."""
    if start_element_id in (None, ''):
        return list(items)
    target = str(start_element_id)
    for index, item in enumerate(items):
        if str(item.get('id')) == target:
            return list(items[index:]) + list(items[:index])
    raise ValueError('start element is not in the ordered parking set')
