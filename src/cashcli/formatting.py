"""JSON envelope encoding and a plain-text --pretty renderer (no dependencies)."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal


def _default(o):
    if isinstance(o, Decimal):
        return f"{o:.2f}"
    if isinstance(o, date):
        return o.isoformat()
    if isinstance(o, frozenset | set):
        return sorted(o)
    if hasattr(o, "to_json"):
        return o.to_json()
    raise TypeError(f"not JSON serializable: {type(o).__name__}")


def dumps(obj, *, indent: int | None = 2) -> str:
    return json.dumps(obj, default=_default, indent=indent, ensure_ascii=False)


# ---- pretty ---------------------------------------------------------------------------------


def _cell(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, list):
        return ", ".join(_cell(x) for x in v)
    if isinstance(v, dict):
        items = [(k, x) for k, x in v.items() if not isinstance(x, dict | list)]
        shown = " ".join(f"{k}={_cell(x)}" for k, x in items[:4])
        return shown + (" …" if len(v) > 4 else "")
    return str(v)


def table(rows: list[dict], columns: list[str] | None = None) -> str:
    if not rows:
        return "(none)"
    cols = columns or list({k: None for r in rows for k in r})
    cells = [[_cell(r.get(c)) for c in cols] for r in rows]
    widths = [max(len(c), *(len(row[i]) for row in cells)) for i, c in enumerate(cols)]

    def is_num(s: str) -> bool:
        return s.replace("-", "", 1).replace(".", "", 1).isdigit()

    def fmt(row):
        out = []
        for i, v in enumerate(row):
            out.append(v.rjust(widths[i]) if is_num(v) else v.ljust(widths[i]))
        return "  ".join(out).rstrip()

    lines = [fmt(cols), "  ".join("-" * w for w in widths)]
    lines += [fmt(r) for r in cells]
    return "\n".join(lines)


def pretty(data, title: str | None = None, level: int = 0) -> str:
    """Generic renderer: scalars as key: value, lists of dicts as tables, nested dicts indented."""
    out: list[str] = []
    pad = "  " * level
    if title:
        out.append(f"{pad}{title}")
    if isinstance(data, dict):
        scalars = {k: v for k, v in data.items() if not isinstance(v, dict | list)}
        for k, v in scalars.items():
            out.append(f"{pad}{k}: {_cell(v)}")
        for k, v in data.items():
            if isinstance(v, dict):
                if not v:
                    out.append(f"{pad}{k}: (none)")
                else:
                    out.append("")
                    out.append(pretty(v, k, level + 1))
            elif isinstance(v, list):
                out.append("")
                if v and all(isinstance(x, dict) for x in v):
                    out.append(f"{pad}{k} ({len(v)})")
                    out.append("\n".join(pad + "  " + line for line in table(v).splitlines()))
                else:
                    out.append(f"{pad}{k}: {_cell(v)}")
    elif isinstance(data, list):
        if data and all(isinstance(x, dict) for x in data):
            out.append("\n".join(pad + line for line in table(data).splitlines()))
        else:
            out.append(pad + _cell(data))
    else:
        out.append(pad + _cell(data))
    return "\n".join(out)
