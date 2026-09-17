def test_summary_car_tag(budget):
    d = budget("summary", "--as-of", "2026-09-16", "--tag", "car")["data"]
    car = next(t for t in d["by_tag"] if t["tag"] == "car")
    assert car["expense_monthly"] == "506.66"
    assert car["expense_annual"] == "6079.92"
    assert sorted(car["flows"]) == [3, 4]
    loan = next(f for f in d["by_flow"] if f["name"] == "Car loan")
    assert loan["occurrences_per_year"] == "12" and loan["monthly"] == "386.66" and loan["is_debt"]


def test_summary_net_and_one_offs(budget):
    budget(
        "flow",
        "add",
        "--name",
        "Tax refund",
        "--kind",
        "income",
        "--amount",
        "1200",
        "--dtstart",
        "2027-04-15",
    )
    d = budget("summary", "--as-of", "2026-09-16")["data"]
    assert d["net"]["income_monthly"] == "5436.51"  # 2500 * 2192/84 / 12
    assert d["net"]["expense_monthly"] == "3506.66"
    assert d["one_offs"] == [
        {
            "flow": 5,
            "name": "Tax refund",
            "kind": "income",
            "date": "2027-04-15",
            "amount": "1200.00",
            "tags": [],
        }
    ]
    assert d["untagged"]["income_monthly"] == "0.00"


def test_summary_actual_mode(budget):
    d = budget(
        "summary", "--as-of", "2026-09-16", "--mode", "actual", "--months", "6", "--by", "flow"
    )["data"]
    salary = next(f for f in d["by_flow"] if f["name"] == "Salary")
    assert salary["occurrences_in_window"] == "13" and salary["monthly"] == "5416.67"
    loan = next(f for f in d["by_flow"] if f["name"] == "Car loan")
    assert loan["occurrences_in_window"] == "5"
    assert "by_tag" not in d


def test_summary_with_scenario(budget):
    d = budget(
        "summary", "--as-of", "2026-09-16", "--scenario-json", '{"disable":{"tags":["car"]}}'
    )["data"]
    assert d["net"]["expense_monthly"] == "3000.00"
    assert d["scenario_applied"]
