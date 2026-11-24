---
name: remember
description: Save a note to Allinone's long-term memory. Use when the user says "remember", "تذكّر", "احفظ هذه المعلومة" or asks to keep something for later sessions.
argument-hint: <what to remember>
---

Save the following to long-term memory with the `memory_save` tool from the `allinone` MCP server:

$ARGUMENTS

Rules:
- Rewrite it as one short, self-contained sentence (keep the user's language).
- Add 1–3 lowercase tags (project name, topic) in the `tags` argument.
- If nothing was given after the command, ask what to remember.
- Confirm with the note number the tool returns.
