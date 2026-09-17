def test_spend_by_tag(budget):
    d = budget("spend", "car", "--until", "2026-12-12")["data"]
    assert d["total"] == "1013.32"
    assert d["matched"] == [{"term": "car", "as": "tag"}]
    assert [(f["name"], f["count"], f["total"]) for f in d["by_flow"]] == [
        ("Car loan", 2, "773.32"),
        ("Car insurance", 2, "240.00"),
    ]
    assert d["items"][0] == {"date": "2026-10-15", "name": "Car insurance", "amount": "120.00"}
    assert d["lifestyle_total"] == "0.00"


def test_spend_flow_names_exclude_and_income(budget):
    d = budget("spend", "car insurance", "rent", "--until", "2026-12-12")["data"]
    assert d["total"] == "9240.00"
    assert [m["as"] for m in d["matched"]] == ["flow", "flow"]
    d = budget("spend", "car", "--exclude", "loan", "--until", "2026-12-12")["data"]
    assert d["total"] == "240.00"
    d = budget("spend", "--income", "--until", "2026-10-31")["data"]
    assert d["total"] == "10000.00" and d["direction"] == "in"


def test_spend_everything_includes_lifestyle_and_scenarios(budget):
    d = budget("spend", "--until", "2026-09-30", "--weekly-spend", "70")["data"]
    assert d["total"] == d["lifestyle_total"] == "140.00" and d["items"] == []
    d = budget("spend", "car", "--until", "2026-12-12", "--stop-tag", "car@2026-11-10")["data"]
    assert d["total"] == "506.66"


def test_spend_unknown_term_lists_tags(budget):
    env = budget("spend", "cars", expect_ok=False)
    assert env["error"]["code"] == "unknown_term"
    assert "car, housing, job, lifestyle, loan" in env["error"]["message"]


def test_spend_tag_on_inactive_flows_is_zero(budget):
    budget("flow", "update", "Car insurance", "--inactive")
    budget("flow", "update", "Car loan", "--inactive")
    assert budget("spend", "car", "--until", "2026-12-12")["data"]["total"] == "0.00"


def test_tag_list_names_flows(budget):
    tags = budget("tag", "list")["data"]["tags"]
    car = next(t for t in tags if t["name"] == "car")
    assert car == {"name": "car", "flows": 2, "flow_names": ["Car loan", "Car insurance"]}
