import json


def test_select_and_compact(budget, capsys):

    d = budget(
        "project",
        "--starting-balance",
        "3000",
        "--until",
        "2026-11-13",
        "--select",
        "ending_balance,spare.next_income.date,series[-1].balance",
    )["data"]
    assert d == {
        "ending_balance": "8993.34",
        "spare.next_income.date": "2026-11-27",
        "series[-1].balance": "8993.34",
    }
    env = budget("project", "--select", "nope", expect_ok=False)
    assert env["error"]["code"] == "select_not_found"
    budget("project", "--compact", "--select", "ending_balance")
    # compact => one line


def test_trimmed_vs_verbose(budget):
    d = budget(
        "project", "--starting-balance", "3000", "--months", "1", "--weekly-spend", "70", "--ledger"
    )["data"]
    assert "flows_used" not in d and d["scenario"] is None
    assert all(e["kind"] != "lifestyle" for e in d["ledger"]) and "ledger_note" in d
    assert set(d["debts"][0]) == {"flow", "name", "balance_at_until", "paid_off_on"}
    v = budget(
        "project",
        "--starting-balance",
        "3000",
        "--months",
        "1",
        "--weekly-spend",
        "70",
        "--ledger",
        "--verbose",
    )["data"]
    assert "flows_used" in v and any(e["kind"] == "lifestyle" for e in v["ledger"])
    assert "interest_accrued_in_window" in v["debts"][0]


def test_shortcut_flags_match_scenario_json(budget):
    via_json = budget(
        "project",
        "--starting-balance",
        "3000",
        "--until",
        "2026-11-13",
        "--scenario-json",
        json.dumps(
            {
                "disable": {"tags": ["car"]},
                "add_flows": [
                    {"name": "Car sale", "kind": "income", "amount": "15000", "on": "2026-10-15"}
                ],
                "debt_events": [{"flow": "Car loan", "type": "payoff", "date": "2026-10-15"}],
            }
        ),
    )["data"]
    via_flags = budget(
        "project",
        "--starting-balance",
        "3000",
        "--until",
        "2026-11-13",
        "--disable-tag",
        "car",
        "--add-income",
        "Car sale:15000@2026-10-15",
        "--payoff",
        "Car loan@2026-10-15",
    )["data"]
    assert via_flags["ending_balance"] == via_json["ending_balance"]
    assert via_flags["spare_balance"] == via_json["spare_balance"]
    d = budget(
        "project",
        "--starting-balance",
        "3000",
        "--until",
        "2026-11-13",
        "--extra-payment",
        "Car loan:5000@2026-10-15",
        "--set-amount",
        "Rent:3500@2026-11-01",
        "--add-expense",
        "Vet: bill:120@2026-10-20",
    )["data"]
    assert d["ending_balance"] == "3373.34"  # 8993.34 - 5000 - 500 - 120
    assert any("Vet: bill" in a for a in d["scenario_applied"])
    env = budget("project", "--payoff", "Car loan", expect_ok=False)
    assert env["error"]["code"] == "usage"
    # shortcuts also satisfy compare/breakeven's scenario requirement and merge with a json scenario
    b = budget(
        "breakeven",
        "--disable-tag",
        "car",
        "--add-income",
        "Car sale:15000@2026-10-15",
        "--payoff",
        "Car loan@2026-10-15",
        "--as-of",
        "2026-09-16",
    )["data"]
    assert b["breakeven"]["date"] == "2027-08-01"
    m = budget(
        "project",
        "--until",
        "2026-11-13",
        "--scenario-json",
        '{"name":"x","disable":{"flows":["Rent"]}}',
        "--disable",
        "Car insurance",
    )["data"]
    assert (
        m["scenario"] == "x"
        and len([a for a in m["scenario_applied"] if a.startswith("disabled")]) == 2
    )


def test_config_weekly_spend_default(budget):
    assert budget("config", "list")["data"]["config"] == {}
    budget("config", "set", "weekly_spend", "70")
    assert budget("config", "get", "weekly_spend")["data"]["value"] == "70"
    d = budget("project", "--starting-balance", "3000", "--until", "2026-11-13")["data"]
    assert d["weekly_spend"] == "70.00" and d["lifestyle_total"] == "580.00"
    d = budget(
        "project", "--starting-balance", "3000", "--until", "2026-11-13", "--weekly-spend", "0"
    )["data"]
    assert d["weekly_spend"] == "0.00"
    assert budget("config", "set", "bogus", "1", expect_ok=False)["error"]["code"] == "usage"
    budget("config", "unset", "weekly_spend")
    assert budget("project", "--months", "1")["data"]["weekly_spend"] == "0.00"


def test_schedule_max_rows(budget):
    d = budget("debt", "schedule", "Car loan", "--as-of", "2026-10-01", "--max-rows", "5")["data"]
    assert len(d["rows"]) == 5 and d["rows_truncated"] is True and d["payments_remaining"] == 60
