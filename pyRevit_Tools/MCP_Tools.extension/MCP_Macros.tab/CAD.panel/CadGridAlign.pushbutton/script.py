# -*- coding: utf-8 -*-
from __future__ import division, unicode_literals

"""CAD 對齊網格匯入——多視圖 × 多 DWG，依樓層配對後自動對齊 Grid。

每次匯入 CAD 都要對網格、再把 CAD 交點貼到 Revit 交點。這顆按鈕把那件事
批次化：

1. 選平面視圖（多選）與資料夾中的 CAD（多選）。
2. 依名稱樓層配對（「一層」＝1F、「地下一層」＝B1…），預覽表可手動改。
3. 匯入或連結：僅目前視圖、自動判斷單位、原點對原點。
4. 讀 CAD 軸線圖層算平移量——有軸號（ODA + ezdxf）以軸號為準，沒有則用
   軸距序列比對；有歧義就**不放**並說明，不猜。
5. 全部在一個 TransactionGroup 裡試跑，看完結果再決定保留或整批復原。
"""

__title__ = u'CAD對齊\n網格匯入'
__author__ = 'RevitMCP'

import codecs
import datetime
import os

from Autodesk.Revit import DB
from pyrevit import forms, revit, script

import cad_align_logic as logic
import cad_align_sources as sources
import cad_grid_label_runner as label_runner
import mcp_window as ui
import mcp_window_logic as uilogic


TITLE = u'CAD 對齊網格匯入'

MODES = (
    (u'匯入（Import，檔案內嵌進專案）', sources.MODE_IMPORT),
    (u'連結（Link，保留與 DWG 的關聯）', sources.MODE_LINK),
)


def _settings_spec(views, files, folder):
    fields = [
        uilogic.section(u'來源'),
        uilogic.multichoice('views', u'要放 CAD 的平面視圖（可複選）', views,
                            required=True),
        uilogic.multichoice('files', u'{} 內的 CAD 檔（可複選）'.format(folder),
                            files, default=[path for unused, path in files],
                            required=True),

        uilogic.section(u'放置方式',
                        u'固定：僅目前視圖、自動判斷匯入單位、原點對原點再平移。'),
        uilogic.choice('mode', u'匯入或連結', MODES,
                       default=sources.MODE_IMPORT),
        uilogic.choice('color', u'顏色', sources.COLOR_MODES,
                       default='BlackAndWhite'),
        uilogic.boolean('visible_only', u'只匯入 CAD 中可見的圖層',
                        default=False),
        uilogic.boolean('pin', u'對齊後鎖定（Pin）', default=True),

        uilogic.section(u'對齊依據'),
        uilogic.text('grid_layer', u'CAD 軸線圖層',
                     default=logic.DEFAULT_GRID_LAYER, required=True),
        uilogic.text('label_layer', u'CAD 軸號圖層',
                     default=logic.DEFAULT_LABEL_LAYER),
        uilogic.boolean('use_labels', u'讀軸號文字（需 Python + ezdxf，DWG 另需 '
                        u'ODA File Converter）', default=True),
        uilogic.number('tolerance', u'軸線重合容差',
                       default=logic.DEFAULT_TOLERANCE_MM, minimum=0.1,
                       unit=u'mm'),
        uilogic.note(u'Revit 讀不到匯入 CAD 裡的文字，軸號要另外從檔案讀。'
                     u'讀不到時改用軸距比對；等距軸網會有「差一跨」的歧義，'
                     u'那一筆會略過並說明，不會亂貼。', tone='info'),
    ]
    return uilogic.spec(TITLE, fields,
                        subtitle=u'選視圖與 CAD，下一步預覽樓層配對',
                        badge=uilogic.BADGE_WRITE, run_label=u'配對預覽',
                        width=980, height=860)


def _pairing_spec(view_rows, file_rows, pairing):
    options = [(u'（不處理）', None)] + [(name, path)
                                        for name, path in file_rows]
    fields = [uilogic.section(u'樓層配對',
                              u'依名稱中的樓層自動配對；可逐一改選。')]
    for index, (label, view) in enumerate(view_rows):
        entry = pairing[index]
        help_text = u'樓層 {}'.format(entry['code']) if entry['code'] else u''
        if entry['reason']:
            help_text = (help_text + u'　' if help_text else u'') + \
                entry['reason']
        fields.append(uilogic.choice('pair_{}'.format(index), label, options,
                                     default=entry['file'], help=help_text,
                                     required=False))
    return uilogic.spec(TITLE, fields, subtitle=u'確認每個視圖要放哪個 CAD',
                        badge=uilogic.BADGE_WRITE, run_label=u'試跑對齊',
                        footnote=u'試跑會真的匯入並對齊，但結果確認前都可整批復原。',
                        width=980, height=760)


def _read_labels(paths, label_layer):
    """``({path: [labels]}, 說明)``。失敗不擋流程。"""
    # 沒裝 ODA 也能讀軸號：同資料夾有同名 .dxf（CAD 另存 DXF 即可）就改讀它。
    # 放進 Revit 的仍是 DWG，DXF 只用來取文字。
    source = {}
    for path in paths:
        dxf = os.path.splitext(path)[0] + '.dxf'
        if path.lower().endswith('.dwg') and os.path.exists(dxf):
            source[path] = dxf
        else:
            source[path] = path
    result, problem = label_runner.run(sorted(set(source.values())),
                                       label_layer)
    if result is None:
        return {}, problem
    read = result.get('files') or {}
    labels = {}
    notes = []
    for path in paths:
        entry = read.get(source[path]) or {}
        if entry.get('error'):
            notes.append(u'{}：{}'.format(os.path.basename(source[path]),
                                          entry['error']))
            continue
        labels[os.path.normcase(path)] = entry.get('labels') or []
    unread_dwg = [p for p in paths
                  if p.lower().endswith('.dwg') and source[p] == p]
    if unread_dwg and not result.get('oda'):
        notes.insert(0, u'本機沒有 ODA File Converter，DWG 軸號讀不到；'
                     u'把 CAD 另存同名 .dxf 放在同資料夾即可讀取，'
                     u'否則改用軸距比對')
    return labels, u'\n'.join(notes)


def _scaled_labels(raw_labels, cad_lines):
    if not raw_labels or not cad_lines:
        return []
    scale, hits = logic.choose_label_scale(raw_labels, cad_lines)
    if not scale or hits == 0:
        return []
    return [{'text': label['text'], 'x': label['x'] * scale,
             'y': label['y'] * scale} for label in raw_labels]


def _process(doc, job, settings, labels_by_path):
    """一筆 視圖 × CAD。回傳報告 entry。每筆自己一個 Transaction：
    沒對齊成功的那筆會被 RollBack，模型裡不會留下沒對齊的 CAD。"""
    view = job['view']
    path = job['path']
    name = os.path.basename(path)
    entry = {'view': view.Name, 'file': name, 'code': job['code'],
             'plan': None, 'status': u'', 'id': None, 'note': u''}

    if sources.existing_import(doc, view, name) is not None:
        entry['status'] = u'略過'
        entry['note'] = u'這個視圖已有同名 CAD'
        return entry

    revit_grids = sources.revit_grid_lines(doc, view)
    transaction = DB.Transaction(doc, u'CAD 對齊：{}'.format(name))
    transaction.Start()
    try:
        instance = sources.place_cad(doc, path, view, settings['options'],
                                     settings['mode'])
        doc.Regenerate()
        cad_lines = sources.grid_layer_lines(doc, instance, view,
                                             settings['grid_layer'])
        labels = _scaled_labels(
            labels_by_path.get(os.path.normcase(path)), cad_lines)
        plan = logic.plan_alignment(cad_lines, revit_grids, labels,
                                    tolerance=settings['tolerance'])
        entry['plan'] = plan
        if plan['status'] != logic.STATUS_READY:
            transaction.RollBack()
            entry['status'] = plan['status']
            return entry
        sources.move_and_pin(doc, instance, plan['translation'],
                             settings['pin'])
        transaction.Commit()
        entry['status'] = u'已對齊'
        entry['id'] = sources.id_value(instance.Id)
        return entry
    except Exception as error:
        if transaction.HasStarted() and not transaction.HasEnded():
            transaction.RollBack()
        entry['status'] = u'失敗'
        entry['note'] = u'{}'.format(error)
        return entry


def _print_report(entries, label_note):
    output = script.get_output()
    output.print_md(u'## {}'.format(TITLE))
    if label_note:
        output.print_md(u'> 軸號：{}'.format(label_note.replace(u'\n', u'；')))
    rows = []
    for entry in entries:
        plan = entry.get('plan') or {}
        translation = plan.get('translation')
        rows.append([
            entry['view'], entry['file'], entry.get('code') or u'',
            entry['status'],
            u'({:.1f}, {:.1f})'.format(*translation) if translation else u'',
            output.linkify(DB.ElementId(entry['id'])) if entry.get('id')
            else u'',
            entry.get('note') or logic.describe(plan),
        ])
    output.print_table(table_data=rows,
                       columns=[u'視圖', u'CAD', u'樓層', u'狀態',
                                u'平移(mm)', u'元素', u'說明'])


def _write_csv(folder, entries):
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    path = os.path.join(folder, u'CAD對齊報告_{}.csv'.format(stamp))
    stream = codecs.open(path, 'w', 'utf-8-sig')
    try:
        stream.write(logic.csv_text(logic.report_rows(entries)))
    finally:
        stream.close()
    return path


def main():
    doc = revit.doc
    if doc is None:
        forms.alert(u'請先開啟 Revit 專案。', title=TITLE, exitscript=True)

    folder = forms.pick_folder(title=u'選擇 CAD 檔所在資料夾')
    if not folder:
        return
    files = sources.cad_files(folder)
    if not files:
        forms.alert(u'這個資料夾裡沒有 .dwg／.dxf。', title=TITLE)
        return
    views = sources.plan_views(doc)
    if not views:
        forms.alert(u'專案裡沒有平面視圖。', title=TITLE)
        return

    values = ui.ask(_settings_spec(views, files, folder))
    if values is None:
        return

    picked_views = [(label, view) for label, view in views
                    if view in values['views']]
    picked_files = [(name, path) for name, path in files
                    if path in values['files']]
    auto = logic.pair_views_to_files(
        [(index, view.Name) for index, (unused, view)
         in enumerate(picked_views)],
        [(path, name) for name, path in picked_files])

    pairs = ui.ask(_pairing_spec(picked_views, picked_files,
                                 [auto[index] for index in
                                  range(len(picked_views))]))
    if pairs is None:
        return
    jobs = []
    for index, (unused, view) in enumerate(picked_views):
        path = pairs.get('pair_{}'.format(index))
        if path:
            jobs.append({'view': view, 'path': path,
                         'code': auto[index]['code']})
    if not jobs:
        forms.alert(u'沒有任何視圖配到 CAD，未執行。', title=TITLE)
        return

    labels_by_path, label_note = {}, u''
    if values['use_labels'] and values.get('label_layer'):
        unique_paths = sorted(set(job['path'] for job in jobs))
        labels_by_path, label_note = _read_labels(unique_paths,
                                                  values['label_layer'])

    settings = {
        'options': sources.build_options(values['color'],
                                         values['visible_only']),
        'mode': values['mode'],
        'grid_layer': values['grid_layer'],
        'tolerance': values['tolerance'],
        'pin': values['pin'],
    }

    group = DB.TransactionGroup(doc, TITLE)
    group.Start()
    entries = []
    try:
        with forms.ProgressBar(title=u'CAD 對齊中… ({value}/{max_value})',
                               cancellable=True) as progress:
            for index, job in enumerate(jobs):
                if progress.cancelled:
                    break
                entries.append(_process(doc, job, settings, labels_by_path))
                progress.update_progress(index + 1, len(jobs))
    except Exception:
        group.RollBack()
        raise

    _print_report(entries, label_note)
    done = len([e for e in entries if e['status'] == u'已對齊'])
    if done == 0:
        group.RollBack()
        csv_path = _write_csv(folder, entries)
        forms.alert(u'沒有任何一筆對齊成功，模型未變更。\n\n'
                    u'明細在 pyRevit 輸出視窗，報告：\n{}'.format(csv_path),
                    title=TITLE)
        return

    keep = forms.alert(
        u'試跑完成：{} 筆已對齊，{} 筆未放置（見輸出視窗）。\n\n'
        u'請在視圖中確認 CAD 與網格是否重合。\n'
        u'要保留結果嗎？選「否」會整批復原。'.format(done, len(entries) - done),
        title=TITLE, yes=True, no=True)
    if keep:
        group.Assimilate()
    else:
        group.RollBack()
        for entry in entries:
            if entry['status'] == u'已對齊':
                entry['status'] = u'已復原'
    csv_path = _write_csv(folder, entries)
    forms.alert(u'{}。\n\n報告：{}'.format(
        u'已保留 {} 筆'.format(done) if keep else u'已整批復原', csv_path),
        title=TITLE)


try:
    main()
except Exception as error:
    forms.alert(u'執行失敗：\n\n{}'.format(error), title=TITLE)
