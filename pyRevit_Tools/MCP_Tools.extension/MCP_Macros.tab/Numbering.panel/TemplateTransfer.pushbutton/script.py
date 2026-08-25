# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""樣板移轉 — JAC 11.02（先輸入關鍵字）／11.03（先選模型）.

Two JAC entries, one job entered from opposite ends: either you know the
template's name and want to find which file has it, or you know the file and
want to see what it offers. Both land on the same copy, so they are two modes
here rather than two buttons.

Three things this has to get right, none of them the copy itself:

**A same-named template cannot be overwritten.** ``DuplicateTypeAction`` offers
only ``UseDestinationTypes`` or ``Abort`` — no replace. Collisions are found
before anything is copied and skipped by default; copying anyway is allowed but
then the resulting name is Revit's to choose, and the preview says exactly that
instead of promising one.

**A file we opened is a file we must close; a file the user had open is not.**
Opening a standards file that is already open would either fail or hand back
the user's own document — and closing that would shut their work. So open
documents are matched by path first, and only a document this button actually
opened is closed again.

**Copying runs on the destination.** The Transaction belongs to the current
document, the source is only read, and a failure rolls the destination back
whole.
"""

__title__ = u'樣板移轉'
__author__ = 'RevitMCP'

import os

from Autodesk.Revit import DB
from pyrevit import forms, revit, script
from System.Collections.Generic import List

import mcp_window as ui
import mcp_window_logic as uilogic
import template_transfer_logic as logic


TITLE = u'樣板移轉'

MODES = (
    (u'先輸入關鍵字，跨已開啟的檔案搜尋（JAC 11.02）', 'keyword'),
    (u'先選來源模型，再挑樣板（JAC 11.03）', 'model'),
)

EXISTING_CHOICES = (
    (u'略過目標已有的同名樣板（建議）', True),
    (u'仍然複製，名稱交由 Revit 決定', False),
)

FILE_SOURCE = u'（從檔案選一個 .rvt…）'
# Not None: _pick returns None on cancel, so the file option needs a
# value of its own or the two become indistinguishable.
FILE_SENTINEL = 'pick-file'


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


def _doc_title(doc):
    try:
        return doc.Title or u'(未命名)'
    except Exception:
        return u'(未命名)'


def _open_documents(app, current):
    """Other project documents already open, so nothing has to be loaded."""
    found = []
    try:
        documents = list(app.Documents)
    except Exception:
        return found
    for document in documents:
        try:
            if document.IsFamilyDocument or document.IsLinked:
                continue
            if document.Equals(current):
                continue
        except Exception:
            continue
        found.append(document)
    return found


def _find_open_by_path(app, path):
    """An already-open document for this file, or ``None``.

    Opening a file Revit already has open would either fail or return the
    user's own document — and closing that afterwards would shut their work.
    """
    try:
        wanted = os.path.normcase(os.path.abspath(path))
    except Exception:
        return None
    try:
        documents = list(app.Documents)
    except Exception:
        return None
    for document in documents:
        try:
            existing = document.PathName
            if not existing:
                continue
            if os.path.normcase(os.path.abspath(existing)) == wanted:
                return document
        except Exception:
            continue
    return None


def _templates(doc):
    """Every view template in one document."""
    records = []
    try:
        views = list(DB.FilteredElementCollector(doc)
                     .OfClass(DB.View)
                     .WhereElementIsNotElementType()
                     .ToElements())
    except Exception:
        return records
    title = _doc_title(doc)
    for view in views:
        try:
            if not view.IsTemplate:
                continue
            view_type = u'{}'.format(view.ViewType)
        except Exception:
            continue
        records.append({
            'id': _id_value(view.Id),
            'element_id': view.Id,
            'name': _element_name(view),
            'view_type': view_type,
            'doc_title': title,
            'document': doc,
        })
    return records


def _destination_names(doc):
    return [record['name'] for record in _templates(doc)]


def _template_options(records, keyword=u''):
    """``[(label, record)]``，依視圖類型分組。"""
    options = []
    for group in logic.group_by_view_type(logic.filter_templates(records,
                                                                 keyword)):
        for record in group['records']:
            options.append((u'[{}]　{}　（{}）'.format(
                group['view_type'], record['name'], record['doc_title']),
                record))
    return options


def _build_source_spec(app, current):
    """第一個視窗：怎麼找、從哪找。

    樣板清單必須先知道來源檔才列得出來，所以分兩段——這是真的相依。
    """
    open_options = [(u'{}　（已開啟）'.format(_doc_title(document)), document)
                    for document in _open_documents(app, current)]
    fields = [
        uilogic.section(u'找法'),
        uilogic.choice('mode', u'要用哪種方式找樣板', MODES, default='keyword'),
        uilogic.text('keyword', u'關鍵字（可留空白列出全部）', default=u'',
                     help=u'多個詞以空格分隔，全部都要命中才算符合。'
                          u'兩種模式都用它過濾。'),
        uilogic.choice('source', u'來源模型', open_options + [(FILE_SOURCE,
                                                            FILE_SENTINEL)],
                       default=FILE_SENTINEL,
                       enabled_when=('mode', 'model'),
                       help=u'「先輸入關鍵字」模式會跨所有已開啟的專案檔搜尋，'
                            u'不需要指定來源。'),
    ]
    return uilogic.spec(
        TITLE, fields,
        subtitle=u'把視圖樣板從另一個模型複製進來',
        badge=uilogic.BADGE_WRITE,
        run_label=u'下一步：挑樣板',
        footnote=u'複製在目標文件上進行，失敗時整批回復。',
        width=920, height=620)


def _build_pick_spec(options):
    """第二個視窗：挑樣板與同名處理。"""
    fields = [
        uilogic.section(u'要移轉的視圖樣板'),
        uilogic.multichoice('templates', u'可複選', options, required=True),

        uilogic.section(u'同名衝突'),
        uilogic.choice('skip_existing', u'目標已有同名樣板時怎麼辦',
                       EXISTING_CHOICES, default=True,
                       help=u'Revit 的 API 沒有「取代」這個選項，'
                            u'所以仍要複製時，最後的名稱由 Revit 決定，'
                            u'本工具不會承諾是哪一個。'),
    ]
    return uilogic.spec(
        TITLE, fields,
        subtitle=u'挑選要複製的樣板',
        badge=uilogic.BADGE_WRITE,
        run_label=u'複製',
        footnote=u'複製在目標文件上進行，失敗時整批回復。',
        width=940, height=700)


class _KeepDestination(DB.IDuplicateTypeNamesHandler):
    """Types already in the target win.

    ``Abort`` is the only alternative the API offers, and aborting the whole
    batch because one text type name matched would be a worse outcome than
    reusing the target's own version of it.
    """

    def OnDuplicateTypeNamesFound(self, args):
        return DB.DuplicateTypeAction.UseDestinationTypes


def _copy(destination, source, records):
    """Single Transaction on the destination. Returns ``(count, error)``."""
    ids = List[DB.ElementId]()
    for record in records:
        ids.Add(record['element_id'])

    options = DB.CopyPasteOptions()
    try:
        options.SetDuplicateTypeNamesHandler(_KeepDestination())
    except Exception:
        pass

    transaction = DB.Transaction(destination, TITLE)
    try:
        transaction.Start()
        copied = DB.ElementTransformUtils.CopyElements(
            source, ids, destination, DB.Transform.Identity, options)
        transaction.Commit()
        try:
            return len(list(copied)), u''
        except Exception:
            return len(records), u''
    except Exception as error:
        try:
            if transaction.HasStarted():
                transaction.RollBack()
        except Exception:
            pass
        return 0, u'{}'.format(error)


def _resolve_source(app, current, choice):
    """``(document, opened_by_us)``；取消或失敗回 ``(None, False)``。

    ``choice`` 已經由視窗選好：不是一個已開啟的文件，就是「從檔案選」的哨符。
    """
    if choice is not None and choice != FILE_SENTINEL:
        return choice, False

    path = forms.pick_file(file_ext='rvt')
    if not path:
        return None, False

    existing = _find_open_by_path(app, path)
    if existing is not None:
        # Already open: reuse it, and make sure we never close it later.
        return existing, False
    try:
        return app.OpenDocumentFile(path), True
    except Exception as error:
        forms.alert(u'開啟檔案失敗：\n\n{}'.format(error), title=TITLE)
        return None, False


def main():
    doc = revit.doc
    if doc is None:
        forms.alert(u'請先開啟 Revit 專案文件，再執行移轉。',
                    title=TITLE, exitscript=True)
    app = doc.Application

    picked = ui.ask(_build_source_spec(app, doc))
    if picked is None:
        return
    mode = picked['mode']
    keyword = picked['keyword'] or u''

    source = None
    opened_by_us = False
    try:
        if mode == 'keyword':
            others = _open_documents(app, doc)
            if not others:
                forms.alert(
                    u'目前沒有其他已開啟的專案檔可以搜尋。@@NL@@@@NL@@'
                    u'請先開啟來源檔案，或改用「先選來源模型」模式從檔案挑。',
                    title=TITLE)
                return
            records = []
            for document in others:
                records.extend(_templates(document))
            options = _template_options(records, keyword)
            if not options:
                forms.alert(u'在已開啟的 {} 個檔案裡找不到符合「{}」的視圖樣板。'
                            .format(len(others), keyword), title=TITLE)
                return
        else:
            source, opened_by_us = _resolve_source(app, doc, picked['source'])
            if source is None:
                return
            records = _templates(source)
            if not records:
                forms.alert(u'「{}」裡沒有視圖樣板。'.format(_doc_title(source)),
                            title=TITLE)
                return
            options = _template_options(records, keyword)
            if not options:
                forms.alert(u'「{}」裡沒有符合「{}」的視圖樣板。'.format(
                    _doc_title(source), keyword), title=TITLE)
                return

        chosen = ui.ask(_build_pick_spec(options))
        if chosen is None:
            return
        records = list(chosen['templates'])

        documents = []
        for record in records:
            if record['document'] not in documents:
                documents.append(record['document'])
        if len(documents) > 1:
            forms.alert(
                u'一次只能從同一個來源檔案複製，這次選到了 {} 個檔案：@@NL@@@@NL@@{}'
                u'@@NL@@@@NL@@請分次執行。'.format(
                    len(documents),
                    u'、'.join(_doc_title(item) for item in documents)),
                title=TITLE)
            return
        if source is None:
            source = documents[0]

        skip_existing = chosen['skip_existing']

        plan = logic.build_plan(records, [item['id'] for item in records],
                                _destination_names(doc), skip_existing)
        summary = logic.plan_lines(plan, _doc_title(source), _doc_title(doc))

        output = script.get_output()
        output.print_md(u'## {}'.format(TITLE))
        output.print_md(u'來源：**{}**　→　目標：**{}**'.format(
            _doc_title(source), _doc_title(doc)))
        if plan['copy']:
            renamed_ids = set(record['id'] for record in plan['renamed'])
            output.print_table(
                table_data=[[record['view_type'], record['name'],
                             u'○' if record['id'] in renamed_ids else u'']
                            for record in plan['copy']],
                columns=[u'視圖類型', u'樣板名稱', u'目標已有同名'])
        if plan['blocked']:
            output.print_table(
                table_data=[[entry['record']['view_type'],
                             entry['record']['name'], entry['reason']]
                            for entry in plan['blocked']],
                columns=[u'視圖類型', u'樣板名稱', u'略過原因'])

        if not logic.has_work(plan):
            forms.alert(u'【預覽】沒有要複製的樣板，模型未變更。\n\n{}'.format(
                summary), title=TITLE)
            return

        if not forms.alert(
                u'【dry-run 預覽】模型目前未變更。\n\n{}\n\n確定要複製嗎？'
                .format(summary), title=TITLE, yes=True, no=True):
            return

        copied, error = _copy(doc, source, plan['copy'])
        if error:
            forms.alert(u'複製失敗，交易已完整回復，目標檔案沒有變更。\n\n{}'
                        .format(error), title=TITLE)
            return
        forms.alert(u'已從「{}」複製 {} 個視圖樣板。'.format(
            _doc_title(source), copied), title=TITLE)
    finally:
        # Only ever close a document this button opened.
        if opened_by_us and source is not None:
            try:
                source.Close(False)
            except Exception:
                pass


try:
    main()
except Exception as error:
    forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
