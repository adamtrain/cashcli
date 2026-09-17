def test_project_six_months(budget):
    d = budget(
        "project",
        "--starting-balance",
        "3000",
        "--as-of",
        "2026-09-16",
        "--months",
        "6",
        "--verbose",
    )["data"]
    assert d["until"] == "2027-03-16"
    assert d["ending_balance"] == "14846.70"
    assert d["min_balance"] == {"date": "2026-10-01", "balance": "2500.00"}
    assert d["totals"]["income"] == "32500.00"
    assert d["totals"]["expense"] == "20653.30"
    assert [r["date"] for r in d["series"]] == [
        "2026-09-16",
        "2026-09-30",
        "2026-10-31",
        "2026-11-30",
        "2026-12-31",
        "2027-01-31",
        "2027-02-28",
        "2027-03-16",
    ]
    assert d["series"][-1]["balance"] == "14846.70"
    salary = next(u for u in d["flows_used"] if u["name"] == "Salary")
    assert salary["occurrences"] == 13 and salary["total"] == "32500.00"
    loan = d["debts"][0]
    assert loan["name"] == "Car loan" and loan["balance_at_as_of"] == "20000.00"
    assert loan["balance_at_until"] == "18552.30"  # after 5 payments
    assert "ledger" not in d


def test_series_sums_match_totals(budget):
    d = budget(
        "project",
        "--starting-balance",
        "3000",
        "--as-of",
        "2026-09-16",
        "--months",
        "6",
        "--verbose",
    )["data"]
    inc = sum(float(r["income"]) for r in d["series"])
    exp = sum(float(r["expense"]) for r in d["series"])
    assert round(inc, 2) == 32500.00 and round(exp, 2) == 20653.30


def test_daily_granularity_and_ledger(budget):
    d = budget(
        "project", "--as-of", "2026-09-16", "--months", "6", "--granularity", "daily", "--ledger"
    )["data"]
    assert len(d["series"]) == 182
    row = next(e for e in d["ledger"] if e["date"] == "2026-11-01" and e["name"] == "Car loan")
    assert row["debt"] == {"interest": "100.00", "principal": "286.66", "balance_after": "19713.34"}
    assert row["kind"] == "debt_payment"


def test_inactive_and_until(budget):
    budget("flow", "update", "Rent", "--until", "2026-12-01")
    budget("flow", "update", "Car insurance", "--inactive")
    d = budget(
        "project",
        "--starting-balance",
        "3000",
        "--as-of",
        "2026-09-16",
        "--months",
        "6",
        "--verbose",
    )["data"]
    rent = next(u for u in d["flows_used"] if u["name"] == "Rent")
    assert rent["occurrences"] == 3
    assert all(u["name"] != "Car insurance" for u in d["flows_used"])
    assert d["ending_balance"] == "24566.70"  # +3 rents (9000) + 6 insurance (720)


def test_default_as_of_is_today(budget):
    d = budget("project")["data"]
    assert d["as_of"] <= d["until"]


def test_until_before_as_of_is_usage_error(budget):
    env = budget("project", "--as-of", "2026-01-01", "--until", "2025-01-01", expect_ok=False)
    assert env["error"]["code"] == "usage"
