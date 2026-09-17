"""--settle, --stop/--stop-tag, the '?' date placeholder (+ --on) and `cash earliest`."""

import json

BASE = ["project", "--starting-balance", "3000", "--as-of", "2026-09-16", "--months", "6"]
BASELINE_END = "14846.70"  # see test_project_six_months


def test_settle_pays_the_shortfall_from_cash(budget):
    d = budget(*BASE, "--settle", "Car loan:15000@2026-11-15", "--ledger", "--verbose")["data"]
    # owed on Nov 15 = 19713.34 (after the Nov 1 payment; interest posts on the 1st)
    row = next(e for e in d["ledger"] if e["kind"] == "settle")
    assert row["date"] == "2026-11-15" and row["name"] == "Car loan"
    assert row["amount"] == "4713.34" and row["delta"] == "-4713.34"
    assert row["debt"]["balance_after"] == "0.00"
    # 14846.70 - 4713.34 + 4 saved payments of 386.66
    assert d["ending_balance"] == "11680.00"
    assert d["debts"][0]["paid_off_on"] == "2026-11-15"
    assert d["total_debt_at_until"] == "0.00"
    assert not any(e["name"] == "Car loan" and e["date"] > "2026-11-15" for e in d["ledger"])


def test_settle_surplus_is_income(budget):
    d = budget(*BASE, "--settle", "Car loan:25000@2026-11-15", "--ledger")["data"]
    row = next(e for e in d["ledger"] if e["kind"] == "settle")
    assert row["delta"] == "5286.66"
    assert d["ending_balance"] == "21680.00"
    assert d["totals"]["income"] == "37786.66"
    assert d["totals"]["principal_paid"] == "286.66"  # only the Nov 1 scheduled payment


def test_settle_is_scenario_only(budget):
    env = budget(
        "debt",
        "events",
        "add",
        "Car loan",
        "--type",
        "settle",
        "--date",
        "2026-11-15",
        "--amount",
        "1",
        expect_ok=False,
    )
    assert env["error"]["code"] == "usage"
    env = budget(*BASE, "--settle", "Car loan:-5@2026-11-15", expect_ok=False)
    assert env["error"]["code"] == "invalid_event"


def test_stop_flow_after_date(budget):
    d = budget(*BASE, "--stop", "Car insurance@2026-11-15", "--ledger")["data"]
    ins = [e["date"] for e in d["ledger"] if e["name"] == "Car insurance"]
    assert ins == ["2026-10-15", "2026-11-15"]
    assert d["ending_balance"] == "15326.70"  # 4 x 120 saved
    assert "ended 1 flow(s) after 2026-11-15: Car insurance" in d["scenario_applied"]


def test_stop_tag_without_settling_warns(budget):
    env = budget(*BASE, "--stop-tag", "car@2026-11-15")
    d = env["data"]
    assert d["ending_balance"] == "16873.34"  # 480 insurance + 4 x 386.66 payments
    assert float(d["total_debt_at_until"]) > 19713.34  # balance stays and accrues
    assert any("ends debt flow 'Car loan'" in w for w in env["warnings"])
    # with a settle by that date there is nothing to warn about
    env = budget(*BASE, "--stop-tag", "car@2026-11-15", "--settle", "Car loan:15000@2026-11-15")
    assert env["warnings"] == []
    assert env["data"]["ending_balance"] == "12160.00"  # 11680.00 + 480


def test_stop_matches_scenario_json_end(budget):
    via_json = budget(
        *BASE,
        "--scenario-json",
        json.dumps({"end": [{"tag": "car", "after": "2026-11-15"}]}),
    )["data"]
    via_flag = budget(*BASE, "--stop-tag", "car@2026-11-15")["data"]
    assert via_json["ending_balance"] == via_flag["ending_balance"]
    env = budget(
        *BASE, "--scenario-json", json.dumps({"end": [{"after": "2026-11-15"}]}), expect_ok=False
    )
    assert env["error"]["code"] == "invalid_scenario"
    env = budget(*BASE, "--stop-tag", "boat@2026-11-15")
    assert any("end tag 'boat' matched no active flow" in w for w in env["warnings"])


def test_placeholder_needs_on_or_earliest(budget):
    env = budget(*BASE, "--add-expense", "Flight:550@?", expect_ok=False)
    assert env["error"]["code"] == "usage" and "earliest" in env["error"]["message"]
    env = budget(
        *BASE, "--add-expense", "Flight:550@2026-10-15", "--on", "2026-10-15", expect_ok=False
    )
    assert env["error"]["code"] == "usage"
    pinned = budget(
        *BASE,
        "--add-expense",
        "Flight:550@?",
        "--settle",
        "Car loan:15000@?+3",
        "--on",
        "2026-11-12",
    )["data"]
    explicit = budget(
        *BASE, "--add-expense", "Flight:550@2026-11-12", "--settle", "Car loan:15000@2026-11-15"
    )["data"]
    assert pinned["ending_balance"] == explicit["ending_balance"] == "11130.00"
    assert "debt event on 'Car loan': settle on 2026-11-15" in pinned["scenario_applied"]


EARLIEST = [
    "earliest",
    "--starting-balance",
    "3000",
    "--as-of",
    "2026-09-16",
    "--months",
    "6",
    "--settle",
    "Car loan:15000@?",
    "--add-expense",
    "Flight:550@?",
    "--stop",
    "Car insurance@?",
]


def test_earliest_finds_first_feasible_date(budget):
    env = budget(*EARLIEST, "--floor", "2000")
    d = env["data"]
    assert d["status"] == "found"
    assert d["date"] == "2026-11-13"  # a payday: the day before, the Dec 1 rent dips to 1230
    assert d["candidates"] == {
        "from": "2026-09-16",
        "before": "2027-03-16",
        "step_days": 1,
        "weekdays_only": False,
        "checked": 182,  # every later date is feasible too, so the whole range was scanned
    }
    assert d["feasible_through"] == "2027-03-16"
    r = d["result"]
    assert r["date"] == "2026-11-13"
    assert r["balance_on_date"] == "3730.00"
    assert r["min_after"] == {"date": "2026-12-01", "balance": "3230.00", "spare": "3230.00"}
    assert r["headroom"] == "1230.00"
    assert r["ending_balance"] == "11730.00"  # 14846.70 - 4713.34 - 550 + 4x386.66 + 5x120
    names = [(e["name"], e["kind"], e["delta"]) for e in r["placeholder_entries"]]
    assert ("Car loan", "settle", "-4713.34") in names and ("Flight", "expense", "-550.00") in names
    assert d["last_infeasible"] == {
        "date": "2026-11-12",
        "min_after": {"date": "2026-11-12", "balance": "1230.00", "spare": "1230.00"},
        "shortfall": "770.00",
    }
    assert d["best_infeasible"] is None
    assert env["warnings"] == []
    # cross-check with project --on: the answer is feasible, the day before is not
    for day, ok in (("2026-11-13", True), ("2026-11-12", False)):
        p = budget(
            "project",
            "--starting-balance",
            "3000",
            "--as-of",
            "2026-09-16",
            "--months",
            "6",
            "--settle",
            "Car loan:15000@?",
            "--add-expense",
            "Flight:550@?",
            "--stop",
            "Car insurance@?",
            "--on",
            day,
            "--granularity",
            "daily",
        )["data"]
        lo = min(float(s["balance"]) for s in p["series"] if s["date"] >= day)
        assert (lo >= 2000) is ok


def test_earliest_spare_measure_is_stricter(budget):
    bal = budget(*EARLIEST, "--floor", "2000")["data"]["date"]
    spare = budget(*EARLIEST, "--floor", "2000", "--measure", "spare")["data"]
    assert spare["measure"] == "spare" and spare["date"] >= bal


def test_earliest_none_in_range(budget):
    env = budget(*EARLIEST, "--floor", "1000000")
    d = env["data"]
    assert d["status"] == "none_in_range" and d["date"] is None and d["result"] is None
    assert d["best_infeasible"]["date"] and float(d["best_infeasible"]["shortfall"]) > 0
    assert any("no date between" in w for w in env["warnings"])


def test_earliest_options(budget):
    d = budget(*EARLIEST, "--floor", "2000", "--weekdays", "--step", "7", "--from", "2026-10-01")[
        "data"
    ]
    assert d["candidates"]["from"] == "2026-10-01" and d["candidates"]["weekdays_only"]
    assert d["status"] == "found" and d["date"] == "2026-11-19"  # Thursdays from Oct 1
    env = budget(*EARLIEST, "--floor", "2000", "--from", "2026-01-01", expect_ok=False)
    assert env["error"]["code"] == "usage"
    env = budget(
        "earliest", "--floor", "2000", "--add-expense", "Flight:550@2026-10-01", expect_ok=False
    )
    assert env["error"]["code"] == "usage" and "'?'" in env["error"]["message"]
