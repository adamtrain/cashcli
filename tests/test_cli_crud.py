import json


def test_flow_roundtrip(run):
    f = run(
        "flow",
        "add",
        "--name",
        "Rent",
        "--kind",
        "expense",
        "--amount",
        "$1,200",
        "--rrule",
        "freq=monthly;bymonthday=1",
        "--dtstart",
        "2026-10-01",
        "--tag",
        "Housing",
        "--notes",
        "x",
    )["data"]
    assert (
        f["amount"] == "1200.00"
        and f["tags"] == ["housing"]
        and f["rrule"] == "FREQ=MONTHLY;BYMONTHDAY=1"
    )
    assert run("flow", "show", "rent")["data"]["id"] == f["id"]
    assert run("flow", "show", str(f["id"]))["data"]["name"] == "Rent"
    u = run(
        "flow", "update", "Rent", "--amount", "1250", "--add-tag", "fixed", "--until", "2027-01-01"
    )["data"]
    assert (
        u["amount"] == "1250.00"
        and u["tags"] == ["fixed", "housing"]
        and u["until"] == "2027-01-01"
    )
    u = run("flow", "update", "Rent", "--set-tags", "--no-until", "--one-off")["data"]
    assert u["tags"] == [] and u["until"] is None and u["rrule"] is None
    assert run("tag", "list")["data"]["tags"] == []
    lst = run("flow", "list")["data"]
    assert lst["count"] == 1
    run("flow", "update", "Rent", "--inactive")
    assert run("flow", "list")["data"]["count"] == 0
    assert run("flow", "list", "--include-inactive")["data"]["count"] == 1
    run("flow", "remove", "Rent")
    assert run("flow", "show", "Rent", expect_ok=False)["error"]["code"] == "unknown_flow"


def test_errors(run):
    run(
        "flow", "add", "--name", "A", "--kind", "income", "--amount", "1", "--dtstart", "2026-10-01"
    )
    assert (
        run(
            "flow",
            "add",
            "--name",
            "a",
            "--kind",
            "income",
            "--amount",
            "1",
            "--dtstart",
            "2026-10-01",
            expect_ok=False,
        )["error"]["code"]
        == "duplicate_flow"
    )
    assert (
        run(
            "flow",
            "add",
            "--name",
            "B",
            "--kind",
            "income",
            "--amount",
            "-1",
            "--dtstart",
            "2026-10-01",
            expect_ok=False,
        )["error"]["code"]
        == "negative_amount"
    )
    assert (
        run(
            "flow",
            "add",
            "--name",
            "B",
            "--kind",
            "income",
            "--amount",
            "1",
            "--dtstart",
            "2026-10-01",
            "--rrule",
            "FREQ=NOPE",
            expect_ok=False,
        )["error"]["code"]
        == "invalid_rrule"
    )
    assert (
        run(
            "flow",
            "add",
            "--name",
            "B",
            "--kind",
            "income",
            "--amount",
            "1",
            "--dtstart",
            "2026-10-01",
            "--until",
            "2025-01-01",
            expect_ok=False,
        )["error"]["code"]
        == "invalid_date"
    )
    assert (
        run(
            "debt",
            "set",
            "A",
            "--balance",
            "1",
            "--balance-as-of",
            "2026-10-01",
            "--rate",
            "0.1",
            "--compounding",
            "monthly",
            expect_ok=False,
        )["error"]["code"]
        == "debt_requires_expense"
    )
    env = run("flow", "list", "--bogus", expect_ok=False)
    assert env["error"]["code"] == "usage"


def test_debt_crud(run):
    run(
        "flow",
        "add",
        "--name",
        "Loan",
        "--kind",
        "expense",
        "--amount",
        "100",
        "--rrule",
        "FREQ=MONTHLY",
        "--dtstart",
        "2026-11-01",
    )
    assert (
        run(
            "debt",
            "set",
            "Loan",
            "--balance",
            "1000",
            "--balance-as-of",
            "2026-10-01",
            "--rate",
            "5%",
            "--compounding",
            "simple",
            "--capitalize",
            expect_ok=False,
        )["error"]["code"]
        == "invalid_debt"
    )
    d = run(
        "debt",
        "set",
        "Loan",
        "--balance",
        "1000",
        "--balance-as-of",
        "2026-10-01",
        "--rate",
        "5%",
        "--compounding",
        "daily",
        "--no-capitalize",
        "--original-principal",
        "1500",
    )["data"]["debt"]
    assert (
        d["annual_rate"] == "0.05"
        and d["capitalize_interest"] is False
        and d["original_principal"] == "1500.00"
    )
    assert (
        run("flow", "update", "Loan", "--kind", "income", expect_ok=False)["error"]["code"]
        == "debt_requires_expense"
    )
    e = run(
        "debt",
        "events",
        "add",
        "Loan",
        "--type",
        "rate_change",
        "--date",
        "2027-01-01",
        "--rate",
        "4%",
    )["data"]
    run(
        "debt",
        "events",
        "add",
        "Loan",
        "--type",
        "balance_adjustment",
        "--date",
        "2027-01-01",
        "--amount",
        "-50",
    )
    assert (
        run(
            "debt",
            "events",
            "add",
            "Loan",
            "--type",
            "payoff",
            "--date",
            "2027-01-01",
            "--amount",
            "5",
            expect_ok=False,
        )["error"]["code"]
        == "invalid_event"
    )
    evs = run("debt", "events", "list", "Loan")["data"]["events"]
    assert len(evs) == 2 and evs[1]["amount"] == "-50.00"
    run("debt", "events", "remove", str(e["id"]))
    assert len(run("debt", "show", "Loan")["data"]["debt"]["events"]) == 1
    run("debt", "unset", "Loan")
    assert run("flow", "show", "Loan")["data"]["debt"] is None
    assert run("debt", "show", "Loan", expect_ok=False)["error"]["code"] == "no_debt"


def test_tag_commands(run):
    run(
        "flow",
        "add",
        "--name",
        "A",
        "--kind",
        "expense",
        "--amount",
        "1",
        "--dtstart",
        "2026-10-01",
        "--tag",
        "car",
    )
    run("tag", "rename", "car", "auto")
    assert run("flow", "show", "A")["data"]["tags"] == ["auto"]
    run("tag", "remove", "auto")
    assert run("flow", "show", "A")["data"]["tags"] == []
    assert run("tag", "remove", "auto", expect_ok=False)["error"]["code"] == "unknown_tag"


def test_export_import_roundtrip(budget, tmp_path, db_path):
    budget(
        "debt",
        "events",
        "add",
        "Car loan",
        "--type",
        "extra_payment",
        "--date",
        "2027-01-01",
        "--amount",
        "500",
    )
    exp = budget("export")["data"]
    f = tmp_path / "exp.json"
    f.write_text(json.dumps(exp))
    assert budget("import", str(f), expect_ok=False)["error"]["code"] == "db_not_empty"
    n = budget("import", str(f), "--replace")["data"]["imported_flows"]
    assert n == 4
    again = budget("export")["data"]
    exp.pop("exported_at"), again.pop("exported_at")
    assert again == exp
    assert (
        budget("debt", "schedule", "Car loan", "--as-of", "2026-10-01")["data"]["payoff_date"]
        == "2031-09-01"
    )


def test_sql(budget):
    d = budget("sql", "SELECT count(*) AS n FROM flow")["data"]
    assert d["rows"] == [{"n": 4}] and d["columns"] == ["n"]
    assert budget("sql", "DELETE FROM flow", expect_ok=False)["error"]["code"] == "readonly_sql"
    assert budget("sql", "SELECT nope FROM flow", expect_ok=False)["error"]["code"] == "sql_error"
    d = budget("sql", "SELECT id FROM flow", "--limit", "2")["data"]
    assert d["truncated"] is True and d["row_count"] == 2


def test_schema_and_help(run):
    ref = run("schema")["data"]["reference"]
    assert "CREATE TABLE flow" in ref and "FREQ=YEARLY;BYMONTH=11;BYDAY=3TU" in ref
    h = run("help")["data"]["help"]
    assert "cash flow add" in h and "cash debt schedule" in h


def test_init_and_missing_db(tmp_path, capsys):
    from cashcli.cli import main

    p = tmp_path / "x.sqlite"
    assert main(["flow", "list", "--db", str(p)]) == 1
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "db_not_found"
    assert main(["init", "--db", str(p)]) == 0
    capsys.readouterr()
    assert main(["init", "--db", str(p)]) == 1
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "db_exists"
    assert main(["init", "--force", "--db", str(p)]) == 0
    capsys.readouterr()
    assert main(["--db", str(p), "--pretty", "flow", "list"]) == 0
    assert "count: 0" in capsys.readouterr().out


def test_env_var_db(tmp_path, monkeypatch, capsys):
    from cashcli.cli import main

    p = tmp_path / "env.sqlite"
    monkeypatch.setenv("CASHCLI_DB", str(p))
    assert main(["init"]) == 0
    assert p.exists()


def test_default_db_path(monkeypatch, tmp_path):
    from pathlib import Path

    from cashcli.db import resolve_db_path

    monkeypatch.delenv("CASHCLI_DB", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert resolve_db_path(None) == Path.home() / ".config" / "cashcli" / "budget.sqlite"

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert resolve_db_path(None) == tmp_path / "xdg" / "cashcli" / "budget.sqlite"

    monkeypatch.setenv("CASHCLI_DB", str(tmp_path / "env.sqlite"))
    assert resolve_db_path(None) == tmp_path / "env.sqlite"
    assert resolve_db_path(str(tmp_path / "cli.sqlite")) == tmp_path / "cli.sqlite"
