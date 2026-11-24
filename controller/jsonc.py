"""JSON with comments (JSONC): // and /* */ comments plus trailing commas.

The config files are meant to be read and edited by people, so they carry
comments. Python's json module rejects comments, so this module removes them
(string-aware) before parsing.
"""

from __future__ import annotations

import json
from typing import Any


def _strip_comments(text: str) -> str:
    out = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            end = text.find("\n", i)
            i = n if end == -1 else end
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            if end == -1:
                raise ValueError("Unterminated /* comment")
            # Keep line numbers stable for error messages.
            out.append("\n" * text.count("\n", i, end))
            i = end + 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _strip_trailing_commas(text: str) -> str:
    out = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == ",":
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in "}]":
                i += 1  # drop the trailing comma
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def loads(text: str) -> Any:
    if text.startswith("﻿"):
        text = text[1:]
    return json.loads(_strip_trailing_commas(_strip_comments(text)))


def load(path) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        try:
            return loads(fh.read())
        except ValueError as exc:
            raise ValueError(f"{path}: {exc}") from exc
