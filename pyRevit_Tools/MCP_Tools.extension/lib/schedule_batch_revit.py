# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""批量建立明細表／批量新增欄位的 Revit 端讀寫。

IronPython 2.7。純邏輯（命名、撞名、欄位比對）在 ``schedule_batch_logic``；
這裡只碰 Revit API。兩顆按鈕共用：

- ``BatchCreateSchedules``：``probe_categories`` → ``create_schedules``
- ``BatchAddScheduleFields``：``schedule_field_names`` → ``add_fields``

欄位以名稱比對、同名時實例參數優先，與 MCP 工具
``batch_create_view_schedules`` / ``add_schedule_fields`` 的 C# 端同一套規則。
"""

from Autodesk.Revit import DB

import schedule_batch_logic as logic


def id_value(element_id):
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


def user_schedules(doc):
    """一般明細表（排除樣板、圖框修訂表），依名稱排序。"""
    result = []
    for view in DB.FilteredElementCollector(doc).OfClass(DB.ViewSchedule):
        try:
            if view.IsTemplate or view.IsTitleblockRevisionSchedule:
                continue
            view.Definition
        except Exception:
            continue
        result.append(view)
    result.sort(key=lambda v: v.Name.lower())
    return result


def category_name(doc, schedule):
    try:
        category = DB.Category.GetCategory(doc, schedule.Definition.CategoryId)
        return category.Name if category is not None else u''
    except Exception:
        return u''


def _field_key(field_type, parameter_id):
    return u'{}|{}'.format(int(field_type), id_value(parameter_id))


def _schedulable_name(doc, schedulable):
    try:
        return schedulable.GetName(doc)
    except Exception:
        return None


def schedulable_names(doc, schedule):
    """明細表可加入的欄位名稱（去重，依名稱排序）。"""
    names = {}
    for schedulable in schedule.Definition.GetSchedulableFields():
        name = _schedulable_name(doc, schedulable)
        if name:
            names.setdefault(name.strip().lower(), name.strip())
    return sorted(names.values(), key=lambda n: n.lower())


def present_names(doc, schedule):
    """明細表上已經有的欄位名稱。"""
    definition = schedule.Definition
    names = []
    for field_id in definition.GetFieldOrder():
        field = definition.GetField(field_id)
        try:
            names.append(field.GetName())
        except Exception:
            pass
    return names


def _candidate_categories(doc):
    candidates = []
    for category in doc.Settings.Categories:
        try:
            if category.Parent is not None:
                continue
            if category.CategoryType not in (DB.CategoryType.Model,
                                             DB.CategoryType.Annotation):
                continue
            if not category.AllowsBoundParameters:
                continue
            try:
                if category.IsTagCategory:
                    continue
            except Exception:
                pass
        except Exception:
            continue
        candidates.append(category)
    candidates.sort(key=lambda c: c.Name.lower())
    return candidates


def probe_categories(doc):
    """哪些品類能建明細表、各有哪些可用欄位。

    唯一可靠的辦法是真的建一張看 ``GetSchedulableFields``，所以在一個**一定
    會回復**的交易裡逐品類試建，讀完欄位名稱就丟掉。回傳
    ``[{'name', 'id', 'fields': [名稱]}]``，建不出來的品類不收。
    """
    result = []
    transaction = DB.Transaction(doc, u'探測可建明細表的品類（回復）')
    transaction.Start()
    try:
        for category in _candidate_categories(doc):
            try:
                schedule = DB.ViewSchedule.CreateSchedule(doc, category.Id)
                fields = schedulable_names(doc, schedule)
            except Exception:
                continue
            if fields:
                result.append({'name': category.Name,
                               'id': id_value(category.Id),
                               'fields': fields})
    finally:
        transaction.RollBack()
    return result


def add_fields(doc, schedule, wanted, apply):
    """把欄位（依名稱）加到明細表；``apply=False`` 只算結果。

    回傳 ``{'added', 'already', 'missing'}`` 三個名稱清單。同名時實例參數
    優先；明細表上已有的欄位（同 FieldType＋ParameterId）列入 ``already``，
    不重複加。
    """
    definition = schedule.Definition
    existing = set()
    for field_id in definition.GetFieldOrder():
        field = definition.GetField(field_id)
        existing.add(_field_key(field.FieldType, field.ParameterId))

    by_name = {}
    for schedulable in definition.GetSchedulableFields():
        name = _schedulable_name(doc, schedulable)
        if not name:
            continue
        key = name.strip().lower()
        current = by_name.get(key)
        is_instance = schedulable.FieldType == DB.ScheduleFieldType.Instance
        if current is None or (is_instance and current[1] is False):
            by_name[key] = (schedulable, is_instance)

    added, already, missing = [], [], []
    for raw in wanted:
        name = logic.text(raw).strip()
        if not name:
            continue
        entry = by_name.get(name.lower())
        if entry is None:
            missing.append(name)
            continue
        schedulable = entry[0]
        key = _field_key(schedulable.FieldType, schedulable.ParameterId)
        if key in existing:
            already.append(name)
            continue
        if apply:
            definition.AddField(schedulable)
        existing.add(key)
        added.append(name)
    return {'added': added, 'already': already, 'missing': missing}


def create_schedules(doc, plans, wanted, title):
    """單一 Transaction 建立所有 ``status == 'create'`` 的計畫。

    ``plans`` 每一項要有 ``category_id`` 與 ``name``。成功時回傳
    ``(failures, created)``，``failures`` 為空代表全部成功；有任何一張失敗就
    整批回復（``created`` 為空），模型不留半套。
    """
    failures = []
    created = []
    transaction = DB.Transaction(doc, title)
    transaction.Start()
    try:
        for plan in plans:
            if plan['status'] != 'create':
                continue
            try:
                schedule = DB.ViewSchedule.CreateSchedule(
                    doc, DB.ElementId(plan['category_id']))
                schedule.Name = plan['name']
                report = add_fields(doc, schedule, wanted, True)
                created.append({'name': plan['name'],
                                'id': id_value(schedule.Id),
                                'report': report})
            except Exception as error:
                failures.append(u'{}：{}'.format(plan['name'], error))
        if failures:
            transaction.RollBack()
            created = []
        else:
            transaction.Commit()
    except Exception as error:
        if transaction.HasStarted() and not transaction.HasEnded():
            transaction.RollBack()
        failures.append(u'{}'.format(error))
        created = []
    return failures, created


def add_fields_to_schedules(doc, schedules, wanted, title):
    """單一 Transaction 對多張既有明細表加欄位；任一張失敗整批回復。"""
    failures = []
    transaction = DB.Transaction(doc, title)
    transaction.Start()
    try:
        for schedule in schedules:
            try:
                add_fields(doc, schedule, wanted, True)
            except Exception as error:
                failures.append(u'{}：{}'.format(schedule.Name, error))
        if failures:
            transaction.RollBack()
        else:
            transaction.Commit()
    except Exception as error:
        if transaction.HasStarted() and not transaction.HasEnded():
            transaction.RollBack()
        failures.append(u'{}'.format(error))
    return failures
