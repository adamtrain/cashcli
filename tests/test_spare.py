def test_spare_balance_on_payday(budget):
    # 2026-11-13 is a payday; next payday 11-27; insurance (120) lands 11-15 in between
    d = budget("project", "--starting-balance", "3000", "--until", "2026-11-13")["data"]
    assert d["ending_balance"] == "8993.34"
    assert d["spare"]["next_income"] == {
        "date": "2026-11-27",
        "name": "Salary",
        "amount": "2500.00",
    }
    assert d["spare"]["committed_before_next_income"] == [
        {"date": "2026-11-15", "name": "Car insurance", "amount": "120.00"}
    ]
    assert d["spare_balance"] == "8873.34"
    assert d["series"][-1]["spare"] == "8873.34"
    assert all("spare" in r for r in d["series"])


def test_spare_excludes_expenses_on_income_day_and_no_spare_flag(budget):
    # 2026-11-30: next payday 12-11; rent+loan 12-01 are before it
    d = budget("project", "--starting-balance", "3000", "--until", "2026-11-30")["data"]
    committed = {c["name"]: c["amount"] for c in d["spare"]["committed_before_next_income"]}
    assert committed == {"Rent": "3000.00", "Car loan": "386.66"}
    d = budget("project", "--starting-balance", "3000", "--until", "2026-11-30", "--no-spare")[
        "data"
    ]
    assert d["spare"] is None and d["spare_balance"] is None and "spare" not in d["series"][0]


def test_spare_null_without_income(run):
    run(
        "flow",
        "add",
        "--name",
        "Rent",
        "--kind",
        "expense",
        "--amount",
        "10",
        "--rrule",
        "FREQ=MONTHLY",
        "--dtstart",
        "2026-10-01",
    )
    env = run("project", "--until", "2026-10-15")
    assert env["data"]["spare_balance"] is None
    assert any("no income found" in w for w in env["warnings"])
