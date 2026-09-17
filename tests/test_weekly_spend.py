from datetime import date

from cashcli import engine
from cashcli.models import EffectiveModel


def test_weekly_spend_prorated_exactly():
    m = EffectiveModel(flows=[])
    r = engine.run(m, as_of=date(2026, 9, 16), until=date(2026, 11, 13), weekly_spend_cents=20000)
    days = (date(2026, 11, 13) - date(2026, 9, 16)).days
    assert days == 58
    assert r.expense_cents == 165714  # round(58 * 200 / 7, 2) = 1657.142857 -> 1657.14
    assert len(r.ledger) == 58 and r.ledger[0].date == date(2026, 9, 17)
    assert all(e.amount_cents in (2857, 2858) for e in r.ledger)
    r = engine.run(m, as_of=date(2026, 9, 16), until=date(2026, 9, 23), weekly_spend_cents=20000)
    assert r.expense_cents == 20000  # exactly one week


def test_weekly_spend_in_project_and_spare(budget):
    d = budget(
        "project",
        "--starting-balance",
        "3000",
        "--until",
        "2026-11-13",
        "--weekly-spend",
        "70",
        "--verbose",
    )["data"]
    assert d["weekly_spend"] == "70.00" and d["lifestyle_total"] == "580.00"  # 58 days x 10
    assert d["ending_balance"] == "8413.34"  # 8993.34 - 580
    # spare: 13 days x 10 lifestyle + insurance 120 before the 11-27 payday
    assert d["spare"]["committed_lifestyle"] == "130.00"
    assert d["spare"]["committed_total"] == "250.00"
    assert d["spare_balance"] == "8163.34"
    assert [c["name"] for c in d["spare"]["committed_before_next_income"]] == ["Car insurance"]
    assert any(u["flow"] == "lifestyle" for u in d["flows_used"])


def test_scenario_overrides_weekly_spend(budget):
    d = budget(
        "project",
        "--starting-balance",
        "3000",
        "--until",
        "2026-11-13",
        "--weekly-spend",
        "70",
        "--scenario-json",
        '{"weekly_spend": "140"}',
    )["data"]
    assert d["weekly_spend"] == "140.00" and d["lifestyle_total"] == "1160.00"
    c = budget(
        "compare",
        "--scenario-json",
        '{"name":"frugal","weekly_spend":"70"}',
        "--weekly-spend",
        "140",
        "--as-of",
        "2026-09-16",
        "--until",
        "2026-11-13",
    )["data"]
    assert c["a"]["weekly_spend"] == "140.00" and c["b"]["weekly_spend"] == "70.00"
    assert c["difference"]["ending"] == "580.00"
    assert c["breakeven"]["status"] == "immediate"
