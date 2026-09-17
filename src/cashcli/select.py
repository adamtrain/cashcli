"""--select: reduce `data` to a few dotted paths so an agent reads only what it asked for."""

from __future__ import annotations

import re

from cashcli.errors import CashError

_TOKEN = re.compile(r"([^.\[\]]+)|\[(-?\d+)\]")


def get_path(data, path: str):
    cur = data
    pos = 0
    for m in _TOKEN.finditer(path):
        if m.start() != pos and path[pos : m.start()] not in (".", ""):
            raise CashError(f"bad --select path {path!r}", "usage")
        pos = m.end()
        key, idx = m.group(1), m.group(2)
        try:
            cur = cur[int(idx)] if idx is not None else cur[key]
        except (KeyError, IndexError, TypeError) as exc:
            raise CashError(
                f"--select: {path!r} not found in the output", "select_not_found"
            ) from exc
    return cur


def select(data, paths: str) -> dict:
    return {p.strip(): get_path(data, p.strip()) for p in paths.split(",") if p.strip()}
