# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import re


def split_names(value):
    """Split a comma/semicolon/newline separated Revit name list."""
    if value is None:
        return []
    result = []
    for part in re.split(r'[,;\n\r]+', value):
        name = part.strip()
        if name and name not in result:
            result.append(name)
    return result


def canonicalize_names(names, available_names):
    """Return (canonical_names, invalid_names), matching case-insensitively."""
    lookup = {}
    for name in available_names:
        lookup[name.lower()] = name

    canonical = []
    invalid = []
    for name in names:
        actual = lookup.get(name.lower())
        if actual is None:
            invalid.append(name)
        elif actual not in canonical:
            canonical.append(actual)
    return canonical, invalid


def validate_grid_settings(x_text, y_text, offset_text, available_names):
    """Return normalized grid settings and an inline validation message."""
    x_names, invalid_x = canonicalize_names(
        split_names(x_text), available_names)
    y_names, invalid_y = canonicalize_names(
        split_names(y_text), available_names)
    invalid = invalid_x + invalid_y
    if invalid:
        return None, u'找不到以下網格名稱：{}'.format(u'、'.join(invalid))
    if not x_names and not y_names:
        return None, u'請至少輸入一個 X 向或 Y 向網格名稱。'
    try:
        offset_mm = float(offset_text)
    except Exception:
        return None, u'邊界偏移量必須是數字。'
    if offset_mm < 0:
        return None, u'邊界偏移量不可小於 0。'
    return {
        'x_names': x_names,
        'y_names': y_names,
        'offset_mm': offset_mm,
    }, None


def result_items(result):
    """Normalize both create_dependent_views and batch command responses."""
    if isinstance(result, list):
        return result
    if not isinstance(result, dict):
        return []
    items = result.get('CreatedViews')
    if items is None:
        items = result.get('Results')
    return items if isinstance(items, list) else []


def result_summary(result, mode, target_count, source_name=None,
                   scope_name=None, source_dependent_count=None):
    items = result_items(result)
    deleted_count = 0
    for item in items:
        if isinstance(item, dict):
            deleted = item.get('DeletedExistingViewIds') or []
            if isinstance(deleted, (list, tuple)):
                deleted_count += len(deleted)
    lines = [u'模式：{}'.format(mode),
             u'目標母圖數：{}'.format(target_count),
             u'建立從屬視圖數：{}'.format(len(items))]
    if deleted_count:
        lines.append(u'重建前清除舊從屬視圖數：{}'.format(deleted_count))
    if source_name:
        lines.append(u'裁切來源母圖：{}'.format(source_name))
    if source_dependent_count:
        lines.append(u'來源從屬視圖模板數：{}'.format(source_dependent_count))
    if scope_name:
        lines.append(u'套用既有範圍框：{}'.format(scope_name))
    else:
        lines.append(u'裁切控制：CropBox')

    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get('NewViewName') or item.get('TargetViewName') or u''
        if name:
            lines.append(u'  - {}'.format(name))
        warnings = item.get('Warnings') or []
        for warning in warnings:
            lines.append(u'    ⚠ {}'.format(warning))
    return u'\n'.join(lines)
