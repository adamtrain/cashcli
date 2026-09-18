"""--select: reduce `data` to a few dotted paths so an agent reads only what it asked for.

Paths are relative to the envelope's `data` (a leading `data.` is forgiven). When a path does not
resolve, the error names the deepest level that did resolve and lists what is actually there, so
the caller can fix the path in one step instead of dumping the whole output.
"""

from __future__ import annotations

import re

from cashcli.errors import CashError

_TOKEN = re.compile(r"([^.\[\]]+)|\[(-?\d+)\]")

# Keys that exist only when a flag is given; the error says so instead of "not found".
GATED_KEYS = {
    "flows_used": "--verbose",
    "ledger": "--ledger",
}


def _describe(value) -> str:
    if isinstance(value, dict):
        return f"an object with keys: {', '.join(sorted(value))}" if value else "an empty object"
    if isinstance(value, list):
        return f"a list of {len(value)} items (index it: [0], [-1], ...)"
    return f"a {type(value).__name__} with no fields"


def _tokens(path: str) -> list[tuple[str | None, str | None]]:
    out: list[tuple[str | None, str | None]] = []
    pos = 0
    for m in _TOKEN.finditer(path):
        if m.start() != pos and path[pos : m.start()] not in (".", ""):
            raise CashError(f"bad --select path {path!r}", "usage")
        pos = m.end()
        out.append((m.group(1), m.group(2)))
    return out


def get_path(data, path: str):
    tokens = _tokens(path)
    if (
        len(tokens) > 1
        and tokens[0] == ("data", None)
        and isinstance(data, dict)
        and "data" not in data
    ):
        tokens = tokens[1:]  # forgive `data.x`: paths are already relative to data
    cur = data
    resolved = ""
    for key, idx in tokens:
        try:
            cur = cur[int(idx)] if idx is not None else cur[key]
        except KeyError, IndexError, TypeError:
            where = f"{resolved!r}" if resolved else "data"
            want = f"index [{idx}]" if idx is not None else f"key {key!r}"
            msg = f"--select: {path!r} not found: {where} has no {want}; it is {_describe(cur)}"
            if key in GATED_KEYS and isinstance(cur, dict):
                msg += f". {key!r} is only in the output when {GATED_KEYS[key]} is given"
            raise CashError(msg, "select_not_found") from None
        resolved += f"[{idx}]" if idx is not None else (f".{key}" if resolved else key)
    return cur


def select(data, paths: str) -> dict:
    return {p.strip(): get_path(data, p.strip()) for p in paths.split(",") if p.strip()}
