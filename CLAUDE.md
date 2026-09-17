# cashcli — notes for Claude

This repo is a Python CLI (`cash`) that stores a personal budget in one sqlite file and answers
cash-flow questions. **You are its primary user.** When the user asks a budget question, use the tool
instead of doing the arithmetic yourself.

## Using the tool
- Run commands with `uv run cash ...` from this directory (or `cash ...` if installed with `uv tool install .`).
- Start by reading the reference: `uv run cash schema` (JSON; the markdown is in `data.reference`).
- The database defaults to `$CASHCLI_DB`, else
  `~/Documents/70-79 Computer/73 App Data Exports/73.02 cashcli/budget.sqlite`
  (`DEFAULT_PATH` in `src/cashcli/db.py`). Use `--db PATH` for a throwaway file. `cash init` creates it.
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
- "How much will I spend on X between now and DATE?" → `cash tag list` (tags with the flow names
  each covers), then `cash spend TAG --until DATE` → `total`. Terms may be tags or flow names and
  combine (`cash spend car "Bay Ridge" --exclude debt`); no terms = everything. `summary --tag T` is
  for monthly/annual averages, not dated totals.
- What-ifs are scenario JSON overlays (`--scenario FILE` / `--scenario-json '{...}'`), never edits to
  the stored budget. Use `breakeven` / `compare` for "should I do X" questions and `project` for
  "how much will I have" questions.
- "When is the earliest I can do X without dropping below $A?" → `cash earliest --floor A` with the
  what-if dated `?` (`--settle "Loan:29500@?" --add-expense "Flight:550@?" --stop-tag "car@?"`),
  then `project --on DATE` with the same flags for the detail. `--settle` = sell the thing and clear
  its loan with the proceeds; `--stop`/`--stop-tag` = no occurrences after a date.
- "How fast can I pay off my debts with an extra $A/month?" → `cash plan --extra A` (`--strategy
  avalanche|snowball`, `--tag debt`, `--from DATE`; add `--starting-balance` for the cash check).
  Run both strategies when the user asks which is better; `steps` is the payoff sequence.
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
