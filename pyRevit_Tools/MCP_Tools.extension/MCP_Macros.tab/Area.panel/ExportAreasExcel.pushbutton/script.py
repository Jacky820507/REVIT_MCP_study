# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""面積清單 Excel 匯出（JAC 01.01）— read-only.

「多筆」 is the point: several area schemes go into one workbook, one worksheet
each plus a summary that totals every scheme by level. Exporting one scheme at
a time is what leaves people reconciling numbers by hand.

Columns are chosen rather than fixed — a 法定面積 review and a 銷售面積 sheet
want different ones, and shipping a fixed set just sends people back to Excel
to delete columns.

Reads only. Nothing is written to the model and no Transaction is opened.

UI 走共用視窗（``mcp_window``）：面積計畫、樓層、欄位三個都是複選，用三個接續
的對話框問，改一個就得把另外兩個重答一次。
"""

__title__ = u'面積清單\nExcel'
__author__ = 'RevitMCP'

import os

from pyrevit import forms, revit, script

import area_export_logic as logic
import area_placement_logic as audit
import area_scheme_sources as sources
import mcp_window as ui
import mcp_window_logic as uilogic
import xlsx_writer


TITLE = u'面積清單 Excel'


def _safe_filename(text):
    cleaned = []
    for char in u'{}'.format(text or u''):
        cleaned.append(u'_' if char in u'\\/:*?"<>|' else char)
    return u''.join(cleaned).strip() or u'Areas'


def _default_name(doc):
    try:
        title = os.path.splitext(os.path.basename(doc.PathName))[0]
    except Exception:
        title = u''
    return u'{}_面積清單.xlsx'.format(_safe_filename(title or u'Revit'))


def _build_spec(doc, levels):
    """整份視窗規格；沒有面積計畫時回 ``None``。"""
    schemes = sources.area_schemes(doc)
    if not schemes:
        return None, None

    scheme_options = [(sources.scheme_label(scheme), scheme)
                      for scheme in schemes]
    scheme_options.sort(key=lambda item: item[0])

    level_options = sorted(
        [(entry[0], level_id) for level_id, entry in levels.items()],
        key=lambda item: levels[item[1]][1])

    field_options = logic.field_labels()

    fields = [
        uilogic.section(u'匯出範圍'),
        uilogic.multichoice(
            'schemes', u'面積計畫（可複選）', scheme_options,
            default=[scheme for unused, scheme in scheme_options[:1]],
            required=True,
            help=u'多個計畫會進同一個活頁簿，各自一張工作表，另加一張'
                 u'依樓層彙總的總表——一次匯一個才是讓人回頭用手對數字的原因。'),
        uilogic.multichoice(
            'levels', u'樓層（不勾就是全部）', level_options,
            help=u'一個都不勾代表全部樓層，這是預設行為。'),

        uilogic.section(u'欄位'),
        uilogic.multichoice(
            'fields', u'要匯出的欄位', field_options,
            default=list(logic.DEFAULT_FIELD_KEYS), required=True,
            help=u'欄位順序照這份清單，不是照你勾選的順序——'
                 u'否則同一份設定匯兩次會得到欄位順序不同的檔案。'),
    ]

    spec = uilogic.spec(
        TITLE, fields,
        subtitle=u'多個面積計畫匯成一個活頁簿，附依樓層彙總的總表',
        badge=uilogic.BADGE_READONLY,
        run_label=u'選擇檔案並匯出',
        footnote=u'唯讀，不開 Transaction。預覽同時列在 pyRevit 輸出視窗。',
        width=980, height=720)
    return spec, scheme_options


def _ordered_fields(chosen):
    """欄位順序照選單，不照勾選順序。"""
    keys = [key for unused, key in logic.field_labels() if key in set(chosen)]
    return keys or list(logic.DEFAULT_FIELD_KEYS)


def _print_preview(grouped, field_keys):
    output = script.get_output()
    output.print_md(u'## {}'.format(TITLE))
    keys = logic.resolve_fields(field_keys)
    for scheme_name, records in grouped:
        output.print_md(u'### {}（{} 個面積）'.format(scheme_name,
                                                  len(records)))
        if not records:
            continue
        rows, unused = logic.build_sheet(records, keys)
        output.print_table(table_data=rows[1:], columns=rows[0])


def main():
    doc = revit.doc
    if doc is None:
        forms.alert(u'請先開啟 Revit 專案文件，再匯出面積清單。',
                    title=TITLE, exitscript=True)

    levels = sources.level_index(doc)
    spec, unused_options = _build_spec(doc, levels)
    if spec is None:
        forms.alert(u'這個專案沒有任何面積計畫（Area Scheme）。', title=TITLE)
        return

    values = ui.ask(spec)
    if values is None:
        return

    schemes = values['schemes']
    # 一個都不勾＝全部樓層，這是規格裡寫明的預設，不是漏答。
    allowed = set(values['levels']) or None
    field_keys = _ordered_fields(values['fields'])

    grouped = []
    total = 0
    for scheme in schemes:
        scheme_id = sources.id_value(scheme.Id)
        records = sources.collect_areas(doc, scheme_id=scheme_id,
                                        levels=levels)
        if allowed is not None:
            records = [row for row in records if row['level_id'] in allowed]
        # Status and warnings are optional columns, but computing them is
        # cheap and lets one export double as the audit trail.
        warnings = sources.warning_flags(
            doc, area_ids=set(row['id'] for row in records))
        for row in records:
            row['warnings'] = warnings.get(row['id']) or []
            row['status'] = audit.area_status(row, row['warnings'])
        grouped.append((sources.element_name(scheme), records))
        total += len(records)

    if not total:
        forms.alert(u'選定的範圍內沒有面積，未產生檔案。', title=TITLE)
        return

    _print_preview(grouped, field_keys)
    path = forms.save_file(file_ext='xlsx', default_name=_default_name(doc))
    if not path:
        return

    sheets = logic.build_workbook(grouped, field_keys)
    try:
        xlsx_writer.write_workbook(path, sheets)
    except Exception as error:
        forms.alert(u'寫入 Excel 失敗：\n\n{}'.format(error), title=TITLE)
        return
    forms.alert(u'{}\n\n明細已列在 pyRevit 輸出視窗。'.format(
        logic.export_lines(grouped, field_keys, path)), title=TITLE)


try:
    main()
except Exception as error:
    forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
