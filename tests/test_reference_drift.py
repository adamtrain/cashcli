"""Guard against the schema reference drifting from what `cash project` actually emits.

Only agents read the reference, and they trust it literally (a documented key that is not in the
output costs a wasted round-trip). Every key `project` emits must be named in the reference's
project bullet, and every key the bullet names must be emitted in some mode.
"""

import re
from importlib.resources import files


def _project_bullet() -> str:
    text = files("cashcli").joinpath("reference.md").read_text(encoding="utf-8")
    start = text.index("- **project**")
    end = text.index("\n- **", start + 1)
    return text[start:end]


def _documented_keys() -> set[str]:
    return set(re.findall(r"[a-z][a-z_]+", _project_bullet()))


def test_every_emitted_project_key_is_documented(budget):
    slim = budget("project", "--months", "1")["data"]
    full = budget("project", "--months", "1", "--verbose", "--ledger", "--weekly-spend", "10")[
        "data"
    ]
    documented = _documented_keys()
    for key in set(slim) | set(full):
        assert key in documented, (
            f"`project` emits {key!r} but reference.md's project bullet never names it"
        )
    for key in ("balance_at_as_of", "interest_accrued_in_window"):
        assert key in full["debts"][0] and key not in slim["debts"][0]


def test_documented_gated_keys_really_are_gated(budget):
    slim = budget("project", "--months", "1")["data"]
    full = budget("project", "--months", "1", "--verbose", "--ledger")["data"]
    assert "flows_used" not in slim and "ledger" not in slim
    assert "flows_used" in full and "ledger" in full
