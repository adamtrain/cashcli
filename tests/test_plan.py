"""`cash plan`: extra money toward the debts, avalanche / snowball / explicit order, rollover."""

import json

import pytest


@pytest.fixture
def debts(budget):
    """budget fixture + two small simple-interest debts: Card 1000 @ 24% (50/mo), Store 500 @ 3% (25/mo)."""
    for name, amount, bal, rate in (("Card", "50", "1000", "24%"), ("Store", "25", "500", "3%")):
        budget(
            "flow",
            "add",
            "--name",
            name,
            "--kind",
            "expense",
            "--amount",
            amount,
            "--rrule",
            "FREQ=MONTHLY;BYMONTHDAY=1",
            "--dtstart",
            "2026-10-01",
            "--tag",
            "loan",
        )
        budget(
            "debt",
            "set",
            name,
            "--balance",
            bal,
            "--balance-as-of",
            "2026-09-16",
            "--rate",
            rate,
            "--compounding",
            "simple",
        )
    return budget


def names(d):
    return [s["name"] for s in d["steps"]]


def test_avalanche_rolls_freed_payments_and_leftovers(debts):
    env = debts("plan", "--extra", "300", "--starting-balance", "3000", "--verbose")
    d = env["data"]
    assert d["strategy"] == "avalanche" and d["rollover"] is True
    assert names(d) == ["Card", "Store", "Car loan"] or names(d) == ["Card", "Car loan", "Store"]
    card, loan = d["steps"][0], next(s for s in d["steps"] if s["name"] == "Car loan")
    # Card: 1000 @ 24% simple, 350/mo from Oct 1 -> paid off Dec 1 with 20.31 of that payment unused
    assert card["payment_during"] == "350.00" and card["from"] == "2026-09-16"
    assert card["paid_off_on"] == "2026-12-01" and card["leftover_to_next"] == "20.31"
    assert card["freed_to_pool"] == "50.00" and card["baseline_paid_off_on"] == "2028-11-01"
    # Car loan takes over: 386.66 + 300 + 50, plus the 20.31 the same day
    assert loan["payment_during"] == "736.66" and loan["from"] == "2026-12-02"
    assert loan["carry_in"] == "20.31" and loan["paid_off_on"] == "2029-05-01"
    # Store pays itself off on schedule before its turn
    store = next(s for s in d["steps"] if s["name"] == "Store")
    assert store["paid_off_before_turn"] is True and store["paid_off_on"] == "2028-06-01"
    assert d["status"] == "debt_free" and d["debt_free_on"] == "2029-05-01" and d["months"] == 31
    assert d["total_balance_at_start"] == "21500.00"
    assert d["monthly_outlay"] == {"scheduled_payments": "461.66", "with_extra": "761.66"}
    assert (
        d["baseline"]["debt_free_on"] == "2031-10-01"
        and d["baseline"]["interest_paid"] == "3485.79"
    )
    assert d["interest_paid"] == "1696.06" and d["interest_saved"] == "1789.73"
    # no plan events were generated for the debt that never needed them
    assert {e["flow"] for e in d["plan_scenario"]["debt_events"]} == {"Card", "Car loan"}
    cc = d["cash_check"]
    assert cc["until"] == "2029-05-01" and cc["affordable"] is True
    assert cc["min_balance_after_start"]["date"] == "2026-10-01"
    assert env["warnings"] == []


def test_snowball_smallest_balance_first(debts):
    d = debts("plan", "--extra", "300", "--strategy", "snowball")["data"]
    assert names(d) == ["Store", "Card", "Car loan"]
    assert [s["payment_during"] for s in d["steps"]] == ["325.00", "375.00", "761.66"]
    assert [s["leftover_to_next"] for s in d["steps"]] == ["148.94", "319.43", "1.51"]
    assert [s["paid_off_on"] for s in d["steps"]] == ["2026-11-01", "2027-02-01", "2029-04-01"]
    assert d["debt_free_on"] == "2029-04-01" and d["interest_paid"] == "1723.31"


def test_no_rollover_is_slower(debts):
    d = debts("plan", "--extra", "300", "--no-rollover")["data"]
    assert d["rollover"] is False and d["debt_free_on"] == "2029-07-01"
    by = {s["name"]: s for s in d["steps"]}
    assert by["Card"]["payment_during"] == "350.00" and by["Car loan"]["payment_during"] == "686.66"


def test_explicit_order_exclude_tag_and_from(debts):
    env = debts("plan", "--extra", "300", "--order", "Store,Car loan")
    assert (
        names(env["data"]) == ["Store", "Car loan", "Card"] and env["data"]["strategy"] == "order"
    )
    assert any("follow in avalanche order: Card" in w for w in env["warnings"])
    d = debts("plan", "--extra", "300", "--from", "2026-11-15", "--exclude", "Car loan")["data"]
    assert d["start"] == "2026-11-15" and names(d) == ["Card", "Store"]
    assert d["steps"][0]["balance_at_start"] == "937.98" and d["steps"][0]["from"] == "2026-11-15"
    d = debts("plan", "--extra", "300", "--tag", "car")["data"]
    assert names(d) == ["Car loan"]
    env = debts("plan", "--extra", "300", "--order", "Boat", expect_ok=False)
    assert env["error"]["code"] == "unknown_flow"
    env = debts(
        "plan", "--extra", "300", "--from", "2029-01-01", "--exclude", "Car loan", expect_ok=False
    )
    assert env["error"]["code"] == "usage"  # Card and Store are already paid off by then


def test_plan_scenario_reproduces_in_project(debts):
    sc = debts("plan", "--extra", "300")["data"]["plan_scenario"]
    p = debts("project", "--months", "36", "--scenario-json", json.dumps(sc), "--verbose")["data"]
    paid = {x["name"]: x["paid_off_on"] for x in p["debts"]}
    assert paid == {"Car loan": "2029-05-01", "Card": "2026-12-01", "Store": "2028-06-01"}


def test_plan_with_settle_skips_the_sold_debt(debts):
    env = debts(
        "plan",
        "--extra",
        "300",
        "--from",
        "2026-11-16",
        "--settle",
        "Car loan:15000@2026-11-15",
        "--stop-tag",
        "car@2026-11-15",
    )
    assert names(env["data"]) == ["Card", "Store"]
    assert any("'Car loan' is already paid off on 2026-11-15" in w for w in env["warnings"])
