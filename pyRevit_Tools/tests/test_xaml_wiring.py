# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Static checks for every WPF button in the tab.

A XAML window fails late and badly. ``Click="foo"`` with no ``def foo`` raises
only when the window is opened, and ``self.roomList`` with no matching
``x:Name`` raises only once that line is reached — both after the user has
already clicked the ribbon, and neither is caught by importing the module or by
the IronPython compile gate.

These turn both into failing tests, for every XAML button rather than the one
that happened to prompt them.
"""

import io
import os
import re
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
TAB = os.path.join(ROOT, 'MCP_Tools.extension', 'MCP_Macros.tab')

HANDLER = re.compile(
    r'\b(?:Click|SelectionChanged|TextChanged|Checked|Unchecked|Loaded'
    r'|MouseDoubleClick|LostFocus|KeyDown)\s*=\s*"([A-Za-z_]\w*)"')
X_NAME = re.compile(r'x:Name\s*=\s*"([A-Za-z_]\w*)"')
SELF_ATTR = re.compile(r'\bself\.([A-Za-z_]\w*)')
SELF_ASSIGN = re.compile(r'\bself\.([A-Za-z_]\w*)\s*=')
DEF_NAME = re.compile(r'\bdef\s+([A-Za-z_]\w*)\s*\(')


def read(path):
    with io.open(path, 'r', encoding='utf-8') as stream:
        return stream.read()


def xaml_buttons():
    """``[(xaml_path, script_path)]`` for every WPF button in the tab."""
    found = []
    for root, unused_dirs, files in os.walk(TAB):
        for name in sorted(files):
            if not name.endswith('.xaml'):
                continue
            found.append((os.path.join(root, name),
                          os.path.join(root, 'script.py')))
    return sorted(found)


def all_buttons():
    """Every ``.pushbutton`` folder in the tab, XAML-backed or not."""
    found = []
    for panel in sorted(os.listdir(TAB)):
        if not panel.endswith('.panel'):
            continue
        panel_dir = os.path.join(TAB, panel)
        for name in sorted(os.listdir(panel_dir)):
            if name.endswith('.pushbutton'):
                found.append(os.path.join(panel_dir, name))
    return found


class BundleTests(unittest.TestCase):
    """A button with no ``bundle.yaml`` still loads — under the wrong name.

    pyRevit falls back to the folder name and shows no tooltip, so the failure
    is a silently mislabelled ribbon item rather than an error anyone sees.
    """

    def test_every_button_has_a_bundle(self):
        missing = [os.path.basename(path) for path in all_buttons()
                   if not os.path.isfile(os.path.join(path, 'bundle.yaml'))]
        self.assertEqual([], missing)

    def test_every_bundle_declares_a_title_and_tooltip(self):
        problems = []
        for path in all_buttons():
            bundle = os.path.join(path, 'bundle.yaml')
            if not os.path.isfile(bundle):
                continue
            text = read(bundle)
            for field in ('title:', 'tooltip:'):
                if field not in text:
                    problems.append(u'{} 缺 {}'.format(
                        os.path.basename(path), field))
        self.assertEqual([], problems)

    def test_no_button_carries_untested_availability_metadata(self):
        """L-061/L-063: unverified context makes the whole ribbon fail to load."""
        problems = []
        for path in all_buttons():
            bundle = os.path.join(path, 'bundle.yaml')
            if not os.path.isfile(bundle):
                continue
            text = read(bundle)
            for field in ('context:', 'availability:'):
                if field in text:
                    problems.append(u'{} 帶了 {}'.format(
                        os.path.basename(path), field))
        self.assertEqual([], problems)


class XamlWiringTests(unittest.TestCase):
    def test_there_is_at_least_one_xaml_button(self):
        """Guards the guard: a broken walk would make every test below pass."""
        self.assertTrue(xaml_buttons())

    def test_every_xaml_has_a_sibling_script(self):
        missing = [xaml for xaml, script in xaml_buttons()
                   if not os.path.isfile(script)]
        self.assertEqual([], missing)

    def test_every_event_handler_exists_in_the_script(self):
        problems = []
        for xaml, script in xaml_buttons():
            if not os.path.isfile(script):
                continue
            source = read(script)
            defined = set(DEF_NAME.findall(source))
            for handler in sorted(set(HANDLER.findall(read(xaml)))):
                if handler not in defined:
                    problems.append(u'{} -> def {}'.format(
                        os.path.basename(xaml), handler))
        self.assertEqual(
            [], problems,
            u'XAML 綁的事件處理器在 script.py 裡不存在，開視窗時才會炸：{}'
            .format(problems))

    def test_every_named_control_used_by_the_script_exists_in_the_xaml(self):
        problems = []
        for xaml, script in xaml_buttons():
            if not os.path.isfile(script):
                continue
            source = read(script)
            names = set(X_NAME.findall(read(xaml)))
            assigned = set(SELF_ASSIGN.findall(source))
            defined = set(DEF_NAME.findall(source))
            for used in sorted(set(SELF_ATTR.findall(source))):
                # Anything the script assigns to itself, or defines as a
                # method, is its own business; only the leftovers are meant to
                # be controls resolved out of the XAML.
                if used in assigned or used in defined or used in names:
                    continue
                if used.startswith('_') or used[0].isupper():
                    continue
                problems.append(u'{} -> self.{}'.format(
                    os.path.basename(xaml), used))
        self.assertEqual(
            [], problems,
            u'script.py 用到的控制項在 XAML 沒有對應的 x:Name：{}'.format(
                problems))


if __name__ == '__main__':
    unittest.main()


class SharedShellTests(unittest.TestCase):
    """共用視窗外殼 lib/mcp_window.xaml 與 lib/mcp_window.py 的對帳。

    上面的 walk 只掃 MCP_Macros.tab，蓋不到 lib/。而共用外殼是現在全 repo
    最關鍵的一個 XAML：名稱一漂移，所有用它的按鈕會同時壞掉，而且是在 Revit
    裡才炸。所以單獨對帳。
    """

    LIB = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'MCP_Tools.extension', 'lib')

    def _xaml(self):
        path = os.path.join(self.LIB, 'mcp_window.xaml')
        with io.open(path, encoding='utf-8') as handle:
            return handle.read()

    def _script(self):
        path = os.path.join(self.LIB, 'mcp_window.py')
        with io.open(path, encoding='utf-8') as handle:
            return handle.read()

    def test_the_shared_shell_exists(self):
        """守門員的守門員：路徑打錯會讓下面每一條都空過。"""
        self.assertTrue(os.path.isfile(
            os.path.join(self.LIB, 'mcp_window.xaml')))
        self.assertTrue(os.path.isfile(
            os.path.join(self.LIB, 'mcp_window.py')))

    def test_every_control_the_shell_touches_is_declared(self):
        names = set(re.findall(r'x:Name="(\w+)"', self._xaml()))
        used = set(re.findall(r'self\.([a-z]\w*(?:Text|Button|Border|Host|'
                              r'Grid|Tab|tabs))\b', self._script()))
        missing = sorted(used - names)
        self.assertEqual([], missing,
                         u'mcp_window.py 用到 XAML 沒有宣告的控制項：{}'
                         .format(missing))

    def test_every_style_key_the_shell_asks_for_is_defined(self):
        """_res() 查不到資源時是**靜默**回 None，控制項就只是沒有樣式——
        這種壞法在畫面上看起來像「設計沒做好」，不像 bug。"""
        keys = set(re.findall(r'x:Key="(\w+)"', self._xaml()))
        asked = set(re.findall(r"_res\('(\w+)'\)", self._script()))
        asked |= set(re.findall(r"_styled\([^,]+, '(\w+)'\)", self._script()))
        asked |= set(re.findall(r"_block\([^,]+, '(\w+)'\)", self._script()))
        missing = sorted(asked - keys)
        self.assertEqual([], missing,
                         u'程式向 XAML 要了不存在的資源：{}'.format(missing))

    def test_the_tone_table_only_names_real_brushes(self):
        keys = set(re.findall(r'x:Key="(\w+)"', self._xaml()))
        script_text = self._script()
        block = re.search(r'TONE_BRUSHES = \{(.*?)\}', script_text, re.S)
        self.assertIsNotNone(block, u'找不到 TONE_BRUSHES')
        referenced = set(re.findall(r"'(\w+)'", block.group(1)))
        # 語意鍵（info/warning/...）不是資源名，只留大寫開頭的畫刷名。
        brushes = set(name for name in referenced if name[:1].isupper())
        self.assertEqual([], sorted(brushes - keys))

    def test_the_shell_declares_the_action_bar(self):
        """取消鈕不見了會讓視窗只能用右上角的 X 關掉。"""
        names = set(re.findall(r'x:Name="(\w+)"', self._xaml()))
        for required in ('runButton', 'cancelButton', 'secondaryButton',
                         'fieldHost', 'statusText', 'resultGrid'):
            self.assertIn(required, names)


CONVERTED_BUTTONS = (
    'Area.panel/AreaFormula', 'Area.panel/AreaOwnership',
    'Area.panel/AreaParameters', 'Area.panel/AutoPlaceAreas',
    'Area.panel/CadToBoundary', 'Area.panel/CopyAreasToScheme',
    'Area.panel/DedupAreas', 'Area.panel/ExportAreasExcel',
    'Area.panel/PurgeAreas', 'Area.panel/RegenAreaBoundaries',
    'Area.panel/RenumberAreas', 'Check.panel/DuplicateMarks',
    'Check.panel/EgressDistance', 'Check.panel/GroupHeightCheck',
    'Numbering.panel/TemplateTransfer', 'Visual.panel/MergeDimensions',
    'Visual.panel/SwapViewMarkTypes', 'Visual.panel/ViewScale',
)


class ConvertedButtonTests(unittest.TestCase):
    """這 18 顆已經改用共用視窗，不該再退回對話框連珠。

    退回去不會壞掉——它會照常執行，只是使用者又得一題一題答，而且改中間任何
    一個答案都要從頭來。那種退步沒有任何訊號會提醒人，所以用測試釘住。
    """

    def _script(self, name):
        path = os.path.join(TAB, name.replace('/', os.sep) + '.pushbutton',
                            'script.py')
        with io.open(path, encoding='utf-8') as handle:
            return path, handle.read()

    def test_every_converted_button_exists(self):
        """守門員的守門員：路徑打錯會讓下面兩條都空過。"""
        for name in CONVERTED_BUTTONS:
            path, unused = self._script(name)
            self.assertTrue(os.path.isfile(path), path)

    def test_no_converted_button_still_chains_dialogs(self):
        for name in CONVERTED_BUTTONS:
            unused, text = self._script(name)
            body = u'\n'.join(line for line in text.splitlines()
                              if not line.strip().startswith(u'#'))
            for banned in (u'SelectFromList.show', u'forms.ask_for_string'):
                self.assertNotIn(
                    banned, body,
                    u'{} 又用回 {}；請改用 mcp_window 的欄位規格。'
                    .format(name, banned))

    def test_every_converted_button_uses_the_shared_window(self):
        for name in CONVERTED_BUTTONS:
            unused, text = self._script(name)
            self.assertIn(u'import mcp_window as ui', text, name)
            self.assertIn(u'import mcp_window_logic as uilogic', text, name)

    def test_every_converted_button_declares_a_badge(self):
        """徽章說的是「這顆按鈕會不會動到模型」，是規格的必填項。"""
        for name in CONVERTED_BUTTONS:
            unused, text = self._script(name)
            self.assertIn(u'badge=uilogic.BADGE_', text, name)
