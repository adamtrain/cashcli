import json
from datetime import date

from cashcli.recurrence import occurrences, shift_weekend


def test_shift_weekend():
    sat, sun, mon = date(2026, 11, 14), date(2026, 11, 15), date(2026, 11, 16)
    assert shift_weekend(sat, "next") == mon and shift_weekend(sun, "next") == mon
    assert shift_weekend(sat, "previous") == date(2026, 11, 13)
    assert shift_weekend(sun, "previous") == date(2026, 11, 13)
    assert shift_weekend(mon, "next") == mon and shift_weekend(sat, "none") == sat


def test_occurrences_with_weekend_rule():
    # the 15th: Nov 15 2026 is a Sunday, Aug 15 2026 is a Saturday
    got = occurrences(
        "FREQ=MONTHLY;BYMONTHDAY=15",
        date(2026, 8, 15),
        None,
        date(2026, 8, 1),
        date(2026, 12, 31),
        "next",
    )
    assert got == [
        date(2026, 8, 17),
        date(2026, 9, 15),
        date(2026, 10, 15),
        date(2026, 11, 16),
        date(2026, 12, 15),
    ]
    got = occurrences(
        "FREQ=MONTHLY;BYMONTHDAY=15",
        date(2026, 8, 15),
        None,
        date(2026, 8, 1),
        date(2026, 12, 31),
        "previous",
    )
    assert got[0] == date(2026, 8, 14) and got[3] == date(2026, 11, 13)
    # shifted date crossing the window edge: window ends Nov 15 (Sun), occurrence moves to Nov 16 -> excluded
    got = occurrences(
        "FREQ=MONTHLY;BYMONTHDAY=15",
        date(2026, 11, 15),
        None,
        date(2026, 11, 1),
        date(2026, 11, 15),
        "next",
    )
    assert got == []
    # ... and pulled into the window from just outside it
    got = occurrences(
        "FREQ=MONTHLY;BYMONTHDAY=15",
        date(2026, 11, 15),
        None,
        date(2026, 11, 16),
        date(2026, 11, 30),
        "next",
    )
    assert got == [date(2026, 11, 16)]


def test_ach_flag_shifts_payment_in_projection(run):
    run(
        "flow",
        "add",
        "--name",
        "Ins",
        "--kind",
        "expense",
        "--amount",
        "100",
        "--rrule",
        "FREQ=MONTHLY;BYMONTHDAY=15",
        "--dtstart",
        "2026-10-15",
        "--ach",
    )
    assert run("flow", "show", "Ins")["data"]["weekend"] == "next"
    d = run(
        "project", "--as-of", "2026-11-01", "--months", "1", "--ledger", "--granularity", "daily"
    )["data"]
    assert [e["date"] for e in d["ledger"]] == ["2026-11-16"]
    run("flow", "update", "Ins", "--weekend", "previous")
    d = run("project", "--as-of", "2026-11-01", "--months", "1", "--ledger")["data"]
    assert [e["date"] for e in d["ledger"]] == ["2026-11-13"]


def test_cleanup_removes_stale_flows(run):
    run(
        "flow",
        "add",
        "--name",
        "Old one-off",
        "--kind",
        "expense",
        "--amount",
        "5",
        "--dtstart",
        "2026-08-20",
        "--no-cleanup",
    )
    run(
        "flow",
        "add",
        "--name",
        "Ended",
        "--kind",
        "income",
        "--amount",
        "5",
        "--rrule",
        "FREQ=MONTHLY",
        "--dtstart",
        "2026-01-01",
        "--until",
        "2026-08-01",
        "--tag",
        "gone",
        "--no-cleanup",
    )
    run(
        "flow",
        "add",
        "--name",
        "Counted",
        "--kind",
        "income",
        "--amount",
        "5",
        "--rrule",
        "FREQ=MONTHLY;COUNT=3",
        "--dtstart",
        "2026-05-01",
        "--no-cleanup",
    )
    run(
        "flow",
        "add",
        "--name",
        "This month",
        "--kind",
        "expense",
        "--amount",
        "5",
        "--dtstart",
        "2026-09-02",
        "--no-cleanup",
    )
    run(
        "flow",
        "add",
        "--name",
        "Future",
        "--kind",
        "expense",
        "--amount",
        "5",
        "--dtstart",
        "2026-10-02",
        "--no-cleanup",
    )
    assert run("flow", "list", "--no-cleanup")["data"]["count"] == 5
    env = run("cleanup")
    names = sorted(f["name"] for f in run("flow", "list")["data"]["flows"])
    assert names == ["Future", "This month"]
    assert len(env["data"]["actions"]) == 3
    assert run("tag", "list")["data"]["tags"] == []  # 'gone' was pruned with its flow
    # an automatic run reports its actions in the envelope, and nothing on a clean db
    assert "cleanup" not in run("flow", "list")


def test_cleanup_rolls_debt_forward_and_removes_paid_off(run):
    run(
        "flow",
        "add",
        "--name",
        "Loan",
        "--kind",
        "expense",
        "--amount",
        "386.66",
        "--rrule",
        "FREQ=MONTHLY;BYMONTHDAY=1",
        "--dtstart",
        "2026-07-01",
        "--no-cleanup",
    )
    run(
        "debt",
        "set",
        "Loan",
        "--balance",
        "20000",
        "--balance-as-of",
        "2026-06-01",
        "--rate",
        "6%",
        "--compounding",
        "monthly",
        "--no-cleanup",
    )
    run(
        "debt",
        "events",
        "add",
        "Loan",
        "--type",
        "extra_payment",
        "--date",
        "2026-07-15",
        "--amount",
        "1000",
        "--no-cleanup",
    )
    run(
        "debt",
        "events",
        "add",
        "Loan",
        "--type",
        "rate_change",
        "--date",
        "2026-12-01",
        "--rate",
        "5%",
        "--no-cleanup",
    )
    env = run("flow", "show", "Loan")
    d = env["data"]["debt"]
    assert d["balance_as_of"] == "2026-08-31"
    # 20000 -> Jul 1: +100 int -386.66 = 19713.34; Jul 15: -1000 = 18713.34; Aug 1: +93.57 -386.66 = 18420.25
    assert d["balance"] == "18420.25"
    assert [e["type"] for e in d["events"]] == ["rate_change"]
    assert any("rolled debt" in a for a in env["cleanup"])
    # a debt paid off last month disappears
    run(
        "flow",
        "add",
        "--name",
        "Tiny",
        "--kind",
        "expense",
        "--amount",
        "500",
        "--rrule",
        "FREQ=MONTHLY;BYMONTHDAY=1",
        "--dtstart",
        "2026-07-01",
        "--no-cleanup",
    )
    run(
        "debt",
        "set",
        "Tiny",
        "--balance",
        "600",
        "--balance-as-of",
        "2026-06-15",
        "--rate",
        "0%",
        "--compounding",
        "monthly",
        "--no-cleanup",
    )
    env = run("flow", "list")
    assert [f["name"] for f in env["data"]["flows"]] == ["Loan"]
    assert any("removed debt 'Tiny'" in a for a in env["cleanup"])


def test_today_override_drives_default_as_of(run, monkeypatch):
    monkeypatch.setenv("CASHCLI_TODAY", "2027-03-03")
    assert run("project")["data"]["as_of"] == "2027-03-03"


def test_export_import_keeps_weekend(run, tmp_path):
    run(
        "flow",
        "add",
        "--name",
        "A",
        "--kind",
        "expense",
        "--amount",
        "1",
        "--rrule",
        "FREQ=MONTHLY",
        "--dtstart",
        "2026-10-01",
        "--ach",
    )
    exp = run("export")["data"]
    f = tmp_path / "e.json"
    f.write_text(json.dumps(exp))
    run("import", str(f), "--replace")
    assert run("flow", "show", "A")["data"]["weekend"] == "next"


def test_posting_day_survives_roll_forward(run):
    run(
        "flow",
        "add",
        "--name",
        "Card",
        "--kind",
        "expense",
        "--amount",
        "500",
        "--rrule",
        "FREQ=MONTHLY;BYMONTHDAY=15",
        "--dtstart",
        "2026-07-15",
        "--no-cleanup",
    )
    run(
        "debt",
        "set",
        "Card",
        "--balance",
        "10000",
        "--balance-as-of",
        "2026-06-16",
        "--rate",
        "12%",
        "--compounding",
        "monthly",
        "--posting-day",
        "15",
        "--no-cleanup",
    )
    d = run("flow", "show", "Card")["data"]["debt"]
    assert d["balance_as_of"] == "2026-08-31" and d["posting_day"] == 15
    # Jul 15: +100 -500 = 9600; Aug 15: +96 -500 = 9196
    assert d["balance"] == "9196.00"
    sched = run("debt", "schedule", "Card", "--as-of", "2026-09-01")["data"]
    assert sched["rows"][0]["date"] == "2026-09-15" and sched["rows"][0]["interest"] == "91.96"
