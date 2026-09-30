---
name: markdown-encoding-hygiene
description: "當修復或預防亂碼、編碼損毀、UTF-8 與 cp950 錯誤，或處理 SKILL、Domain、Lessons、README 或其他 Markdown 知識檔案的讀寫問題時使用。"
---

# Markdown Encoding Hygiene

Use this skill when Markdown knowledge files show garbled text, `?` replacement characters, decoding failures, or mixed UTF-8 and cp950 behavior.

## Workflow

1. Read `domain/markdown-encoding-hygiene.md`.
2. Determine whether the problem is a wrong reader or truly corrupted file bytes.
3. For `.md` knowledge files, preserve UTF-8 as the source-of-truth encoding.
4. Fix read or validation commands before converting document encoding.
5. Rebuild file content only when bytes were already destroyed.

## Guardrails

- Do not convert Markdown knowledge files to cp950 just to satisfy one Windows reader.
- Keep `name`, paths, code blocks, commands, and machine-readable identifiers unchanged.
- Treat `?` replacement characters as possible irreversible corruption until proven otherwise.
- Use explicit encodings in tools and scripts that touch `.md` files.

## Reference

- `domain/markdown-encoding-hygiene.md`
- `Lessons/markdown-encoding-hygiene-lessons.md`
