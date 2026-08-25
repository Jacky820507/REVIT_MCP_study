---
name: markdown-encoding-hygiene
description: "Markdown 知識文件編碼衛生工作流程：區分讀取端錯誤與檔案本體毀損、固定以 UTF-8 維護 SKILL/Domain/Lessons、對工具顯式指定編碼、避免把 cp950 套到知識文件上，以及在出現問號替代字元時安全重建內容。"
metadata:
  version: "1.0"
  updated: "2026-07-24"
  created: "2026-07-24"
  contributors:
    - "Codex"
  related:
    - traditional-chinese-md-translation.md
    - skill-authoring-standard.md
  referenced_by:
    - markdown-encoding-hygiene
  tags: [markdown, encoding, utf8, cp950, mojibake, skill, domain, lessons]
---

# Markdown 編碼衛生

## 目的

這份 domain 用來處理 SKILL、Domain、Lessons、README 與其他知識型 `.md` 文件的編碼問題。目標不是讓單一工具暫時讀得到，而是讓文件內容本身可長期穩定維護、可被人閱讀、也不會被後續工具鏈再次污染。

知識文件的預設真相來源應是 UTF-8。`cp950`、`Default` 或其他系統碼頁只能作為偵錯線索，不能反過來主導文件應該存成什麼。

## 先分辨是哪一種問題

遇到亂碼時，先判斷是以下哪一類：

- 讀取端錯誤：檔案本體是好的，但工具用錯編碼讀。
- 寫入端錯誤：工具把文字用錯誤編碼寫回去。
- 已污染檔案：內容已經被替換成 `?` 或其他不可逆字元。

不要一看到亂碼就立刻改檔。先用至少兩種方式確認：

- 指定 `UTF8` 讀取。
- 檢查 hex 或原始位元組。
- 比對是否真的出現大量 `?` 取代原本應存在的中文字。

如果 `UTF-8` 讀取正常，而 `Default` 讀取異常，問題通常在讀取端。
如果 hex 內已經是 `3F` 大量取代中文位元組，表示檔案內容很可能已被實際污染。

## 知識文件的編碼原則

對知識型 `.md` 檔，一律遵守：

- 以 UTF-8 為 source of truth。
- 不因單一 Windows 指令或驗證腳本而改存成 cp950。
- 讀取時顯式指定編碼，而不是依賴系統預設。
- 寫入時顯式指定 UTF-8。

這個原則適用於：

- `.claude/skills/*/SKILL.md`
- `domain/*.md`
- `Lessons/*.md`
- `README*.md`
- 其他給人讀、也會被 agent 讀的 Markdown 文件

## 工具側修法優先於文件側改碼

如果某個指令顯示亂碼，優先修工具呼叫：

- PowerShell：`Get-Content -Encoding UTF8`
- Python：`open(path, encoding="utf-8")`
- 其他腳本：找出未指定編碼的讀寫點

只有在工具無法調整，且文件又必須被那個工具讀取時，才進一步評估折衷方案。即便如此，也應先想：

- 能否改腳本
- 能否加 wrapper
- 能否只讓機器可讀部分維持 ASCII

不要先動文件本體。

## SKILL 特例

部分驗證腳本或舊工具可能用系統預設編碼讀 `SKILL.md`。如果這些工具短期內無法修正，而你又需要通過它們，優先順序如下：

1. 修讀取腳本，讓它顯式使用 UTF-8。
2. 若無法立刻修腳本，暫時讓 `SKILL.md` 保持 ASCII 安全內容，同時把中文知識移到 `domain` 或 `Lessons`。
3. 不要為了通過單一驗證，把整個知識文件系統改存成 cp950。

## 內容已污染時的處理

若檔案內容已被 `?` 大量取代，通常代表原始中文已不可逆遺失。這時不要再做編碼轉換，應直接：

1. 以可靠來源重建內容。
2. 刪除受污染檔案。
3. 用正確 UTF-8 內容重建。
4. 再驗證新檔是否可被 UTF-8 讀取。

如果只是部分段落受損，優先從：

- 同回合先前 patch
- 聊天紀錄中的已輸出內容
- 其他引用文件
- git 歷史或備份

恢復文字，而不是猜測亂碼對應。

## 驗證清單

修復完成後至少檢查：

- UTF-8 讀取是否正常
- `Default` 讀取若失敗，是否屬預期且已知
- 是否還有大量 `?` 替代字元
- frontmatter、檔名、路徑、code block 是否保持原樣
- 相關 skill 或 domain 的參照路徑是否仍可用

## 反模式

以下做法要避免：

- 因為 `Get-Content -Encoding Default` 顯示亂碼，就把文件改成 cp950
- 為了通過單一驗證，把所有 Markdown 都降成系統碼頁
- 在未確認位元組內容前，反覆做多次編碼轉換
- 用「看起來像正常」取代實際檢查 hex 或顯式編碼讀取
