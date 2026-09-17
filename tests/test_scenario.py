import json


def project(run, scenario, **kw):
    argv = [
        "project",
        "--starting-balance",
        "3000",
        "--as-of",
        "2026-09-16",
        "--months",
        "6",
        "--scenario-json",
        json.dumps(scenario),
        "--verbose",
    ]
    return run(*argv, **kw)


def test_disable_by_tag(budget):
    d = project(budget, {"disable": {"tags": ["car"]}})["data"]
    assert d["ending_balance"] == "17500.00"
    assert d["debts"] == []


def test_disable_by_name_and_id(budget):
    assert (
        project(budget, {"disable": {"flows": ["car insurance"]}})["data"]["ending_balance"]
        == "15566.70"
    )
    assert project(budget, {"disable": {"flow_ids": [4]}})["data"]["ending_balance"] == "15566.70"


def test_amount_change(budget):
    d = project(
        budget, {"amount_changes": [{"flow": "Rent", "amount": "3500", "from": "2027-01-01"}]}
    )["data"]
    assert d["ending_balance"] == "13346.70"


def test_add_one_off_and_recurring(budget):
    d = project(
        budget,
        {
            "add_flows": [
                {"name": "Car sale", "kind": "income", "amount": "15000", "on": "2026-10-15"}
            ]
        },
    )["data"]
    assert d["ending_balance"] == "29846.70"
    assert any(u["flow"] == "s:1" and u["origin"] == "scenario" for u in d["flows_used"])
    d = project(
        budget,
        {
            "add_flows": [
                {
                    "name": "Bus",
                    "kind": "expense",
                    "amount": "90",
                    "rrule": "FREQ=MONTHLY;BYMONTHDAY=1",
                    "dtstart": "2026-11-01",
                }
            ]
        },
    )["data"]
    assert d["ending_balance"] == "14396.70"  # 5 x 90


def test_unknown_flow_is_error(budget):
    env = project(budget, {"disable": {"flows": ["Carr loan"]}}, expect_ok=False)
    assert env["error"]["code"] == "scenario_unknown_flow"


def test_unknown_key_is_error(budget):
    env = project(budget, {"disabel": {}}, expect_ok=False)
    assert env["error"]["code"] == "invalid_scenario"


def test_unknown_tag_warns(budget):
    env = project(budget, {"disable": {"tags": ["boat"]}})
    assert any("matched no active flow" in w for w in env["warnings"])


def test_enable_inactive_flow(budget):
    budget("flow", "update", "Car insurance", "--inactive")
    assert project(budget, {})["data"]["ending_balance"] == "15566.70"
    assert (
        project(budget, {"enable": {"flows": ["Car insurance"]}})["data"]["ending_balance"]
        == "14846.70"
    )


def test_scenario_debt_events(budget):
    d = project(
        budget, {"debt_events": [{"flow": "Car loan", "type": "payoff", "date": "2026-10-15"}]}
    )["data"]
    assert d["ending_balance"] == "-3220.00"  # 14846.70 - 20000 + 5 x 386.66
    assert d["debts"][0]["paid_off_on"] == "2026-10-15"
    d = project(
        budget,
        {
            "debt_events": [
                {
                    "flow": "Car loan",
                    "type": "extra_payment",
                    "date": "2026-10-15",
                    "amount": "5000",
                }
            ]
        },
    )["data"]
    assert d["ending_balance"] == "9846.70"


def test_disable_debt_without_payoff_warns(budget):
    env = project(budget, {"disable": {"flows": ["Car loan"]}})
    assert any("without a payoff" in w for w in env["warnings"])


def test_adhoc_debt_flow(budget):
    spec = {
        "add_flows": [
            {
                "name": "New loan",
                "kind": "expense",
                "amount": "386.66",
                "rrule": "FREQ=MONTHLY;BYMONTHDAY=1",
                "dtstart": "2026-11-01",
                "debt": {
                    "balance": "20000",
                    "balance_as_of": "2026-10-01",
                    "annual_rate": "6%",
                    "compounding": "monthly",
                },
            }
        ],
        "debt_events": [
            {"flow": "s:1", "type": "extra_payment", "date": "2026-10-15", "amount": "5000"}
        ],
    }
    d = project(budget, spec)["data"]
    new = next(x for x in d["debts"] if x["name"] == "New loan")
    assert new["balance_at_as_of"] == "20000.00"
    assert d["ending_balance"] == "7913.40"  # -5 payments -5000 extra
