# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Pure rules for the dependent-view matchline button.

The heavy lifting (CropBox pairing, line/text placement) lives in the C#
command ``create_dependent_view_matchlines``. This module only owns the
preflight decisions that command cannot make for the user: is the active view
actually a primary view, which dependent views would come out unlabelled, and
what is about to be deleted.
"""

import re
import unicodedata


# domain/matchline-automation.md fixes these as the project's drawing standard.
DEFAULT_LINE_STYLE = u'粗虛線'
DEFAULT_TEXT_STYLE = u'微軟正黑體 3.5 mm'
# The C# command tags what it writes with this comment, and finds old
# annotations by the 銜接線 prefix in the text.
TEXT_PREFIX = u'銜接線'


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value)
    except Exception:
        return str(value)


def normalize_text(value):
    text = unicodedata.normalize('NFKC', _text(value)).lower()
    return re.sub(u'[\\s（）()\\[\\]【】，,、:：;；._\\-/\\\\]', u'', text)


def default_index(names, keyword):
    """Index of the first name containing ``keyword``, else 0.

    Matches the C# side, which picks its style with ``Name.Contains(...)``;
    the button must preselect the same one or the preview would lie about what
    is going to be drawn.
    """
    needle = normalize_text(keyword)
    if needle:
        for index, name in enumerate(names or []):
            if needle in normalize_text(name):
                return index
    return 0


def resolve_style(names, keyword):
    """``(name, matched)`` for the style the C# command would actually use."""
    if not names:
        return None, False
    index = default_index(names, keyword)
    matched = normalize_text(keyword) in normalize_text(names[index])
    return names[index], matched


def style_names_with_fallback(names, fallback):
    """Return usable style names, falling back to Revit's default type.

    Some Revit documents expose the default TextNoteType through
    ``GetDefaultElementTypeId`` even when a class collector returns no rows
    through the pyRevit wrapper.  Keep the UI from treating that recoverable
    case as a hard failure.
    """
    result = set()
    for name in names or []:
        value = _text(name).strip()
        if value:
            result.add(value)
    if not result:
        value = _text(fallback).strip()
        if value:
            result.add(value)
    return sorted(result)


def split_labelled(views):
    """``(labelled, unlabelled)`` dependent views by sheet placement.

    A dependent view that is not on a sheet has no sheet number, so the C#
    command falls back to the view name — the drawing would then read
    「銜接線 <視圖名>」 instead of a sheet number. That is worth stopping for.
    """
    labelled = []
    unlabelled = []
    for view in views or []:
        if _text(view.get('sheet_number')).strip():
            labelled.append(view)
        else:
            unlabelled.append(view)
    return labelled, unlabelled


def view_label(view):
    number = _text(view.get('sheet_number')).strip()
    name = _text(view.get('name')).strip()
    return u'{}　{}'.format(number or u'（未上圖紙）', name).strip()


def preflight_blockers(active_view, views):
    """Hard stops. Empty list means the run can proceed."""
    blockers = []
    if active_view.get('is_dependent'):
        blockers.append(
            u'目前視圖是「從屬視圖」，銜接線必須在母視圖執行。'
            u'請切換到母視圖「{}」後重試。'.format(
                _text(active_view.get('primary_name')) or u'(未知)'))
    if not views:
        blockers.append(u'目前視圖沒有任何從屬視圖，沒有可標註的邊界。')
    return blockers


def preflight_text(active_view, views, line_style, text_style,
                   old_lines, old_texts):
    labelled, unlabelled = split_labelled(views)
    lines = [
        u'母視圖：{}'.format(_text(active_view.get('name'))),
        u'從屬視圖：{} 個（已上圖紙 {}／未上圖紙 {}）'.format(
            len(views), len(labelled), len(unlabelled)),
        u'',
        u'線型：{}'.format(_text(line_style)),
        u'文字型式：{}'.format(_text(text_style)),
        u'',
        u'將先清除母視圖與從屬視圖既有的銜接線：{} 條線、{} 組文字'.format(
            old_lines, old_texts),
        u'',
        u'從屬視圖與圖號：',
    ]
    for view in views:
        lines.append(u'  {}'.format(view_label(view)))
    if unlabelled:
        lines.extend([
            u'',
            u'⚠ 下列 {} 個從屬視圖尚未放上圖紙，標註會改用視圖名稱而不是圖號：'
            .format(len(unlabelled)),
        ])
        for view in unlabelled:
            lines.append(u'  {}'.format(_text(view.get('name'))))
    return u'\n'.join(lines)


def result_text(data):
    """Format the C# response; it reports its own deletions and creations."""
    if not data:
        return u'命令沒有回傳結果。'
    if not data.get('Success'):
        return _text(data.get('Message')) or u'命令回報失敗。'
    lines = [
        u'已清除舊標註：{} 條線、{} 組文字'.format(
            data.get('DeletedLines', 0), data.get('DeletedTexts', 0)),
        u'新建銜接線：{} 條'.format(data.get('CreatedMatchlines', 0)),
    ]
    if data.get('CreatedTexts') is not None:
        lines.append(u'新建兩側文字：{} 組'.format(data.get('CreatedTexts', 0)))
    details = data.get('Details') or []
    if details:
        lines.append(u'')
        lines.append(u'配對結果：')
        for item in details[:40]:
            lines.append(u'  {} ↔ {}'.format(
                _text(item.get('View1')), _text(item.get('View2'))))
        if len(details) > 40:
            lines.append(u'  …其餘 {} 組'.format(len(details) - 40))
    if not data.get('CreatedMatchlines'):
        lines.append(u'')
        lines.append(
            u'沒有建立任何銜接線：命令未回傳可用候選，請確認從屬視圖的 CropBox 配置。')
    return u'\n'.join(lines)
