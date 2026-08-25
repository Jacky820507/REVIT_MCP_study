# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""WPF window for the 門窗表 Excel button (mirrors the 停車位 Excel flow)."""

import os

from pyrevit import forms

import door_window_excel as core
import door_window_excel_logic as logic
import takeoff_standalone

try:
    reload(core)
    reload(logic)
except Exception:
    pass


TITLE = core.TITLE


class DoorWindowWindow(forms.WPFWindow):
    def __init__(self, doc, entry_options):
        xaml = os.path.join(
            os.path.dirname(__file__), '..', 'MCP_Macros.tab',
            'Takeoff.panel', 'DoorWindowExcel.pushbutton',
            'DoorWindowExcel.xaml')
        forms.WPFWindow.__init__(self, os.path.abspath(xaml))
        self.doc = doc
        self.entry_options = dict(entry_options or {})
        self.standalone_mode = (
            takeoff_standalone.entry_mode(self.entry_options)
            == takeoff_standalone.MODE_STANDALONE)
        self.result = None
        self.links = core.list_links(doc)
        self.schedules = core.list_schedules(doc)
        self.selected_link_ids = list(
            self.entry_options.get('selected_link_ids') or [])
        self.selected_schedule_ids = []
        self.selected_level_keys = list(
            self.entry_options.get('selected_level_keys') or [])
        self.levels = core.list_levels(doc, self.selected_link_ids)

        self.browseButton.Click += self.browse_clicked
        self.previewButton.Click += self.preview_clicked
        self.updateButton.Click += self.update_clicked
        self.cancelButton.Click += self.cancel_clicked
        self.selectLinksButton.Click += self.select_links_clicked
        self.selectSchedulesButton.Click += self.select_schedules_clicked
        self.selectLevelsButton.Click += self.select_levels_clicked
        self.sourceModeCombo.SelectionChanged += self.invalidate_preview
        self.pathBox.TextChanged += self.invalidate_preview
        path = self.entry_options.get('workbook_path')
        self.pathBox.Text = (
            path if path else u'（未選主要 Excel，將另存新的 .xlsx）')
        self.pathBox.IsReadOnly = True
        self.browseButton.IsEnabled = False
        self.selectLinksButton.IsEnabled = False
        self.selectLevelsButton.IsEnabled = False
        if self.standalone_mode:
            self.updateButton.Content = u'匯出 Excel'
            self.statusText.Text = u'請設定資料來源模式並產生預覽。'
        self._sync_summaries()

    # --- state ---------------------------------------------------------
    def _source_mode(self):
        return (core.SOURCE_MODE_SCHEDULES
                if int(self.sourceModeCombo.SelectedIndex) == 1
                else core.SOURCE_MODE_AUTO)

    def _sync_summaries(self):
        if self.selected_link_ids:
            names = [choice.label for choice in self.links
                     if choice.element_id in set(self.selected_link_ids)]
            self.linkSummaryText.Text = u'已選 {} 個連結模型：{}'.format(
                len(names), u'、'.join(names[:3]))
        else:
            self.linkSummaryText.Text = (
                u'未選取連結模型（只計算主模型）' if self.links
                else u'此專案沒有連結模型')
        if self._source_mode() == core.SOURCE_MODE_SCHEDULES:
            if self.selected_schedule_ids:
                names = [c.label for c in self.schedules
                         if c.element_id in set(self.selected_schedule_ids)]
                self.scheduleSummaryText.Text = u'已選 {} 張：{}'.format(
                    len(names), u'、'.join(names[:3]))
            else:
                self.scheduleSummaryText.Text = u'尚未選取明細表'
        else:
            self.scheduleSummaryText.Text = u'自動模式不使用明細表'
        if self.selected_level_keys:
            names = [c.label for c in self.levels
                     if c.element_id in set(self.selected_level_keys)]
            self.levelSummaryText.Text = u'已選 {} 個樓層：{}'.format(
                len(names), u'、'.join(names[:4]))
        else:
            self.levelSummaryText.Text = u'未篩選（全部樓層都抓）'

    def _refresh_levels(self):
        """Rebuild the level list for the current link selection.

        Levels are identified per source model, so dropping a link must also
        drop its levels — otherwise a stale key would silently filter nothing.
        """
        self.levels = core.list_levels(self.doc, self.selected_link_ids)
        available = set(choice.element_id for choice in self.levels)
        self.selected_level_keys = [key for key in self.selected_level_keys
                                    if key in available]

    def invalidate_preview(self, sender=None, args=None):
        self.result = None
        self.updateButton.IsEnabled = False
        self.statusText.Text = u'設定已變更，請重新產生預覽。'
        self._sync_summaries()

    # --- pickers -------------------------------------------------------
    def _pick(self, choices, selected_ids, title, button):
        chosen = set(selected_ids)
        options = [forms.TemplateListItem(
            choice.label, checked=choice.element_id in chosen)
            for choice in choices]
        picked = forms.SelectFromList.show(
            options, title=title, button_name=button,
            multiselect=True, width=760, height=620)
        if picked is None:
            return None
        labels = set(u'{}'.format(getattr(item, 'item', item))
                     for item in picked)
        return [c.element_id for c in choices if c.label in labels]

    def select_links_clicked(self, sender, args):
        if not self.links:
            forms.alert(u'此專案沒有 Revit 連結模型。', title=TITLE)
            return
        picked = self._pick(self.links, self.selected_link_ids,
                            u'選擇要納入的 Revit 連結模型',
                            u'使用選取的連結模型')
        if picked is None:
            return
        self.selected_link_ids = picked
        self._refresh_levels()
        self.invalidate_preview()

    def select_levels_clicked(self, sender, args):
        self._refresh_levels()
        if not self.levels:
            forms.alert(u'找不到任何樓層。', title=TITLE)
            return
        picked = self._pick(self.levels, self.selected_level_keys,
                            u'選擇要統計的樓層（不勾選＝全部樓層）',
                            u'使用選取的樓層')
        if picked is None:
            return
        self.selected_level_keys = picked
        self.invalidate_preview()

    def select_schedules_clicked(self, sender, args):
        if not self.schedules:
            forms.alert(u'此專案沒有可用的明細表。', title=TITLE)
            return
        picked = self._pick(self.schedules, self.selected_schedule_ids,
                            u'選擇門窗明細表', u'使用選取的明細表')
        if picked is None:
            return
        self.selected_schedule_ids = picked
        self.invalidate_preview()

    def browse_clicked(self, sender, args):
        return

    # --- preview -------------------------------------------------------
    def preview_clicked(self, sender, args):
        path = self.entry_options.get('workbook_path')
        if (not self.standalone_mode
                and (not path or not os.path.isfile(path))):
            forms.alert(u'請先選擇存在的 Excel 檔案。', title=TITLE)
            return
        source_mode = self._source_mode()
        if (source_mode == core.SOURCE_MODE_SCHEDULES
                and self.entry_options.get('include_host', True)
                and not self.selected_schedule_ids):
            forms.alert(u'明細表模式需要先選取至少一張明細表。', title=TITLE)
            return
        excel = workbook = None
        try:
            result = core.collect_counts_for_options(
                self.doc, self.entry_options, source_mode,
                self.selected_schedule_ids)
            if self.standalone_mode:
                tables = logic.standalone_tables(result)
                self.previewBox.Text = u'\n'.join([
                    u'輸出模式：建立新的 standalone .xlsx',
                    u'本次讀取：{}'.format(u'　'.join(result['sources'])),
                    u'門窗合計：{} 樘'.format(result['total']),
                    u'數量明細：{} 列'.format(len(tables['detail_rows'])),
                    u'公式摘要：{} 列（Excel 公式）'.format(
                        len(tables['formula_rows'])),
                    u'分頁：數量明細／公式摘要／稽核',
                ])
                self.result = {
                    'mode': takeoff_standalone.MODE_STANDALONE,
                    'takeoff': result,
                    'tables': tables,
                }
                self.updateButton.IsEnabled = True
                self.statusText.Text = u'預覽通過，可另存新的 Excel。'
                return
            excel, workbook = core._excel_open(path, True)
            inspection = core.inspect_workbook(workbook)
        except Exception as error:
            core._excel_close(excel, workbook)
            forms.alert(u'產生預覽失敗：\n\n{}'.format(error), title=TITLE)
            return
        core._excel_close(excel, workbook)

        total = result['total']
        sources = result['sources']
        plan = logic.build_plan(inspection['items'], result['counts'])
        plan['blocked'].extend(inspection['protected'])
        if self.selected_level_keys:
            names = [c.label for c in self.levels
                     if c.element_id in set(self.selected_level_keys)]
            level_line = u'樓層篩選：{} 個（{}）'.format(
                len(names), u'、'.join(names))
        else:
            level_line = u'樓層篩選：未篩選，全部樓層'
        text = u'\n'.join([
            u'Excel：{}'.format(path),
            u'本次讀取：{}'.format(u'　'.join(sources)),
            level_line,
            u'金屬門窗工程 工項列：r{} ~ r{}'.format(
                inspection['first_row'], inspection['last_row']),
            u'',
            logic.plan_summary(plan, total,
                               len(inspection['items'])),
        ])
        self.previewBox.Text = text
        blocked = bool(plan['blocked'])
        has_updates = bool(plan['updates'])
        self.result = None if blocked or not has_updates else {
            'mode': takeoff_standalone.MODE_UPDATE,
            'path': path, 'plan': plan, 'total': total,
        }
        self.updateButton.IsEnabled = not blocked and has_updates
        self.statusText.Text = (
            u'有阻擋項，禁止更新。' if blocked else
            u'數量無變化，不需要更新。' if not has_updates else
            u'預覽通過，可更新 {} 列。'.format(len(plan['updates'])))

    def update_clicked(self, sender, args):
        if self.result is not None and self.updateButton.IsEnabled:
            self.Close()

    def cancel_clicked(self, sender, args):
        self.result = None
        self.Close()


def _default_name(doc):
    title = u'{}'.format(getattr(doc, 'Title', u'門窗表')).strip()
    for value in u'\\/:*?"<>|':
        title = title.replace(value, u'_')
    return (title or u'門窗表') + u'_門窗表.xlsx'


def run(doc, entry_options):
    window = DoorWindowWindow(doc, entry_options)
    window.ShowDialog()
    result = window.result
    if result is None:
        return
    if result.get('mode') == takeoff_standalone.MODE_STANDALONE:
        path = forms.save_file(
            file_ext='xlsx',
            default_name=_default_name(doc),
            title=u'匯出門窗表 Excel')
        if not path:
            return
        if not path.lower().endswith('.xlsx'):
            path += '.xlsx'
        tables = result['tables']
        try:
            takeoff_standalone.write_standard_workbook(
                path,
                tables['detail_rows'], tables['detail_headers'],
                tables['formula_rows'], tables['formula_headers'],
                tables['audit_rows'], tables['audit_headers'],
                TITLE)
            forms.alert(
                u'匯出完成。\n門窗 {} 樘\nExcel：{}'.format(
                    result['takeoff']['total'], path),
                title=TITLE)
        except Exception as error:
            forms.alert(u'匯出失敗：\n\n{}'.format(error), title=TITLE)
        return
    backup = core._backup_path(result['path'])
    plan = result['plan']
    confirmed = forms.alert(
        u'將更新 小計 分頁「金屬門窗工程」的 {} 列數量，\n'
        u'不建立「門窗表」或額外稽核分頁。\n本次讀取 {} 樘。\n備份：{}'
        u'\n\n確定更新嗎？'.format(
            len(plan['updates']), result['total'], backup),
        title=TITLE, yes=True, no=True)
    if not confirmed:
        return
    try:
        core.update_workbook(result['path'], plan, backup)
        forms.alert(
            u'更新完成，共 {} 列；只修改「小計」。\n'
            u'Excel：{}\n備份：{}'.format(
                len(plan['updates']),
                result['path'], backup),
            title=TITLE)
    except Exception as error:
        forms.alert(u'更新失敗：\n\n{}'.format(error), title=TITLE)
