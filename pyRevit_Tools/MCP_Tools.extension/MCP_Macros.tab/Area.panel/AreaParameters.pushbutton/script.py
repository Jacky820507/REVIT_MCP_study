# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""新增 AREA 基本項目 — JAC 04.06.

Every other Area button in this extension stops and asks which parameter holds
戶別, 分類, 棟別, 權屬 — because those are project parameters and each office
names them its own way. This is the button that creates them, so a fresh
project can run the rest.

**A shared parameter is its GUID, not its name.** Two projects that each invent
a 戶別 with a fresh random GUID end up with two parameters identical in every
dialog and not the same parameter: they will not schedule together, tag
consistently, or map the same way on IFC export. So when this has to mint a
definition itself, the GUID is derived from the name — same name, same
parameter, in every project it touches. An office shared-parameter file is
still better and is offered first; the derived route exists so a project
without one is not stuck, and the report says which happened.

**The data type is the one thing that genuinely forks by version.** 2020 wants
a ``ParameterType``; 2021+ wants a ``ForgeTypeId`` off ``SpecTypeId``, with
Text and YesNo living under nested classes. Unlike 專案參數移轉 — which carries
a type it read from another document and never interprets — this button has to
*name* a type, so it resolves one per version. ``BuiltInParameterGroup`` needs
no fork: ``PG_IDENTITY_DATA`` and the three-argument ``Insert`` are present in
both.

``SharedParametersFilename`` is a session-wide setting and is restored in a
``finally`` — the same rule 專案參數移轉 follows.
"""

__title__ = u'新增Area\n基本參數'
__author__ = 'RevitMCP'

import os
import tempfile

from Autodesk.Revit import DB
from pyrevit import forms, revit, script
from System import Guid

import area_parameter_setup_logic as logic
import mcp_window as ui
import mcp_window_logic as uilogic


TITLE = u'新增 Area 基本參數'
TEMP_GROUP = u'RevitMCP_AreaParameters'

SOURCE_DERIVED = 'derived'
SOURCE_FILE = 'file'

SOURCE_CHOICES = (
    (u'由工具建立（GUID 依名稱推導，同名跨專案一致）', SOURCE_DERIVED),
    (u'從貴單位的共用參數檔挑（GUID 用你們的標準，建議）', SOURCE_FILE),
)


def _spec_for(kind):
    """The data type this Revit version wants, for one of our kinds.

    2020 has ``ParameterType``; 2021+ replaced it with ``SpecTypeId``, where
    Text sits under ``String`` and YesNo under ``Boolean``. Resolved by probing
    rather than by version number, so a build that has one and not the other
    is what decides.
    """
    spec = getattr(DB, 'SpecTypeId', None)
    if spec is not None:
        text = getattr(spec, 'String', None)
        integer = getattr(spec, 'Int', None)
        boolean = getattr(spec, 'Boolean', None)
        table = {
            logic.KIND_TEXT: getattr(text, 'Text', None) if text else None,
            logic.KIND_INTEGER: (getattr(integer, 'Integer', None)
                                 if integer else None),
            logic.KIND_NUMBER: getattr(spec, 'Number', None),
            logic.KIND_AREA: getattr(spec, 'Area', None),
            logic.KIND_LENGTH: getattr(spec, 'Length', None),
            logic.KIND_YESNO: (getattr(boolean, 'YesNo', None)
                               if boolean else None),
        }
        return table.get(kind)

    legacy = getattr(DB, 'ParameterType', None)
    if legacy is None:
        return None
    table = {
        logic.KIND_TEXT: 'Text',
        logic.KIND_INTEGER: 'Integer',
        logic.KIND_NUMBER: 'Number',
        logic.KIND_AREA: 'Area',
        logic.KIND_LENGTH: 'Length',
        logic.KIND_YESNO: 'YesNo',
    }
    return getattr(legacy, table.get(kind, 'Text'), None)


def _bound_names(doc):
    """Names of every project parameter already bound in this document."""
    names = []
    try:
        iterator = doc.ParameterBindings.ForwardIterator()
        iterator.Reset()
    except Exception:
        return names
    while True:
        try:
            if not iterator.MoveNext():
                break
            definition = iterator.Key
        except Exception:
            break
        if definition is None:
            continue
        try:
            if definition.Name:
                names.append(definition.Name)
        except Exception:
            continue
    return names


def _build_spec(defaults):
    """第一個視窗：來源與（自建時的）參數名稱。

    原本每個參數各問一次 ``ask_for_string``，五個參數就是五個對話框，而且改
    第三個得先把前兩個重打一遍。現在全部在同一頁，留空白仍然代表不建立。
    """
    fields = [
        uilogic.section(u'參數定義的來源'),
        uilogic.choice('source', u'參數定義從哪裡來', SOURCE_CHOICES,
                       default=SOURCE_FILE,
                       help=u'共用參數檔的 GUID 是貴單位的標準，跨專案一致；'
                            u'工具自建的 GUID 依名稱推導，同名也會一致，'
                            u'但和貴單位既有的參數不是同一個。'),

        uilogic.section(u'參數名稱（自建時使用）',
                        u'留空白＝這一個不要建立。'),
    ]
    for index, spec in enumerate(defaults):
        fields.append(uilogic.text(
            'name_{}'.format(index), u'{}（{}）'.format(
                spec['name'], logic.kind_label(spec['kind'])),
            default=spec['name'], required=False,
            enabled_when=('source', SOURCE_DERIVED),
            help=u'供「{}」使用。'.format(spec['used_by'])))

    return uilogic.spec(
        TITLE, fields,
        subtitle=u'替 Area 建立戶別、分類、權屬等基本專案參數',
        badge=uilogic.BADGE_WRITE,
        run_label=u'下一步',
        footnote=u'建立前一定會先預覽並由你確認；失敗時整批回復。',
        width=940, height=760)


def _build_shared_spec(options):
    """第二個視窗：從共用參數檔挑。選項要先讀完那個檔才知道，故分兩段。"""
    fields = [
        uilogic.section(u'共用參數'),
        uilogic.multichoice('picked', u'要加入的共用參數（可複選）',
                            options, required=True),
    ]
    return uilogic.spec(
        TITLE, fields,
        subtitle=u'從共用參數檔挑選',
        badge=uilogic.BADGE_WRITE,
        run_label=u'預覽',
        footnote=u'使用貴單位既有的 GUID，不另外推導。',
        width=880, height=620)


def _named_specs(defaults, values):
    """把視窗填的名稱套回預設規格；留空白的就不建立。"""
    result = []
    for index, spec in enumerate(defaults):
        name = (values.get('name_{}'.format(index)) or u'').strip()
        if not name:
            continue
        item = dict(spec)
        item['name'] = name
        result.append(item)
    return result


def _shared_options(app):
    """``[(label, spec)]`` from the session's shared-parameter file.

    回 ``None`` 表示使用者取消，回 ``[]`` 表示這個檔不能用——呼叫端因此可以
    退回自建 GUID，而不是走進死路。挑選本身交給視窗，這裡只負責讀出選項。
    """
    try:
        path = app.SharedParametersFilename
    except Exception:
        path = u''
    if not path or not os.path.isfile(path):
        path = forms.pick_file(file_ext='txt')
        if not path:
            return None
        try:
            app.SharedParametersFilename = path
        except Exception:
            forms.alert(u'無法設定共用參數檔。', title=TITLE)
            return []
    try:
        definition_file = app.OpenSharedParameterFile()
    except Exception:
        definition_file = None
    if definition_file is None:
        forms.alert(u'讀不到共用參數檔內容。', title=TITLE)
        return []

    labels = {}
    order = []
    for group in definition_file.Groups:
        for definition in group.Definitions:
            try:
                name = definition.Name
                guid = u'{}'.format(definition.GUID)
            except Exception:
                continue
            label = u'[{}]　{}'.format(group.Name, name)
            while label in labels:
                label += u' '
            labels[label] = {'name': name, 'guid': guid,
                             'external': definition,
                             'kind': logic.KIND_TEXT,
                             'used_by': u'（來自共用參數檔）'}
            order.append(label)
    if not order:
        forms.alert(u'這個共用參數檔裡沒有任何參數定義。', title=TITLE)
        return []
    return [(label, labels[label])
            for label in sorted(order)]


def _scratch_definition_file(app):
    """``(definition_file, previous_path, scratch_path)``; caller restores."""
    handle, scratch = tempfile.mkstemp(suffix='.txt',
                                       prefix='RevitMCP_AreaParams_')
    os.close(handle)
    with open(scratch, 'w') as stream:
        stream.write('')
    try:
        previous = app.SharedParametersFilename
    except Exception:
        previous = u''
    app.SharedParametersFilename = scratch
    return app.OpenSharedParameterFile(), previous, scratch


def _make_definitions(definition_file, specs):
    """``[(spec, ExternalDefinition)]`` created in the scratch file."""
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
    for spec in specs:
        data_type = _spec_for(spec.get('kind'))
        if data_type is None:
            raise Exception(u'這個 Revit 版本認不得「{}」這種資料型別。'.format(
                logic.kind_label(spec.get('kind'))))
        options = DB.ExternalDefinitionCreationOptions(spec['name'], data_type)
        options.GUID = Guid(spec['guid'])
        made.append((spec, group.Definitions.Create(options)))
    return made


def _bind(doc, pairs):
    """Bind each definition to Areas. Returns ``(count, error)``."""
    category = getattr(DB.BuiltInCategory, 'OST_Areas', None)
    if category is None:
        return 0, u'這個 Revit 版本沒有「面積」品類。'
    transaction = DB.Transaction(doc, TITLE)
    try:
        transaction.Start()
        areas = doc.Settings.Categories.get_Item(category)
        group = getattr(DB.BuiltInParameterGroup, 'PG_IDENTITY_DATA', None)
        done = 0
        for spec, external in pairs:
            categories = DB.CategorySet()
            categories.Insert(areas)
            binding = DB.InstanceBinding(categories)
            inserted = False
            if group is not None:
                try:
                    inserted = doc.ParameterBindings.Insert(external, binding,
                                                            group)
                except Exception:
                    inserted = False
            if not inserted:
                inserted = doc.ParameterBindings.Insert(external, binding)
            if not inserted:
                raise Exception(u'參數「{}」綁定失敗。'.format(spec['name']))
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


def _print_plan(plan, from_shared_file):
    output = script.get_output()
    output.print_md(u'## {}'.format(TITLE))
    if plan['create']:
        output.print_table(
            table_data=[[item['name'], logic.kind_label(item.get('kind')),
                         item['guid'], item.get('used_by') or u'']
                        for item in plan['create']],
            columns=[u'參數名稱', u'型別', u'GUID', u'供哪個按鈕使用'])
    if plan['blocked']:
        output.print_table(
            table_data=[[entry['record'].get('name') or u'(空白)',
                         entry['reason']]
                        for entry in plan['blocked']],
            columns=[u'參數名稱', u'略過原因'])
    if not from_shared_file:
        output.print_md(
            u'> GUID 由參數名稱推導：同名在每個專案都會是**同一個**共用參數，'
            u'排程與標籤才跨檔一致。若貴單位已有共用參數檔，用那個檔更好。')


def main():
    doc = revit.doc
    if doc is None:
        forms.alert(u'請先開啟 Revit 專案文件，再執行。',
                    title=TITLE, exitscript=True)
    app = doc.Application

    defaults = logic.default_parameters()
    values = ui.ask(_build_spec(defaults))
    if values is None:
        return

    from_shared_file = (values['source'] == SOURCE_FILE)
    if from_shared_file:
        options = _shared_options(app)
        if options is None:
            return
        if not options:
            # 檔案不可用時退回自建，而不是走進死路。
            from_shared_file = False
            specs = _named_specs(defaults, values)
        else:
            chosen = ui.ask(_build_shared_spec(options))
            if chosen is None:
                return
            specs = list(chosen['picked'])
    else:
        specs = _named_specs(defaults, values)

    if not specs:
        forms.alert(u'沒有選擇任何參數。', title=TITLE)
        return

    plan = logic.build_plan(specs, _bound_names(doc))
    _print_plan(plan, from_shared_file)
    summary = logic.plan_lines(plan, from_shared_file)

    if not logic.has_work(plan):
        forms.alert(u'【預覽】沒有要建立的參數，模型未變更。\n\n{}'.format(
            summary), title=TITLE)
        return

    if not forms.alert(
            u'【dry-run 預覽】模型目前未變更。\n\n{}\n\n確定要建立嗎？'.format(
                summary), title=TITLE, yes=True, no=True):
        return

    previous_sp = None
    scratch = None
    try:
        if from_shared_file:
            # The definitions already exist in the office's file; use them.
            pairs = [(item, item['external']) for item in plan['create']]
        else:
            definition_file, previous_sp, scratch = _scratch_definition_file(
                app)
            if definition_file is None:
                forms.alert(u'無法建立暫存的共用參數檔。', title=TITLE)
                return
            pairs = _make_definitions(definition_file, plan['create'])
        done, error = _bind(doc, pairs)
        if error:
            forms.alert(u'建立失敗，交易已完整回復，模型沒有變更。\n\n{}'.format(
                error), title=TITLE)
            return
        forms.alert(u'已建立並綁定 {} 個 Area 專案參數。\n\n'
                    u'現在可以用「面積計算式」與「專有共用面積類型」了。'
                    .format(done), title=TITLE)
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


try:
    main()
except Exception as error:
    forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
