"""The `cash` command. Every command prints one JSON envelope (or a --pretty rendering)."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date
from importlib import resources
from pathlib import Path

from cashcli import __version__, db, repo
from cashcli.cleanup import run_cleanup
from cashcli.dates import add_months, iso, parse_date
from cashcli.dates import today as today_fn
from cashcli.errors import CashError
from cashcli.formatting import dumps, pretty
from cashcli.migrations import LATEST_VERSION
from cashcli.models import Compounding, DayCount, EventType, Flow, Kind, PaymentMode, Weekend
from cashcli.money import cents_to_str, parse_amount, parse_rate, rate_to_str
from cashcli.queries.compare import compare
from cashcli.queries.debt_schedule import debt_schedule
from cashcli.queries.project import project
from cashcli.queries.summary import summary
from cashcli.scenario import build_effective_model, describe, load_scenario
from cashcli.select import select
from cashcli.shortcuts import add_shortcut_flags, merge_scenarios, scenario_from_flags


class UsageError(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):  # JSON usage errors instead of argparse's text + exit 2
        raise UsageError(f"{self.prog}: {message}")


# ---- serialization helpers ----------------------------------------------------------------


def flow_json(f: Flow) -> dict:
    d = {
        "id": f.id,
        "name": f.name,
        "kind": str(f.kind),
        "amount": cents_to_str(f.amount_cents),
        "rrule": f.rrule,
        "dtstart": iso(f.dtstart),
        "until": iso(f.until) if f.until else None,
        "active": f.active,
        "tags": list(f.tags),
        "weekend": str(f.weekend),
        "notes": f.notes,
        "debt": debt_json(f) if f.debt else None,
    }
    return d


def debt_json(f: Flow) -> dict:
    d = f.debt
    assert d is not None
    return {
        "balance": cents_to_str(d.balance_cents),
        "balance_as_of": iso(d.balance_as_of),
        "annual_rate": rate_to_str(d.annual_rate),
        "compounding": str(d.compounding),
        "day_count": str(d.day_count),
        "capitalize_interest": d.capitalize_interest,
        "payment_mode": str(d.payment_mode),
        "payment_pct": rate_to_str(d.payment_pct) if d.payment_pct is not None else None,
        "original_principal": (
            cents_to_str(d.original_principal_cents)
            if d.original_principal_cents is not None
            else None
        ),
        "posting_day": d.posting_day,
        "events": [event_json(e) for e in d.events],
    }


def event_json(e) -> dict:
    return {
        "id": e.id,
        "flow_id": e.flow_id,
        "date": iso(e.date),
        "type": str(e.type),
        "rate": rate_to_str(e.rate) if e.rate is not None else None,
        "amount": cents_to_str(e.amount_cents) if e.amount_cents is not None else None,
        "notes": e.notes,
    }


# ---- shared argument groups ---------------------------------------------------------------


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--db",
        default=argparse.SUPPRESS,
        help="sqlite file (default: $CASHCLI_DB or ~/Documents/Backups/cashcli/budget.sqlite)",
    )
    p.add_argument(
        "--pretty",
        action="store_true",
        default=argparse.SUPPRESS,
        help="human-readable output instead of JSON",
    )
    p.add_argument(
        "--no-cleanup",
        action="store_true",
        default=argparse.SUPPRESS,
        help="skip the automatic prior-month cleanup",
    )
    p.add_argument(
        "--select",
        default=argparse.SUPPRESS,
        metavar="PATHS",
        help="only output these comma-separated dotted paths of data, "
        "e.g. spare_balance,spare.committed_total,series[-1].balance",
    )
    p.add_argument(
        "--compact",
        action="store_true",
        default=argparse.SUPPRESS,
        help="single-line JSON",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        default=argparse.SUPPRESS,
        help="include bulky sections (flows_used, per-debt detail, full scenario spec, "
        "lifestyle ledger rows)",
    )


def _window(p: argparse.ArgumentParser, default_months: int = 12) -> None:
    p.add_argument("--as-of", metavar="DATE", help="projection start (default: today)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--until", metavar="DATE", help="projection end, inclusive")
    g.add_argument(
        "--months",
        type=int,
        metavar="N",
        help=f"horizon in months from as-of (default {default_months})",
    )
    p.set_defaults(default_months=default_months)


def _weekly_spend(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--weekly-spend",
        default=None,
        metavar="A",
        help="variable lifestyle spending (groceries, incidentals) per week, prorated per day "
        "after as-of and included in totals, the ledger and spare balances (default 0)",
    )


def _scenario(p: argparse.ArgumentParser) -> None:
    g = p.add_mutually_exclusive_group()
    g.add_argument(
        "--scenario", metavar="FILE", help="scenario JSON file, or - for stdin (see `cash schema`)"
    )
    g.add_argument("--scenario-json", metavar="JSON", help="inline scenario JSON")
    add_shortcut_flags(p)


def _weekly_cents(conn, args) -> int:
    """--weekly-spend flag, else the stored config default, else 0."""
    if getattr(args, "weekly_spend", None) is not None:
        return parse_amount(args.weekly_spend)
    stored = repo.config_get(conn, "weekly_spend")
    return parse_amount(stored) if stored else 0


def _scenario_spec(args) -> dict | None:
    loaded = load_scenario(getattr(args, "scenario", None), getattr(args, "scenario_json", None))
    return merge_scenarios(loaded, scenario_from_flags(args))


def _resolve_window(args, today: date) -> tuple[date, date]:
    as_of = parse_date(args.as_of) if args.as_of else today
    if args.until:
        until = parse_date(args.until)
    else:
        until = add_months(as_of, args.months if args.months is not None else args.default_months)
    if until < as_of:
        raise CashError("--until must not be before --as-of", "usage")
    return as_of, until


def _model(conn, args, as_of: date, *, include_inactive: bool = False, scenario=None):
    if scenario is None:
        scenario = _scenario_spec(args)
    flows = repo.list_flows(conn, include_inactive=True)
    return build_effective_model(flows, scenario, as_of, include_inactive=include_inactive)


# ---- parser -------------------------------------------------------------------------------


def build_parser() -> Parser:
    root = Parser(
        prog="cash",
        description=(
            "Local personal-budget calculator with JSON output. "
            "Run `cash schema` for the full reference."
        ),
    )
    root.add_argument("--db", default=None)
    root.add_argument("--pretty", action="store_true", default=False)
    root.add_argument("--no-cleanup", action="store_true", default=False)
    root.add_argument("--select", default=None)
    root.add_argument("--compact", action="store_true", default=False)
    root.add_argument("--verbose", action="store_true", default=False)
    root.add_argument("--version", action="version", version=f"cash {__version__}")
    sub = root.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    def cmd(name, help_, **kw):
        p = sub.add_parser(name, help=help_, description=help_, **kw)
        _common(p)
        return p

    p = cmd("init", "create the database file (and parent directory)")
    p.add_argument("--force", action="store_true", help="delete and recreate an existing database")

    cmd("schema", "print the full usage reference (schema, commands, scenario format, examples)")
    p = cmd("config", "stored defaults (e.g. weekly_spend)")
    cs = p.add_subparsers(dest="sub", metavar="ACTION")
    cs.required = True
    q = cs.add_parser("set", help="set a default")
    _common(q)
    q.add_argument("key", choices=sorted(repo.CONFIG_KEYS))
    q.add_argument("value")
    q = cs.add_parser("get", help="get a default")
    _common(q)
    q.add_argument("key")
    q = cs.add_parser("unset", help="remove a default")
    _common(q)
    q.add_argument("key")
    q = cs.add_parser("list", help="list defaults")
    _common(q)

    cmd(
        "cleanup",
        "remove or roll forward data that only concerns months before the current one "
        "(also runs automatically before every command)",
    )
    p = cmd("help", "print help for every command")
    p.add_argument("--all", action="store_true", help="(default) print every command's help")

    # flow
    p = cmd("flow", "manage incomes and expenses")
    fs = p.add_subparsers(dest="sub", metavar="ACTION")
    fs.required = True

    def fcmd(name, help_):
        q = fs.add_parser(name, help=help_, description=help_)
        _common(q)
        return q

    q = fcmd("add", "add an income or expense")
    q.add_argument("--name", required=True)
    q.add_argument("--kind", required=True, choices=[k.value for k in Kind])
    q.add_argument("--amount", required=True, help="positive amount, e.g. 386.66 or $1,200")
    q.add_argument(
        "--rrule", help="RFC 5545 rule body, e.g. FREQ=MONTHLY;BYMONTHDAY=1 (omit for a one-off)"
    )
    q.add_argument(
        "--dtstart", required=True, metavar="DATE", help="first date (or the one-off date)"
    )
    q.add_argument("--until", metavar="DATE", help="last possible date, inclusive")
    q.add_argument("--tag", action="append", default=[], metavar="TAG", help="repeatable")
    q.add_argument("--notes")
    q.add_argument("--inactive", action="store_true")
    g = q.add_mutually_exclusive_group()
    g.add_argument(
        "--weekend",
        choices=[w.value for w in Weekend],
        default="none",
        help="if a date falls on Sat/Sun: none (keep), next (following Monday), "
        "previous (preceding Friday)",
    )
    g.add_argument(
        "--ach",
        action="store_true",
        help="shorthand for --weekend next (ACH-pulled on the next business day)",
    )

    q = fcmd("list", "list flows")
    q.add_argument("--kind", choices=[k.value for k in Kind])
    q.add_argument("--tag")
    q.add_argument("--include-inactive", action="store_true")

    q = fcmd("show", "show one flow (id or name)")
    q.add_argument("flow")

    q = fcmd("update", "update fields of a flow")
    q.add_argument("flow")
    q.add_argument("--name")
    q.add_argument("--kind", choices=[k.value for k in Kind])
    q.add_argument("--amount")
    g = q.add_mutually_exclusive_group()
    g.add_argument("--rrule")
    g.add_argument(
        "--one-off", action="store_true", help="clear the rrule (occurs once on dtstart)"
    )
    q.add_argument("--dtstart", metavar="DATE")
    g = q.add_mutually_exclusive_group()
    g.add_argument("--until", metavar="DATE")
    g.add_argument("--no-until", action="store_true")
    g = q.add_mutually_exclusive_group()
    g.add_argument("--active", action="store_true")
    g.add_argument("--inactive", action="store_true")
    q.add_argument("--notes")
    g = q.add_mutually_exclusive_group()
    g.add_argument("--weekend", choices=[w.value for w in Weekend])
    g.add_argument("--ach", action="store_true", help="shorthand for --weekend next")
    q.add_argument("--add-tag", action="append", default=[], metavar="TAG")
    q.add_argument("--remove-tag", action="append", default=[], metavar="TAG")
    q.add_argument(
        "--set-tags", nargs="*", metavar="TAG", help="replace all tags (pass none to clear)"
    )

    q = fcmd("remove", "delete a flow (cascades its debt record, events, and tag links)")
    q.add_argument("flow")

    # tag
    p = cmd("tag", "manage tags")
    ts = p.add_subparsers(dest="sub", metavar="ACTION")
    ts.required = True
    q = ts.add_parser("list", help="list tags with flow counts")
    _common(q)
    q = ts.add_parser("rename", help="rename a tag everywhere")
    _common(q)
    q.add_argument("old")
    q.add_argument("new")
    q = ts.add_parser("remove", help="remove a tag from every flow")
    _common(q)
    q.add_argument("name")

    # debt
    p = cmd("debt", "manage and analyse debts (a debt attaches to an expense flow)")
    ds = p.add_subparsers(dest="sub", metavar="ACTION")
    ds.required = True

    def dcmd(name, help_):
        q = ds.add_parser(name, help=help_, description=help_)
        _common(q)
        return q

    q = dcmd("set", "create or replace the debt record on an expense flow")
    q.add_argument("flow")
    q.add_argument("--balance", required=True, help="balance owed right after balance-as-of")
    q.add_argument("--balance-as-of", required=True, metavar="DATE")
    q.add_argument("--rate", required=True, help="annual nominal rate, e.g. 0.06 or 6%%")
    q.add_argument("--compounding", required=True, choices=[c.value for c in Compounding])
    q.add_argument("--day-count", choices=[c.value for c in DayCount], default="actual/365")
    g = q.add_mutually_exclusive_group()
    g.add_argument(
        "--capitalize",
        dest="capitalize",
        action="store_true",
        default=None,
        help="unpaid interest is added to principal (default for daily/monthly/continuous)",
    )
    g.add_argument(
        "--no-capitalize",
        dest="capitalize",
        action="store_false",
        help="unpaid interest accrues separately, never compounds",
    )
    q.add_argument("--payment-mode", choices=[m.value for m in PaymentMode], default="fixed")
    q.add_argument("--payment-pct", help="with percent_of_balance: fraction of balance, e.g. 0.02")
    q.add_argument("--original-principal")
    q.add_argument(
        "--posting-day",
        type=int,
        metavar="1-31",
        help="monthly compounding: day of month interest posts (default: balance-as-of day; "
        "clamped in short months; unaffected by the monthly roll-forward)",
    )

    q = dcmd("show", "show the debt record and events")
    q.add_argument("flow")
    q = dcmd("unset", "remove the debt record (the flow stays as a plain expense)")
    q.add_argument("flow")

    q = dcmd("events", "manage dated debt events")
    es = q.add_subparsers(dest="sub2", metavar="ACTION")
    es.required = True
    e = es.add_parser("add", help="add an event")
    _common(e)
    e.add_argument("flow")
    e.add_argument("--type", required=True, choices=[t.value for t in EventType])
    e.add_argument("--date", required=True)
    e.add_argument("--rate", help="for rate_change")
    e.add_argument(
        "--amount", help="for balance_adjustment (signed), extra_payment, payment_change"
    )
    e.add_argument("--notes")
    e = es.add_parser("list", help="list events")
    _common(e)
    e.add_argument("flow")
    e = es.add_parser("remove", help="remove an event by id")
    _common(e)
    e.add_argument("event_id", type=int)

    q = dcmd("schedule", "amortization schedule from as-of until payoff")
    q.add_argument("flow")
    _window(q, default_months=600)
    _scenario(q)
    q.add_argument("--max-rows", type=int, metavar="N", help="cap the number of schedule rows")
    q.add_argument(
        "--solve-payment",
        type=int,
        metavar="MONTHS",
        help="also compute the level monthly payment that pays off in MONTHS",
    )

    # queries
    p = cmd("project", "cash balance over a horizon given a starting balance")
    p.add_argument("--starting-balance", default="0", help="cash on hand at as-of (default 0)")
    _window(p)
    p.add_argument("--granularity", choices=["daily", "monthly"], default="monthly")
    _weekly_spend(p)
    p.add_argument("--ledger", action="store_true", help="include every transaction")
    p.add_argument(
        "--no-spare",
        action="store_true",
        help="skip the spare-balance calculation (balance minus expenses due before the next "
        "income); by default spare_balance is computed for the end date and every series row",
    )
    _scenario(p)

    p = cmd("summary", "monthly / annual equivalents by flow and tag")
    p.add_argument("--as-of", metavar="DATE")
    p.add_argument("--mode", choices=["steady", "actual"], default="steady")
    p.add_argument("--months", type=int, default=12, help="window for --mode actual")
    p.add_argument("--by", choices=["tag", "flow", "both"], default="both")
    p.add_argument("--tag", help="only flows carrying this tag")
    p.add_argument("--include-inactive", action="store_true")
    _scenario(p)

    p = cmd("compare", "run two scenarios side by side and find the breakeven")
    p.add_argument(
        "--baseline",
        metavar="FILE",
        help="scenario JSON for side A (default: the stored budget as-is)",
    )
    p.add_argument("--scenario", metavar="FILE", help="scenario JSON for side B (or - for stdin)")
    p.add_argument("--scenario-json", metavar="JSON")
    add_shortcut_flags(p)
    p.add_argument("--starting-balance", default="0")
    _window(p)
    p.add_argument("--granularity", choices=["daily", "monthly"], default="monthly")
    _weekly_spend(p)

    p = cmd("breakeven", "when does a scenario's cash position catch up with the baseline?")
    p.add_argument("--baseline", metavar="FILE")
    p.add_argument("--scenario", metavar="FILE")
    p.add_argument("--scenario-json", metavar="JSON")
    add_shortcut_flags(p)
    _window(p, default_months=120)
    _weekly_spend(p)

    p = cmd("export", "dump the whole budget as JSON")
    p.add_argument("-o", "--output", metavar="FILE")
    p = cmd("import", "load a JSON export")
    p.add_argument("file")
    p.add_argument(
        "--replace",
        action="store_true",
        help="wipe existing data first (required if the db is not empty)",
    )
    p = cmd("sql", "run a read-only SQL query")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=1000)
    return root


# ---- handlers -----------------------------------------------------------------------------


def h_init(args, path: Path):
    if path.exists():
        if not args.force:
            raise CashError(f"{path} already exists (use --force to recreate)", "db_exists")
        path.unlink()
    conn = db.connect(path, create=True)
    conn.close()
    return {"db": str(path), "schema_version": LATEST_VERSION}, []


def h_schema(args, conn):
    text = (resources.files("cashcli") / "reference.md").read_text()
    return {"reference": text, "format": "markdown"}, []


def h_help(args, conn, parser):
    chunks = [parser.format_help()]

    def walk(p: argparse.ArgumentParser):
        for action in p._actions:
            if isinstance(action, argparse._SubParsersAction):
                for sp in action.choices.values():
                    chunks.append(f"\n===== {sp.prog} =====\n{sp.format_help()}")
                    walk(sp)

    walk(parser)
    return {"help": "\n".join(chunks)}, []


def h_flow(args, conn):
    a = args.sub
    if a == "add":
        f = repo.add_flow(
            conn,
            name=args.name,
            kind=Kind(args.kind),
            amount_cents=parse_amount(args.amount),
            rrule=args.rrule,
            dtstart=parse_date(args.dtstart),
            until=parse_date(args.until) if args.until else None,
            tags=args.tag,
            notes=args.notes,
            active=not args.inactive,
            weekend=Weekend.NEXT if args.ach else Weekend(args.weekend),
        )
        return flow_json(f), []
    if a == "list":
        flows = repo.list_flows(
            conn,
            kind=Kind(args.kind) if args.kind else None,
            tag=args.tag,
            include_inactive=args.include_inactive,
        )
        return {"flows": [flow_json(f) for f in flows], "count": len(flows)}, []
    if a == "show":
        return flow_json(repo.resolve_flow(conn, args.flow)), []
    if a == "update":
        f = repo.resolve_flow(conn, args.flow)
        kw = {}
        if args.name is not None:
            kw["name"] = args.name
        if args.kind is not None:
            kw["kind"] = Kind(args.kind)
        if args.amount is not None:
            kw["amount_cents"] = parse_amount(args.amount)
        if args.rrule is not None:
            kw["rrule"] = args.rrule
        if args.one_off:
            kw["rrule"] = None
        if args.dtstart is not None:
            kw["dtstart"] = parse_date(args.dtstart)
        if args.until is not None:
            kw["until"] = parse_date(args.until)
        if args.no_until:
            kw["until"] = None
        if args.active:
            kw["active"] = True
        if args.inactive:
            kw["active"] = False
        if args.notes is not None:
            kw["notes"] = args.notes
        if args.ach:
            kw["weekend"] = Weekend.NEXT
        elif args.weekend is not None:
            kw["weekend"] = Weekend(args.weekend)
        conn.execute("BEGIN")
        try:
            f = repo.update_flow(conn, int(f.id), **kw)
            if args.set_tags is not None:
                repo.set_flow_tags(conn, int(f.id), args.set_tags)
            if args.add_tag:
                repo.add_flow_tags(conn, int(f.id), args.add_tag)
            if args.remove_tag:
                repo.remove_flow_tags(conn, int(f.id), args.remove_tag)
            repo.prune_unused_tags(conn)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        return flow_json(repo.get_flow(conn, int(f.id))), []
    if a == "remove":
        f = repo.resolve_flow(conn, args.flow)
        repo.remove_flow(conn, int(f.id))
        return {"removed": flow_json(f)}, []
    raise UsageError(f"unknown flow action {a}")


def h_tag(args, conn):
    if args.sub == "list":
        tags = repo.list_tags(conn)
        return {"tags": [{"id": t.id, "name": t.name, "flows": t.flow_count} for t in tags]}, []
    if args.sub == "rename":
        repo.rename_tag(conn, args.old, args.new)
        return {
            "renamed": {"from": repo.normalize_tag(args.old), "to": repo.normalize_tag(args.new)}
        }, []
    if args.sub == "remove":
        repo.remove_tag(conn, args.name)
        return {"removed": repo.normalize_tag(args.name)}, []
    raise UsageError(f"unknown tag action {args.sub}")


def h_debt(args, conn, today: date):
    a = args.sub
    if a == "set":
        f = repo.resolve_flow(conn, args.flow)
        repo.set_debt(
            conn,
            int(f.id),
            balance_cents=parse_amount(args.balance),
            balance_as_of=parse_date(args.balance_as_of),
            annual_rate=parse_rate(args.rate),
            compounding=Compounding(args.compounding),
            day_count=DayCount(args.day_count),
            capitalize_interest=args.capitalize,
            payment_mode=PaymentMode(args.payment_mode),
            payment_pct=parse_rate(args.payment_pct) if args.payment_pct else None,
            original_principal_cents=(
                parse_amount(args.original_principal) if args.original_principal else None
            ),
            posting_day=args.posting_day,
        )
        return flow_json(repo.get_flow(conn, int(f.id))), []
    if a == "show":
        f = repo.resolve_flow(conn, args.flow)
        if f.debt is None:
            raise CashError(f"flow {f.name!r} has no debt record", "no_debt")
        return flow_json(f), []
    if a == "unset":
        f = repo.resolve_flow(conn, args.flow)
        repo.unset_debt(conn, int(f.id))
        return flow_json(repo.get_flow(conn, int(f.id))), []
    if a == "events":
        b = args.sub2
        if b == "add":
            f = repo.resolve_flow(conn, args.flow)
            ev = repo.add_event(
                conn,
                int(f.id),
                type=EventType(args.type),
                date=parse_date(args.date),
                rate=parse_rate(args.rate) if args.rate is not None else None,
                amount_cents=(
                    parse_amount(args.amount, allow_negative=True)
                    if args.amount is not None
                    else None
                ),
                notes=args.notes,
            )
            return event_json(ev), []
        if b == "list":
            f = repo.resolve_flow(conn, args.flow)
            if f.debt is None:
                raise CashError(f"flow {f.name!r} has no debt record", "no_debt")
            return {
                "flow": f.id,
                "name": f.name,
                "events": [event_json(e) for e in f.debt.events],
            }, []
        if b == "remove":
            repo.remove_event(conn, args.event_id)
            return {"removed": args.event_id}, []
    if a == "schedule":
        f = repo.resolve_flow(conn, args.flow)
        as_of, until = _resolve_window(args, today)
        model = _model(conn, args, as_of, include_inactive=True)
        data, warnings = debt_schedule(
            model,
            f.id,
            as_of=as_of,
            until=until,
            solve_payment_months=args.solve_payment,
            max_rows=args.max_rows,
        )
        _attach_scenario(data, model, args)
        return data, warnings
    raise UsageError(f"unknown debt action {a}")


def _attach_scenario(data: dict, model, args) -> None:
    if getattr(args, "verbose", False):
        data["scenario"] = describe(model.scenario)
    else:
        data["scenario"] = (model.scenario or {}).get("name") if model.scenario else None
    data["scenario_applied"] = model.applied


def h_project(args, conn, today: date):
    as_of, until = _resolve_window(args, today)
    model = _model(conn, args, as_of)
    data, warnings = project(
        model,
        as_of=as_of,
        until=until,
        starting_balance_cents=parse_amount(args.starting_balance, allow_negative=True),
        granularity=args.granularity,
        include_ledger=args.ledger,
        include_spare=not args.no_spare,
        weekly_spend_cents=_weekly_cents(conn, args),
        verbose=getattr(args, "verbose", False),
    )
    _attach_scenario(data, model, args)
    return data, warnings


def h_summary(args, conn, today: date):
    as_of = parse_date(args.as_of) if args.as_of else today
    if args.months <= 0:
        raise CashError("--months must be positive", "usage")
    model = _model(conn, args, as_of, include_inactive=args.include_inactive)
    data, warnings = summary(
        model, as_of=as_of, mode=args.mode, months=args.months, by=args.by, tag_filter=args.tag
    )
    _attach_scenario(data, model, args)
    return data, warnings


def h_compare(args, conn, today: date, *, breakeven_only: bool):
    as_of, until = _resolve_window(args, today)
    base_spec = load_scenario(args.baseline, None) if args.baseline else None
    scen_spec = _scenario_spec(args)
    if scen_spec is None:
        raise CashError(
            "a scenario is required: --scenario FILE, --scenario-json JSON, or shortcut flags "
            "such as --disable-tag / --payoff / --extra-payment",
            "usage",
        )
    base = (
        _model(conn, args, as_of, scenario=base_spec)
        if base_spec
        else _model(conn, argparse.Namespace(scenario=None, scenario_json=None), as_of)
    )
    scen = _model(conn, args, as_of, scenario=scen_spec)
    labels = (
        (base_spec or {}).get("name") or "baseline",
        (scen_spec or {}).get("name") or "scenario",
    )
    data, warnings = compare(
        base,
        scen,
        as_of=as_of,
        until=until,
        starting_balance_cents=(
            0 if breakeven_only else parse_amount(args.starting_balance, allow_negative=True)
        ),
        granularity="monthly" if breakeven_only else args.granularity,
        include_series=not breakeven_only,
        labels=labels,
        weekly_spend_cents=_weekly_cents(conn, args),
        verbose=getattr(args, "verbose", False),
    )
    if getattr(args, "verbose", False):
        data["baseline_scenario"] = describe(base_spec)
        data["scenario"] = describe(scen_spec)
    else:
        data["scenario"] = scen_spec.get("name")
    data["scenario_applied"] = scen.applied
    if base.applied:
        data["baseline_applied"] = base.applied
    warnings = (
        [f"[baseline] {w}" for w in base.warnings]
        + [f"[scenario] {w}" for w in scen.warnings]
        + warnings
    )
    return data, warnings


def h_config(args, conn):
    if args.sub == "set":
        if args.key == "weekly_spend":
            parse_amount(args.value)  # validate
        repo.config_set(conn, args.key, args.value)
        return {"config": repo.config_all(conn)}, []
    if args.sub == "get":
        return {"key": args.key, "value": repo.config_get(conn, args.key)}, []
    if args.sub == "unset":
        repo.config_unset(conn, args.key)
        return {"config": repo.config_all(conn)}, []
    return {"config": repo.config_all(conn), "keys": repo.CONFIG_KEYS}, []


def h_export(args, conn):
    payload = repo.export_all(conn, db.current_version(conn))
    payload["exported_at"] = today_fn().isoformat()
    if args.output:
        Path(args.output).expanduser().write_text(dumps(payload) + "\n")
        return {"written": args.output, "flows": len(payload["flows"])}, []
    return payload, []


def h_import(args, conn):
    p = Path(args.file).expanduser()
    if not p.exists():
        raise CashError(f"{args.file} not found", "file_not_found")
    try:
        payload = json.loads(p.read_text())
    except json.JSONDecodeError as exc:
        raise CashError(f"{args.file} is not valid JSON: {exc}", "invalid_import") from exc
    n = repo.import_all(conn, payload, replace=args.replace)
    return {"imported_flows": n}, []


_READONLY_FIRST = {"SELECT", "WITH", "EXPLAIN", "PRAGMA"}


def h_sql(args, path: Path):
    q = args.query.strip()
    first = q.split(None, 1)[0].upper().rstrip("(") if q else ""
    if first not in _READONLY_FIRST:
        raise CashError(
            "only read-only statements are allowed (SELECT / WITH / EXPLAIN / PRAGMA); "
            "use the flow/debt commands to modify data",
            "readonly_sql",
        )
    conn = db.readonly_connect(path)
    try:
        cur = conn.execute(q)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchmany(args.limit + 1)
    except sqlite3.Error as exc:
        raise CashError(f"sql error: {exc}", "sql_error") from exc
    finally:
        conn.close()
    truncated = len(rows) > args.limit
    rows = rows[: args.limit]
    return {
        "columns": cols,
        "rows": [dict(zip(cols, r, strict=True)) for r in rows],
        "row_count": len(rows),
        "truncated": truncated,
    }, []


# ---- main ---------------------------------------------------------------------------------


def _emit(envelope: dict, pretty_mode: bool, *, compact: bool = False) -> None:
    if pretty_mode:
        if envelope["ok"]:
            data = envelope["data"]
            if isinstance(data, dict) and set(data) <= {"reference", "format", "help"}:
                print(data.get("reference") or data.get("help"))
            else:
                print(pretty(data))
            for w in envelope.get("warnings") or []:
                print(f"warning: {w}")
            for a in envelope.get("cleanup") or []:
                print(f"cleanup: {a}")
        else:
            print(f"error [{envelope['error']['code']}]: {envelope['error']['message']}")
    else:
        print(dumps(envelope, indent=None if compact else 2))


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    command = "?"
    pretty_mode = "--pretty" in argv
    try:
        args = parser.parse_args(argv)
        command = args.command + (f" {args.sub}" if getattr(args, "sub", None) else "")
        if getattr(args, "sub2", None):
            command += f" {args.sub2}"
        pretty_mode = bool(getattr(args, "pretty", False))
        path = db.resolve_db_path(getattr(args, "db", None))
        today = today_fn()
        cleanup_actions: list[str] = []
        if args.command == "init":
            data, warnings = h_init(args, path)
        elif args.command == "sql":
            data, warnings = h_sql(args, path)
        elif args.command == "help":
            data, warnings = h_help(args, None, parser)
        elif args.command == "schema":
            data, warnings = h_schema(args, None)
        else:
            conn = db.connect(path)
            try:
                if not getattr(args, "no_cleanup", False):
                    cleanup_actions = run_cleanup(conn, today)
                if args.command == "cleanup":
                    data, warnings = (
                        {"month": today.replace(day=1).isoformat(), "actions": cleanup_actions},
                        [],
                    )
                elif args.command == "flow":
                    data, warnings = h_flow(args, conn)
                elif args.command == "config":
                    data, warnings = h_config(args, conn)
                elif args.command == "tag":
                    data, warnings = h_tag(args, conn)
                elif args.command == "debt":
                    data, warnings = h_debt(args, conn, today)
                elif args.command == "project":
                    data, warnings = h_project(args, conn, today)
                elif args.command == "summary":
                    data, warnings = h_summary(args, conn, today)
                elif args.command == "compare":
                    data, warnings = h_compare(args, conn, today, breakeven_only=False)
                elif args.command == "breakeven":
                    data, warnings = h_compare(args, conn, today, breakeven_only=True)
                elif args.command == "export":
                    data, warnings = h_export(args, conn)
                elif args.command == "import":
                    data, warnings = h_import(args, conn)
                else:  # pragma: no cover
                    raise UsageError(f"unknown command {args.command}")
            finally:
                conn.close()
        if getattr(args, "select", None):
            data = select(data, args.select)
        envelope = {"ok": True, "command": command, "data": data, "warnings": warnings}
        if cleanup_actions and args.command != "cleanup":
            envelope["cleanup"] = cleanup_actions
        _emit(envelope, pretty_mode, compact=bool(getattr(args, "compact", False)))
        return 0
    except UsageError as exc:
        _emit(
            {"ok": False, "command": command, "error": {"code": "usage", "message": str(exc)}},
            pretty_mode,
        )
        return 2
    except CashError as exc:
        _emit(
            {"ok": False, "command": command, "error": {"code": exc.code, "message": exc.message}},
            pretty_mode,
        )
        return 2 if exc.code == "usage" else 1
    except sqlite3.IntegrityError as exc:
        _emit(
            {
                "ok": False,
                "command": command,
                "error": {"code": "integrity", "message": str(exc)},
            },
            pretty_mode,
        )
        return 1
