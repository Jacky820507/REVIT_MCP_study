# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""專案參數移轉（可篩選）— JAC 11.04.

Moving project parameters between documents is not a copy. A ``Definition``
belongs to the document that owns it, so the target must be handed a *new*
definition that Revit recognises as the same parameter. That identity is the
GUID, which only shared parameters have — hence the one hard limit, reported
rather than worked around: **non-shared project parameters cannot be
transferred.** Recreating them as shared would change what they are.

Three implementation facts, all confirmed by reflection against 2020 and 2024:

**The data type is carried, never interpreted.** 2020 exposes
``Definition.ParameterType`` and takes a ``ParameterType`` in
``ExternalDefinitionCreationOptions``; 2024 removed both in favour of
``GetDataType()`` and a ``ForgeTypeId``. Since source and target are open in
the *same* Revit, whatever the reader returns is exactly what that version's
constructor wants — so it is passed through opaquely and this button never has
to know which era it is in.

**Creating the definition needs a shared-parameter file, and that setting is
global.** ``Application.SharedParametersFilename`` belongs to the session, not
to this command. It is pointed at a scratch file and **restored in a finally**,
because leaving a user's shared-parameter path aimed at a temp file is a
lasting mess for a momentary convenience.

**A file we opened is a file we close; a file the user had open is not** — the
same rule the 樣板移轉 button follows, for the same reason.
"""

__title__ = u'專案參數\n移轉'
__author__ = 'RevitMCP'

import os
import tempfile

from Autodesk.Revit import DB
from pyrevit import forms, revit, script
from System import Guid

import project_parameter_logic as logic


TITLE = u'專案參數移轉'
FILE_SOURCE = u'（從檔案選一個 .rvt…）'
FILE_SENTINEL = 'pick-file'
TEMP_GROUP = u'RevitMCP_Transfer'

# ANY is a real answer, not the absence of one: _pick returns None on
# cancel, so "no filter" needs a value of its own.
ANY = 'any'

BINDING_CHOICES = (
    (u'全部（實體＋類型）', ANY),
    (logic.BINDING_LABELS[logic.BINDING_INSTANCE], logic.BINDING_INSTANCE),
    (logic.BINDING_LABELS[logic.BINDING_TYPE], logic.BINDING_TYPE),
)


def _pick(options, title):
    """SelectFromList single pick; returns the paired value, None on cancel."""
    labels = [label for label, unused in options]
    picked = forms.SelectFromList.show(labels, title=title, multiselect=False)
    if not picked:
        return None
    for label, value in options:
        if label == picked:
            return value
    return None


def _doc_title(doc):
    try:
        return doc.Title or u'(未命名)'
    except Exception:
        return u'(未命名)'


def _open_documents(app, current):
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
    """An already-open document for this file, or ``None``."""
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


def _data_type(definition):
    """The version's own notion of a parameter's data type, uninterpreted.

    2024 dropped ``ParameterType`` for ``GetDataType() -> ForgeTypeId``; the
    value is only ever handed straight back to the same version's
    ``ExternalDefinitionCreationOptions``, so it never needs decoding.
    """
    getter = getattr(definition, 'GetDataType', None)
    if getter is not None:
        try:
            return getter()
        except Exception:
            pass
    return getattr(definition, 'ParameterType', None)


def _group_of(definition):
    """The parameter group, again as whatever token this version uses."""
    getter = getattr(definition, 'GetGroupTypeId', None)
    if getter is not None:
        try:
            return getter()
        except Exception:
            pass
    return getattr(definition, 'ParameterGroup', None)


def _category_names(binding):
    names = []
    try:
        categories = binding.Categories
    except Exception:
        return names
    try:
        iterator = categories.ForwardIterator()
        iterator.Reset()
        while iterator.MoveNext():
            category = iterator.Current
            try:
                if category is not None and category.Name:
                    names.append(category.Name)
            except Exception:
                continue
    except Exception:
        return names
    return sorted(names)


def _shared_guid(doc, definition):
    """``(is_shared, guid_text)`` for one definition."""
    try:
        element = doc.GetElement(definition.Id)
    except Exception:
        return False, u''
    if element is None:
        return False, u''
    try:
        if isinstance(element, DB.SharedParameterElement):
            return True, u'{}'.format(element.GuidValue)
    except Exception:
        pass
    return False, u''


def _read_bindings(doc):
    """Every project-parameter binding in one document."""
    records = []
    try:
        iterator = doc.ParameterBindings.ForwardIterator()
        iterator.Reset()
    except Exception:
        return records
    while True:
        try:
            if not iterator.MoveNext():
                break
            definition = iterator.Key
            binding = iterator.Current
        except Exception:
            break
        if definition is None or binding is None:
            continue
        try:
            name = definition.Name or u''
        except Exception:
            continue
        if isinstance(binding, DB.InstanceBinding):
            kind = logic.BINDING_INSTANCE
        elif isinstance(binding, DB.TypeBinding):
            kind = logic.BINDING_TYPE
        else:
            kind = u''
        is_shared, guid = _shared_guid(doc, definition)
        records.append({
            # GUID for shared parameters, name otherwise — either way unique
            # within one document, which is all the picker needs.
            'id': guid or (u'name:' + name),
            'name': name,
            'guid': guid,
            'is_shared': is_shared,
            'binding_kind': kind,
            'categories': _category_names(binding),
            'group': u'{}'.format(_group_of(definition) or u''),
            'definition': definition,
            'binding': binding,
        })
    return records


def _resolve_source(app, current):
    """``(document, opened_by_us)`` or ``(None, False)`` on cancel."""
    options = []
    for document in _open_documents(app, current):
        options.append((u'{}　（已開啟）'.format(_doc_title(document)),
                        document))
    options.append((FILE_SOURCE, FILE_SENTINEL))
    choice = _pick(options, u'來源模型是哪一個？')
    if choice is None:
        return None, False
    if choice != FILE_SENTINEL:
        return choice, False

    path = forms.pick_file(file_ext='rvt')
    if not path:
        return None, False
    existing = _find_open_by_path(app, path)
    if existing is not None:
        return existing, False
    try:
        return app.OpenDocumentFile(path), True
    except Exception as error:
        forms.alert(u'開啟檔案失敗：\n\n{}'.format(error), title=TITLE)
        return None, False


def _pick_parameters(records):
    labels = {}
    order = []
    for group in logic.group_by_binding(records):
        for record in group['records']:
            mark = u'' if record['is_shared'] else u'　⚠非共用'
            label = u'[{}]　{}　（{}）{}'.format(
                group['label'], record['name'],
                u'、'.join(record['categories']) or logic.NO_CATEGORY, mark)
            while label in labels:
                label += u' '
            labels[label] = record
            order.append(label)
    if not order:
        forms.alert(u'沒有符合條件的專案參數。', title=TITLE)
        return None
    picked = forms.SelectFromList.show(
        order, title=u'選擇要移轉的專案參數（可複選）', multiselect=True)
    if not picked:
        return None
    return [labels[label] for label in picked if label in labels]


def _scratch_definition_file(app):
    """Point Revit at an empty scratch shared-parameter file.

    Returns ``(definition_file, previous_path, scratch_path)``. The caller
    restores ``previous_path`` — this setting belongs to the session.
    """
    handle, scratch = tempfile.mkstemp(suffix='.txt',
                                       prefix='RevitMCP_ParamTransfer_')
    os.close(handle)
    with open(scratch, 'w') as stream:
        stream.write('')
    try:
        previous = app.SharedParametersFilename
    except Exception:
        previous = u''
    app.SharedParametersFilename = scratch
    return app.OpenSharedParameterFile(), previous, scratch


def _external_definitions(definition_file, records):
    """Recreate each shared parameter in the scratch file, GUID intact.

    Same GUID means Revit treats it as the same shared parameter as the one in
    the source document — that is the whole mechanism by which this transfer
    is a transfer rather than a lookalike.
    """
    group = None
    for existing in definition_file.Groups:
        try:
            if existing.Name == TEMP_GROUP:
                group = existing
                break
        except Exception:
            continue
    if group is None:
        group = definition_file.Groups.Create(TEMP_GROUP)

    made = []
    for record in records:
        options = DB.ExternalDefinitionCreationOptions(
            record['name'], _data_type(record['definition']))
        # Same GUID as the source: that is what makes Revit treat this as the
        # same shared parameter rather than a namesake.
        options.GUID = Guid(record['guid'])
        made.append((record, group.Definitions.Create(options)))
    return made


def _transfer(destination, pairs):
    """One Transaction on the destination. Returns ``(count, error)``."""
    transaction = DB.Transaction(destination, TITLE)
    try:
        transaction.Start()
        done = 0
        # Categories is keyed by name, so one lookup each beats walking the
        # whole map per parameter.
        available = destination.Settings.Categories
        for record, external in pairs:
            categories = DB.CategorySet()
            for name in record['categories']:
                try:
                    category = available.get_Item(name)
                except Exception:
                    category = None
                if category is not None:
                    categories.Insert(category)
            if categories.IsEmpty:
                raise Exception(
                    u'參數「{}」的品類在目標檔案裡都找不到。'.format(
                        record['name']))
            if record['binding_kind'] == logic.BINDING_TYPE:
                binding = DB.TypeBinding(categories)
            else:
                binding = DB.InstanceBinding(categories)
            group = _group_of(record['definition'])
            inserted = False
            if group is not None:
                try:
                    inserted = destination.ParameterBindings.Insert(
                        external, binding, group)
                except Exception:
                    inserted = False
            if not inserted:
                inserted = destination.ParameterBindings.Insert(external,
                                                                binding)
            if not inserted:
                raise Exception(u'參數「{}」寫入失敗。'.format(record['name']))
            done += 1
        transaction.Commit()
        return done, u''
    except Exception as error:
        try:
            if transaction.HasStarted():
                transaction.RollBack()
        except Exception:
            pass
        return 0, u'{}'.format(error)


def main():
    doc = revit.doc
    if doc is None:
        forms.alert(u'請先開啟 Revit 專案文件，再執行移轉。',
                    title=TITLE, exitscript=True)
    app = doc.Application

    source = None
    opened_by_us = False
    previous_sp = None
    scratch = None
    try:
        source, opened_by_us = _resolve_source(app, doc)
        if source is None:
            return

        records = _read_bindings(source)
        if not records:
            forms.alert(u'「{}」裡沒有專案參數。'.format(_doc_title(source)),
                        title=TITLE)
            return

        keyword = forms.ask_for_string(
            default=u'', prompt=u'名稱／品類關鍵字（可留空白；多詞以空格分隔，需全部命中）',
            title=TITLE)
        if keyword is None:
            return
        binding_kind = _pick(BINDING_CHOICES, u'要哪一種綁定？')
        if binding_kind is None:
            return

        category_options = [(u'（不限品類）', ANY)]
        for name in logic.all_categories(records):
            category_options.append((name, name))
        category = _pick(category_options, u'要限定哪個品類？')
        if category is None:
            return

        filtered = logic.filter_parameters(
            records, keyword,
            None if category == ANY else [category],
            None if binding_kind == ANY else binding_kind)
        if not filtered:
            forms.alert(u'沒有符合條件的專案參數。', title=TITLE)
            return

        chosen = _pick_parameters(filtered)
        if not chosen:
            return

        target = _read_bindings(doc)
        plan = logic.build_plan(
            chosen, [item['id'] for item in chosen],
            [item['guid'] for item in target if item['guid']],
            [item['name'] for item in target])
        summary = logic.plan_lines(plan, _doc_title(source), _doc_title(doc))

        output = script.get_output()
        output.print_md(u'## {}'.format(TITLE))
        output.print_md(u'來源：**{}**　→　目標：**{}**'.format(
            _doc_title(source), _doc_title(doc)))
        if plan['transfer']:
            output.print_table(
                table_data=[[logic.binding_label(record['binding_kind']),
                             record['name'], record['guid'],
                             u'、'.join(record['categories'])]
                            for record in plan['transfer']],
                columns=[u'綁定', u'參數名稱', u'GUID', u'品類'])
        if plan['blocked']:
            output.print_table(
                table_data=[[entry['record']['name'], entry['reason']]
                            for entry in plan['blocked']],
                columns=[u'參數名稱', u'略過原因'])

        if not logic.has_work(plan):
            forms.alert(u'【預覽】沒有可移轉的參數，模型未變更。\n\n{}'.format(
                summary), title=TITLE)
            return

        if not forms.alert(
                u'【dry-run 預覽】模型目前未變更。\n\n{}\n\n確定要移轉嗎？'
                .format(summary), title=TITLE, yes=True, no=True):
            return

        definition_file, previous_sp, scratch = _scratch_definition_file(app)
        if definition_file is None:
            forms.alert(u'無法建立暫存的共用參數檔，移轉中止。', title=TITLE)
            return
        pairs = _external_definitions(definition_file, plan['transfer'])
        done, error = _transfer(doc, pairs)
        if error:
            forms.alert(u'移轉失敗，交易已完整回復，目標檔案沒有變更。\n\n{}'
                        .format(error), title=TITLE)
            return
        forms.alert(u'已從「{}」移轉 {} 個專案參數。'.format(
            _doc_title(source), done), title=TITLE)
    finally:
        # SharedParametersFilename belongs to the session, not to this button.
        if previous_sp is not None:
            try:
                app.SharedParametersFilename = previous_sp
            except Exception:
                pass
        if scratch:
            try:
                os.remove(scratch)
            except Exception:
                pass
        if opened_by_us and source is not None:
            try:
                source.Close(False)
            except Exception:
                pass


try:
    main()
except Exception as error:
    forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
