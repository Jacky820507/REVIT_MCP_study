#!/usr/bin/env bash
# session-start-log-digest.sh
# SessionStart hook: automatically reads the latest log/YYYY-MM.md (last 80
# lines), the same content CLAUDE.md's "Session Start Protocol" already tells
# every session to read manually. Manual instructions get forgotten (the same
# reasoning behind the ~/.claude UserPromptSubmit skill-reminder hook); this
# makes it happen unconditionally.
#
# Deliberately does NOT use jq. Confirmed 2026-08-11: this repo's other hook
# (detect-claudemd-trigger.sh) depends on jq, and jq is not on PATH in the
# Bash environment these hooks actually run in — it fails with
# "jq: command not found" and silently falls through to exit 0, so that hook
# has never actually fired. `python` IS confirmed present, so JSON is built
# with `json.dumps` instead of hand-rolled shell escaping.

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
LOG_DIR="$PROJECT_DIR/log"

[ -d "$LOG_DIR" ] || exit 0

LATEST=$(ls "$LOG_DIR"/*.md 2>/dev/null | grep -v '/README\.md$' | sort | tail -1)
[ -z "$LATEST" ] && exit 0

python - "$LATEST" <<'PYEOF'
import json
import os
import sys

# Windows python defaults stdout to the console codepage (cp950 here), which
# cannot encode the Traditional Chinese log content and raises
# UnicodeEncodeError. Force UTF-8 regardless of console codepage.
sys.stdout.reconfigure(encoding='utf-8')

path = sys.argv[1]
try:
    with open(path, encoding='utf-8') as f:
        lines = f.readlines()
except OSError:
    sys.exit(0)

tail = ''.join(lines[-80:]).strip()
if not tail:
    sys.exit(0)

name = os.path.basename(path)
context = (
    "[Session Start Protocol] 最新工作日誌 "
    + name
    + "（最後 80 行）：\n\n"
    + tail
)
out = {
    "hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": context,
    }
}
print(json.dumps(out, ensure_ascii=False))
PYEOF

exit 0
