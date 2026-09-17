import json


def test_breakeven_reached_and_never(run):
    run(
        "flow",
        "add",
        "--name",
        "Gym",
        "--kind",
        "expense",
        "--amount",
        "500",
        "--rrule",
        "FREQ=MONTHLY;BYMONTHDAY=1",
        "--dtstart",
        "2026-10-01",
    )
    scen = json.dumps(
        {
            "name": "buy equipment",
            "disable": {"flows": ["Gym"]},
            "add_flows": [
                {"name": "Equipment", "kind": "expense", "amount": "2400", "on": "2026-09-20"}
            ],
        }
    )
    d = run("breakeven", "--scenario-json", scen, "--as-of", "2026-09-16", "--months", "12")["data"]
    b = d["breakeven"]
    assert b["status"] == "reached" and b["date"] == "2027-02-01"
    assert b["first_divergence"] == "2026-09-20"
    assert b["max_shortfall"] == {"date": "2026-09-20", "amount": "-2400.00"}
    assert d["b"]["label"] == "buy equipment"
    assert "series" not in d["a"]
    d = run("breakeven", "--scenario-json", scen, "--as-of", "2026-09-16", "--months", "3")["data"]
    b = d["breakeven"]
    assert b["status"] == "never_in_horizon" and b["diff_at_end"] == "-900.00"
    assert b["caveat"] and b["extrapolated_date"]


def test_immediate_and_identical(budget):
    scen = json.dumps(
        {"add_flows": [{"name": "Bonus", "kind": "income", "amount": "100", "on": "2026-10-01"}]}
    )
    b = budget("breakeven", "--scenario-json", scen, "--as-of", "2026-09-16")["data"]["breakeven"]
    assert b["status"] == "immediate" and b["date"] == "2026-10-01"
    b = budget("breakeven", "--scenario-json", "{}", "--as-of", "2026-09-16")["data"]["breakeven"]
    assert b["status"] == "identical" and b["date"] is None


def test_sell_car_breakeven(budget, tmp_path):
    spec = {
        "name": "sell car",
        "disable": {"tags": ["car"]},
        "add_flows": [
            {"name": "Car sale", "kind": "income", "amount": "15000", "on": "2026-10-15"}
        ],
        "debt_events": [{"flow": "Car loan", "type": "payoff", "date": "2026-10-15"}],
    }
    f = tmp_path / "sell.json"
    f.write_text(json.dumps(spec))
    d = budget("breakeven", "--scenario", str(f), "--as-of", "2026-09-16")["data"]
    assert d["breakeven"]["date"] == "2027-08-01" and d["breakeven"]["status"] == "reached"
    assert d["breakeven"]["max_shortfall"]["amount"] == "-4880.00"
    assert any("kept debt flow" in a for a in d["scenario_applied"])


def test_compare_series(budget):
    scen = json.dumps({"disable": {"tags": ["car"]}})
    d = budget(
        "compare",
        "--scenario-json",
        scen,
        "--starting-balance",
        "3000",
        "--as-of",
        "2026-09-16",
        "--months",
        "6",
    )["data"]
    assert d["a"]["ending_balance"] == "14846.70" and d["b"]["ending_balance"] == "17500.00"
    assert d["difference"]["ending"] == "2653.30"
    assert d["difference"]["series"][-1]["diff"] == "2653.30"
    assert len(d["difference"]["series"]) == 8


def test_compare_with_baseline_scenario(budget, tmp_path):
    base = tmp_path / "base.json"
    base.write_text(json.dumps({"name": "no rent", "disable": {"flows": ["Rent"]}}))
    scen = json.dumps({"name": "no rent no car", "disable": {"flows": ["Rent"], "tags": ["car"]}})
    d = budget(
        "compare",
        "--baseline",
        str(base),
        "--scenario-json",
        scen,
        "--as-of",
        "2026-09-16",
        "--months",
        "6",
    )["data"]
    assert d["a"]["label"] == "no rent" and d["b"]["label"] == "no rent no car"
    assert d["difference"]["ending"] == "2653.30"
    assert d["baseline_applied"]


def test_compare_requires_scenario(budget):
    env = budget("compare", expect_ok=False)
    assert env["error"]["code"] == "usage"
