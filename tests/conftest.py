import json
from datetime import date

import pytest

from cashcli.cli import main


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "budget.sqlite"


@pytest.fixture
def run(db_path, capsys):
    """Run the CLI in-process against the temp db and return the parsed JSON envelope."""

    def _run(*argv, expect_ok=True):
        code = main([*argv, "--db", str(db_path)])
        out = capsys.readouterr().out
        env = json.loads(out)
        if expect_ok:
            assert env["ok"], env
            assert code == 0
        return env

    _run("init")
    return _run


@pytest.fixture
def budget(run):
    """Salary / Rent / Car loan / Car insurance fixture from the plan."""
    run(
        "flow",
        "add",
        "--name",
        "Salary",
        "--kind",
        "income",
        "--amount",
        "2500",
        "--rrule",
        "FREQ=WEEKLY;INTERVAL=2",
        "--dtstart",
        "2026-09-18",
        "--tag",
        "job",
    )
    run(
        "flow",
        "add",
        "--name",
        "Rent",
        "--kind",
        "expense",
        "--amount",
        "3000",
        "--rrule",
        "FREQ=MONTHLY;BYMONTHDAY=1",
        "--dtstart",
        "2026-10-01",
        "--tag",
        "housing",
    )
    run(
        "flow",
        "add",
        "--name",
        "Car loan",
        "--kind",
        "expense",
        "--amount",
        "386.66",
        "--rrule",
        "FREQ=MONTHLY;BYMONTHDAY=1",
        "--dtstart",
        "2026-11-01",
        "--tag",
        "car",
        "--tag",
        "loan",
    )
    run(
        "debt",
        "set",
        "Car loan",
        "--balance",
        "20000",
        "--balance-as-of",
        "2026-10-01",
        "--rate",
        "6%",
        "--compounding",
        "monthly",
    )
    run(
        "flow",
        "add",
        "--name",
        "Car insurance",
        "--kind",
        "expense",
        "--amount",
        "120",
        "--rrule",
        "FREQ=MONTHLY;BYMONTHDAY=15",
        "--dtstart",
        "2026-10-15",
        "--tag",
        "car",
    )
    return run


AS_OF = date(2026, 9, 16)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setenv("CASHCLI_TODAY", "2026-09-16")
