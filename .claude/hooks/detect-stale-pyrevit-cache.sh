#!/bin/bash
# detect-stale-pyrevit-cache.sh
# PostToolUse hook: 寫入 .pushbutton / .panel 之後，檢查 pyRevit 的編譯快取
# 是否已經跟不上磁碟上的按鈕，若是則注入提醒。
#
# 為什麼需要這支：新增／改名／刪除 .pushbutton 資料夾後，pyRevit 仍會用舊的
# compiled DLL，Revit 會跳「無法初始化增益集"<按鈕>"，因為在增益集組合中找不到
# 類別 ...」。那看起來像程式壞了，其實只是 cache 過期。這個訊息在本專案已經
# 重複出現過四次以上，每次都要重新診斷一遍。
#
# 判斷方式不是用猜的：直接把 compiled DLL 當文字讀，看磁碟上的按鈕名稱在不在
# 裡面（domain/pyrevit-button-development.md 記載的做法）。
#
# 注意觸發範圍：只要碰到任何 .pushbutton/.panel 路徑，且**整體** cache 有缺
# 按鈕，就會提醒——不限於剛剛編輯的那一顆。這是刻意的：cache 過期是一件待辦
# 事項，不會因為這次改的是別顆按鈕就消失；若只在「剛好編到缺的那顆」時才提醒，
# 先新增按鈕、後續好幾輪都在改 lib 的情況就會整段安靜下來，等於沒有保護。
# 代價是 cache 未清期間會重複出現，清掉後自然停止。
#
# 沿用同目錄 detect-claudemd-trigger.sh 已經踩過的兩個坑：
#   1. 這台機器沒有 jq，改用 python（不是 python3）
#   2. 不能用 heredoc 餵 python 又在 python 裡讀 sys.stdin——heredoc 本身就是
#      stdin，程式碼讀完就 EOF。先把 payload 存檔，用 argv 傳路徑。

INPUT=$(cat)
TMPFILE=$(mktemp)
printf '%s' "$INPUT" > "$TMPFILE"

python - "$TMPFILE" <<'PYEOF'
import io
import json
import os
import re
import sys

try:
    payload = json.load(io.open(sys.argv[1], encoding='utf-8'))
except Exception:
    sys.exit(0)

blob = json.dumps(payload, ensure_ascii=False)
# Only look when the turn actually touched a button or panel folder.
if not re.search(r'\.(pushbutton|panel)[\\/]', blob):
    sys.exit(0)

project = os.environ.get('CLAUDE_PROJECT_DIR') or os.getcwd()
extension = os.path.join(project, 'pyRevit_Tools', 'MCP_Tools.extension')
if not os.path.isdir(extension):
    sys.exit(0)

buttons = []
for root, dirs, unused in os.walk(extension):
    for name in dirs:
        if name.endswith('.pushbutton'):
            buttons.append(name[:-len('.pushbutton')])
if not buttons:
    sys.exit(0)

appdata = os.environ.get('APPDATA')
if not appdata:
    sys.exit(0)
pyrevit = os.path.join(appdata, 'pyRevit')
if not os.path.isdir(pyrevit):
    sys.exit(0)

dlls = []
for root, unused_dirs, files in os.walk(pyrevit):
    for name in files:
        if name.endswith('MCP_Tools.dll'):
            dlls.append(os.path.join(root, name))
if not dlls:
    # No compiled cache at all: nothing stale, Revit will build it on start.
    sys.exit(0)

missing = set()
for path in dlls:
    try:
        text = io.open(path, 'rb').read().decode('ascii', 'ignore').lower()
    except Exception:
        continue
    for name in buttons:
        if name.lower() not in text:
            missing.add(name)

if not missing:
    sys.exit(0)

print('')
print('[pyRevit cache 過期偵測]')
print('這些按鈕不在已編譯的 DLL 裡，Revit 現在點下去會跳「找不到類別」：')
print('  ' + '、'.join(sorted(missing)))
print('')
print('這不是程式碼的錯，是 cache 沒更新。收尾時務必告訴使用者：')
print('  1. 存檔並完全關閉 Revit')
print('  2. 執行 .\\scripts\\pyrevit-refresh.ps1（Revit 未關會拒絕動手並說明）')
print('  3. 重新啟動 Revit')
print('清 cache 需要 Revit 關閉，不可代為關閉或終止 Revit 行程。')
PYEOF

rm -f "$TMPFILE"
exit 0
