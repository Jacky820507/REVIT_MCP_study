# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Dependent-view matchline button.

The drawing itself is done by the C# command ``create_dependent_view_matchlines``
through the DLL bridge — same algorithm the AI workflow uses. This module adds
what the command has no way to provide: a preflight that reads the model, tells
the user exactly what is about to be deleted and drawn, and refuses to run from
the wrong view. The command has no dryRun parameter and deletes before it
draws, so the confirmation step is the only safety gate.
"""

from pyrevit import DB, forms, revit

import mcp_bridge as mcp
import matchline_logic as logic

try:
    reload(logic)
except Exception:
    pass


TITLE = u'銜接線標註'
COMMAND = 'create_dependent_view_matchlines'


def _id_value(element_id):
    for name in ('Value', 'IntegerValue'):
        try:
            return int(getattr(element_id, name))
        except Exception:
            pass
    try:
        return int(element_id)
    except Exception:
        return None


def _is_valid(element_id):
    try:
        return (element_id is not None
                and element_id != DB.ElementId.InvalidElementId)
    except Exception:
        return False


def _sheet_number_map(doc):
    """``{view_id: sheet_number}`` — mirrors the C# GetSheetNumber lookup."""
    result = {}
    for viewport in (DB.FilteredElementCollector(doc)
                     .OfClass(DB.Viewport)
                     .WhereElementIsNotElementType()):
        try:
            sheet = doc.GetElement(viewport.SheetId)
            if sheet is None:
                continue
            result[_id_value(viewport.ViewId)] = sheet.SheetNumber
        except Exception:
            continue
    return result


def _active_view_info(doc, view):
    primary_id = None
    try:
        primary_id = view.GetPrimaryViewId()
    except Exception:
        primary_id = None
    is_dependent = _is_valid(primary_id)
    primary_name = u''
    if is_dependent:
        primary = doc.GetElement(primary_id)
        primary_name = getattr(primary, 'Name', u'') if primary else u''
    return {
        'id': _id_value(view.Id),
        'name': getattr(view, 'Name', u''),
        'is_dependent': is_dependent,
        'primary_name': primary_name,
    }


def _dependent_views(doc, view, sheet_map):
    views = []
    try:
        dependent_ids = view.GetDependentViewIds()
    except Exception:
        return views
    for view_id in dependent_ids:
        dependent = doc.GetElement(view_id)
        if dependent is None:
            continue
        key = _id_value(view_id)
        views.append({
            'id': key,
            'name': getattr(dependent, 'Name', u''),
            'sheet_number': sheet_map.get(key, u''),
        })
    views.sort(key=lambda item: (item['sheet_number'], item['name']))
    return views


def _line_style_names(doc):
    names = set()
    for style in (DB.FilteredElementCollector(doc)
                  .OfClass(DB.GraphicsStyle)):
        try:
            category = style.GraphicsStyleCategory
            if category is None or category.Parent is None:
                continue
            if category.Parent.Id != DB.ElementId(
                    DB.BuiltInCategory.OST_Lines):
                continue
            if style.Name:
                names.add(style.Name)
        except Exception:
            continue
    return sorted(names)


def _element_name(element):
    if element is None:
        return None
    try:
        return DB.Element.Name.GetValue(element)
    except Exception:
        return getattr(element, 'Name', None)


def _default_text_style_name(doc):
    """Read the document default when the pyRevit collector is empty."""
    try:
        type_id = doc.GetDefaultElementTypeId(DB.ElementTypeGroup.TextNoteType)
        if not _is_valid(type_id):
            return None
        return _element_name(doc.GetElement(type_id))
    except Exception:
        return None


def _text_style_names(doc):
    names = set()
    try:
        styles = (DB.FilteredElementCollector(doc)
                  .OfClass(DB.TextNoteType))
    except Exception:
        styles = []
    for style in styles:
        try:
            name = _element_name(style)
        except Exception:
            name = getattr(style, 'Name', None)
        if name:
            names.add(name)
    return logic.style_names_with_fallback(
        names, _default_text_style_name(doc))


def _views_for_cleanup(doc, view):
    """Return the primary view and its dependents without duplicate views."""
    result = []
    seen = set()
    candidates = [view]
    try:
        for view_id in view.GetDependentViewIds():
            dependent = doc.GetElement(view_id)
            if dependent is not None:
                candidates.append(dependent)
    except Exception:
        pass

    for candidate in candidates:
        key = _id_value(getattr(candidate, 'Id', None))
        if key is not None and key in seen:
            continue
        if key is not None:
            seen.add(key)
        result.append(candidate)
    return result


def _existing_counts(doc, view, line_style_name):
    """What the C# command will delete before it draws.

    The command cleans both the primary view and its dependent views because
    older runs could have written annotations to the wrong view.
    """
    lines = 0
    texts = 0
    seen_lines = set()
    seen_texts = set()
    for scan_view in _views_for_cleanup(doc, view):
        try:
            for element in (DB.FilteredElementCollector(doc, scan_view.Id)
                            .OfCategory(DB.BuiltInCategory.OST_Lines)
                            .WhereElementIsNotElementType()):
                element_id = _id_value(getattr(element, 'Id', None))
                if element_id is not None and element_id in seen_lines:
                    continue
                try:
                    style = element.LineStyle
                    if style is not None and line_style_name in style.Name:
                        if element_id is not None:
                            seen_lines.add(element_id)
                        lines += 1
                except Exception:
                    continue
        except Exception:
            pass
        try:
            for note in (DB.FilteredElementCollector(doc, scan_view.Id)
                         .OfClass(DB.TextNote)):
                element_id = _id_value(getattr(note, 'Id', None))
                if element_id is not None and element_id in seen_texts:
                    continue
                try:
                    if note.Text and logic.TEXT_PREFIX in note.Text:
                        if element_id is not None:
                            seen_texts.add(element_id)
                        texts += 1
                except Exception:
                    continue
        except Exception:
            pass
    return lines, texts


def _pick_style(names, keyword, prompt):
    """Let the user confirm the style; never hardcode the project's names."""
    resolved, matched = logic.resolve_style(names, keyword)
    if resolved is None:
        return None
    options = list(names)
    default = options[logic.default_index(options, keyword)]
    picked = forms.SelectFromList.show(
        options, title=prompt, button_name=u'使用這個',
        multiselect=False, default=default)
    if picked is None:
        return None
    return picked if not isinstance(picked, list) else picked[0]


def run(doc, view):
    info = _active_view_info(doc, view)
    sheet_map = _sheet_number_map(doc)
    views = _dependent_views(doc, view, sheet_map)

    blockers = logic.preflight_blockers(info, views)
    if blockers:
        forms.alert(u'\n\n'.join(blockers), title=TITLE)
        return

    line_names = _line_style_names(doc)
    if not line_names:
        forms.alert(u'模型中找不到任何線型（Line Style）。', title=TITLE)
        return
    line_style = _pick_style(line_names, logic.DEFAULT_LINE_STYLE,
                             u'選擇銜接線線型')
    if not line_style:
        return

    text_names = _text_style_names(doc)
    if text_names:
        text_style = _pick_style(text_names, logic.DEFAULT_TEXT_STYLE,
                                 u'選擇銜接線文字型式')
        if not text_style:
            return
    else:
        # Let the C# side resolve the default type.  It validates this before
        # deleting anything, so a genuinely type-less document gets a safe,
        # actionable error instead of the old preflight dead end.
        text_style = u'（Revit 預設文字型式）'

    old_lines, old_texts = _existing_counts(doc, view, line_style)
    confirmed = forms.alert(
        u'{}\n\n確定執行嗎？'.format(logic.preflight_text(
            info, views, line_style, text_style, old_lines, old_texts)),
        title=TITLE, yes=True, no=True)
    if not confirmed:
        return

    try:
        data = mcp.run(COMMAND, {
            'primaryViewId': info['id'],
            'lineStyleName': line_style,
            'textStyleName': text_style,
        })
    except mcp.MCPBridgeError as error:
        mcp.show_error(error, TITLE)
        return

    forms.alert(logic.result_text(data), title=TITLE)
