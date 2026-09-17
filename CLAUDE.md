# cashcli — notes for Claude

This repo is a Python CLI (`cash`) that stores a personal budget in one sqlite file and answers
cash-flow questions. **You are its primary user.** When the user asks a budget question, use the tool
instead of doing the arithmetic yourself.

## Using the tool
- Run commands with `uv run cash ...` from this directory (or `cash ...` if installed with `uv tool install .`).
- Start by reading the reference: `uv run cash schema` (JSON; the markdown is in `data.reference`).
- The database defaults to `$CASHCLI_DB`, else `~/Documents/Backups/cashcli/budget.sqlite`. Use `--db PATH` for a
  throwaway file. `cash init` creates it.
- Keep outputs small: add `--select a,b.c` to get just the fields you need (e.g.
  `--select spare_balance,spare.committed_total,ending_balance`), and prefer the what-if shortcut
  flags (`--extra-payment "Mini Cooper:15000@2026-11-13"`, `--disable-tag car`, `--payoff`,
  `--add-income`) over hand-written scenario JSON. `--verbose` exists when you need the detail.
- Output is always one JSON envelope on stdout: check `ok`, read `data`, and **always relay `warnings`**
  to the user (negative amortization, debts paid off before as-of, scenario tags that matched nothing…).
- Money values are strings with two decimals. Never store the user's cash balance: pass it with
  `--starting-balance` each time. Rates accept `6%` or `0.06`.
- "How much will I have on DATE" means **spare** money: `project` returns `spare_balance` (balance
  minus the expenses due after that date and before the next income) alongside the raw
  `ending_balance`. Report `spare_balance` by default and say which bills were deducted
  (`data.spare.committed_before_next_income`); give the raw balance only when asked for it.
- Projections should include variable lifestyle spending: `--weekly-spend A` (groceries,
  incidentals, per week, prorated daily), or the stored default set with
  `cash config set weekly_spend A`. If neither exists, ask the user for the figure; 0 is almost
  always too optimistic.
- What-ifs are scenario JSON overlays (`--scenario FILE` / `--scenario-json '{...}'`), never edits to
  the stored budget. Use `breakeven` / `compare` for "should I do X" questions and `project` for
  "how much will I have" questions; `summary --tag T` for "what do I spend on T".
- `cash sql "SELECT ..."` is available for ad-hoc read-only questions about the stored data.
- A debt is an expense flow (the payment) plus a `debt set` record (balance, rate, compounding).
  `--balance` is the balance right after the `--balance-as-of` date's payment.
- ACH-pulled items use `--ach` (weekend dates move to the following Monday); `--weekend previous`
  for items that pull on the preceding Friday.
- Prior-month data is irrelevant to the user and is cleaned up automatically before every command
  (one-offs and ended flows removed, debts rolled forward to the end of last month, paid-off debts
  removed). Relay the envelope's `cleanup` list when present. `--no-cleanup` skips it;
  `CASHCLI_TODAY=YYYY-MM-DD` pins "today" for reproducible runs.

## Developing
- `uv run pytest` must stay green; amortization tests assert exact cents against hand-verified tables.
- `uv run ruff check . && uv run ruff format --check .` before finishing.
- No floats in money paths: integer cents in the DB, `Decimal` in the engine, rounding only at cash
  movements and at output.
- The engine (`src/cashcli/engine.py`) and debt math (`src/cashcli/debt.py`) never touch sqlite;
  keep them pure so they stay unit-testable.
