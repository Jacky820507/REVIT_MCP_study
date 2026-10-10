# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""批量建立明細表.

複選品類 → 勾選要加入的參數欄位（各品類可用欄位的聯集）→ 命名樣板與撞名處理
→ dry-run 預覽 → 單一 Transaction 一次建完，任何一張失敗整批回復。

哪些品類能建、各有哪些欄位，是用「回復的交易裡試建」探測出來的
（``schedule_batch_revit.probe_categories``）——視窗開著時 Revit 不允許改文件，
所以探測在開視窗**之前**做完。
"""

__title__ = u'批量建立\n明細表'
__author__ = 'RevitMCP'

from pyrevit import forms, revit, script

import mcp_window as ui
import mcp_window_logic as spec_logic
import schedule_batch_logic as logic
import schedule_batch_revit as batch


TITLE = u'批量建立明細表'


def _ask_categories(probes, existing_count):
    options = [(u'{}（{} 個欄位）'.format(p['name'], len(p['fields'])),
                p['name']) for p in probes]
    spec = spec_logic.spec(
        TITLE,
        [spec_logic.multichoice(
            'categories', u'品類', options, required=True, filter=True,
            help=u'可輸入關鍵字篩選；Shift+點擊可連選。每個選到的品類建一張明細表。'),
         spec_logic.text(
             'template', u'名稱樣板', default=logic.DEFAULT_TEMPLATE,
             help=u'{category} 會換成品類名稱。Revit 不允許的字元（\\ : { } [ ] | ; < > ? ` ~）'
                  u'會換成「-」。'),
         spec_logic.choice(
             'conflict', u'名稱已存在時',
             [(u'略過（不動既有明細表）', logic.CONFLICT_SKIP),
              (u'自動加編號，如「牆明細表 (2)」', logic.CONFLICT_SUFFIX)],
             default=logic.CONFLICT_SKIP,
             help=u'目前專案已有 {} 張明細表。'.format(existing_count)),
         spec_logic.note(
             u'下一步勾選要加入的欄位，再預覽；確認前模型不會變更。')],
        badge=spec_logic.BADGE_WRITE, run_label=u'下一步：選欄位',
        width=680, height=760)
    return ui.ask(spec)


def _ask_fields(probes, chosen):
    union = logic.field_union(
        [(p['name'], p['fields']) for p in probes if p['name'] in chosen])
    total = len(chosen)
    options = []
    for name, owners in union:
        suffix = u'' if len(owners) == total else \
            u'（{}/{} 個品類）'.format(len(owners), total)
        options.append((name + suffix, name))
    spec = spec_logic.spec(
        TITLE,
        [spec_logic.multichoice(
            'fields', u'要加入的欄位', options, required=False, filter=True,
            help=u'可輸入關鍵字篩選。只有部分品類具備的欄位會標示數量，'
                 u'其餘品類的那張表會略過該欄位。順序依勾選清單的排列。'),
         spec_logic.note(
             u'一個都不勾會建出沒有欄位的空明細表。', tone='warning')],
        badge=spec_logic.BADGE_WRITE, run_label=u'預覽',
        width=680, height=760)
    values = ui.ask(spec)
    if values is None:
        return None
    return values.get('fields') or []


def _build_rows(plans, probes, wanted):
    by_name = dict((p['name'], p) for p in probes)
    rows = []
    for plan in plans:
        probe = by_name[plan['category']]
        found, missing = logic.resolve_fields(wanted, probe['fields'])
        plan['category_id'] = probe['id']
        plan['found'] = found
        plan['missing'] = missing
        status = {'create': u'建立', 'skip': u'略過'}[plan['status']]
        rows.append([plan['name'], plan['category'], status,
                     u'、'.join(found) or u'-', u'、'.join(missing) or u'-',
                     plan['note'] or u'-'])
    return rows


def _print_preview(rows, counts):
    output = script.get_output()
    output.print_md(u'## {} — 預覽'.format(TITLE))
    output.print_md(u'建立 **{}** 張、略過 **{}** 張。'.format(
        counts.get('create', 0), counts.get('skip', 0)))
    output.print_table(
        table_data=rows,
        columns=[u'明細表名稱', u'品類', u'動作', u'加入欄位', u'對不到的欄位',
                 u'備註'])


def main():
    doc = revit.doc
    probes = batch.probe_categories(doc)
    if not probes:
        forms.alert(u'找不到可以建立明細表的品類。', title=TITLE)
        return
    existing = [v.Name for v in
                batch.DB.FilteredElementCollector(doc)
                .OfClass(batch.DB.ViewSchedule)]

    values = _ask_categories(probes, len(existing))
    if not values:
        return
    chosen = values.get('categories') or []
    if not chosen:
        return
    wanted = _ask_fields(probes, chosen)
    if wanted is None:
        return

    plans = logic.plan_creations(
        chosen, values.get('template'), existing, values.get('conflict'))
    rows = _build_rows(plans, probes, wanted)
    counts = logic.summarize(plans)
    _print_preview(rows, counts)
    if not counts.get('create'):
        forms.alert(u'全部撞名而略過，沒有要建立的明細表。明細在輸出視窗。',
                    title=TITLE)
        return

    answer = forms.alert(
        u'【dry-run 預覽】模型目前未變更。\n\n將建立 {} 張明細表（略過 {} 張），'
        u'明細在輸出視窗。\n\n確定建立嗎？'.format(
            counts.get('create', 0), counts.get('skip', 0)),
        title=TITLE, yes=True, no=True)
    if not answer:
        return

    failures, created = batch.create_schedules(doc, plans, wanted, TITLE)
    if failures:
        forms.alert(
            u'有 {} 張建不起來，交易已完整回復，模型未變更。\n\n{}'.format(
                len(failures), u'\n'.join(failures[:25])), title=TITLE)
        return
    forms.alert(u'已建立 {} 張明細表。'.format(len(created)), title=TITLE)


try:
    main()
except Exception as error:
    forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
