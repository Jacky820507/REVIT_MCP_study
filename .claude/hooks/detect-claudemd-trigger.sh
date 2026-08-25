#!/bin/bash
# detect-claudemd-trigger.sh
# PostToolUse hook: 偵測三種觸發事件，注入雙向驗證指令
#
# 觸發條件：
#   1. git merge / pull / rebase（合併外部 PR）
#   2. 寫入 .claude/skills/ 路徑（Domain 升級 Skill）
#   3. 寫入 MCP-Server/src/tools/ 或 MCP/Core/CommandExecutor（Tools 檢討）
#
# 2026-08-11 改寫：原本依賴 jq，但這台機器實際執行 hook 的 Bash 環境沒有
# jq——`jq: command not found`，導致每次解析都失敗、$TRIGGER 永遠是空字串，
# 這支 hook 自從寫出來就從未真正觸發過一次（靜默失效，沒有任何錯誤訊息）。
# 改用 python 處理 JSON（跟同目錄 session-start-log-digest.sh 同一套做法），
# 這台機器確認有 python（不是 python3）。
#
# 陷阱（改寫時實際踩到過一次）：不能用 `python - <<'PYEOF' ... PYEOF` 又要
# python 內部讀 sys.stdin 拿 hook payload——heredoc 本身就是餵給
# `python -` 當「程式原始碼」用的 stdin，程式碼讀完 stdin 就已經 EOF，
# 腳本內部再讀 sys.stdin 只會拿到空字串，導致每次都靜默判定「非觸發」而
# exit 0，跟 jq 失效的症狀一模一樣但成因不同。修法：先用 `INPUT=$(cat)`
# 把管線進來的 payload 存到暫存檔，改用檔案路徑當 argv 傳給 python，不要
# 讓 python 又讀一次 stdin。

INPUT=$(cat)
TMPFILE=$(mktemp)
printf '%s' "$INPUT" > "$TMPFILE"

python - "$TMPFILE" <<'PYEOF'
import json
import re
import sys

# Windows python 預設 stdout 用主控台 code page（這台是 cp950），印繁體中文
# 會直接 UnicodeEncodeError。強制用 UTF-8，不管主控台編碼是什麼。
sys.stdout.reconfigure(encoding='utf-8')

try:
    with open(sys.argv[1], encoding='utf-8') as f:
        payload = json.load(f)
except (OSError, json.JSONDecodeError, ValueError):
    sys.exit(0)

tool_name = payload.get('tool_name', '') or ''
tool_input = payload.get('tool_input', {}) or {}

trigger = None
label = None

# --- 偵測 Bash 指令：合併外部 PR ---
if tool_name == 'Bash':
    command = tool_input.get('command', '') or ''
    if re.search(r'git\s+(merge|pull|rebase)', command):
        trigger = 'MERGE_EXTERNAL'
        label = '合併外部 PR'

# --- 偵測檔案寫入/編輯 ---
if tool_name in ('Write', 'Edit'):
    file_path = (tool_input.get('file_path', '') or '').replace('\\', '/')

    # Domain 升級 Skill
    if re.search(r'\.claude/skills/.*SKILL\.md', file_path):
        trigger = 'SKILL_CHANGE'
        label = 'Domain 升級 Skill / Skill 異動'

    # Tools 檢討
    if re.search(r'(MCP-Server/src/tools/|MCP/Core/CommandExecutor)', file_path):
        trigger = 'TOOLS_CHANGE'
        label = 'Tools 定義異動'

# --- 無觸發 -> 正常通過 ---
if trigger is None:
    sys.exit(0)

# --- 有觸發 -> 注入雙向驗證指令 ---
context = (
    "⚠️ CLAUDE.md 同步檢查觸發（事件：" + label + "）\n\n"
    "你剛完成的操作可能影響 CLAUDE.md 的正確性。\n"
    "請立即執行 CLAUDE.md 雙向驗證流程（/claude-md-sync）：\n\n"
    "【正向驗證】作業結果 -> CLAUDE.md\n"
    "  1. Skills 表格數量和名稱是否正確\n"
    "  2. Domain 觸發關鍵字表是否需要更新或刪除\n"
    "  3. 工具數量（58->?）是否變化\n"
    "  4. 檔案路徑引用是否仍然存在\n"
    "  5. 架構描述是否仍然正確\n\n"
    "【反向驗證】修正後的 CLAUDE.md -> 回頭檢證作業結果\n"
    "  6. 修正後的 CLAUDE.md 是否與作業結果矛盾\n"
    "  7. Deployment Rules 是否阻止了剛才的操作\n"
    "  8. Build/Deploy 流程是否因修正而需要更新\n\n"
    "兩邊一致後才能結束此驗證。如有衝突，需反覆修正直到一致。"
)

out = {
    "hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": context,
    }
}
print(json.dumps(out, ensure_ascii=False))
PYEOF

rm -f "$TMPFILE"
exit 0
