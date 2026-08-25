---
name: markdown-encoding-hygiene
description: "Use when fixing or preventing mojibake, encoding corruption, UTF-8 versus cp950 mistakes, or Markdown knowledge-file read/write issues in SKILL, Domain, Lessons, README, or other `.md` documentation."
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
