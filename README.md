# cashcli

A local personal-budget calculator with a JSON command-line interface, built to be driven by LLM
agents (Claude and friends) that answer questions like *"if I have $3,000 now, how much will I have in
six months?"*, *"what do I spend on the car per month?"* or *"if I sell the car and prepay the loan,
when do I break even?"*.

- Incomes and expenses ("flows") with names, amounts, tags and RFC 5545 recurrence rules
  (`FREQ=WEEKLY;INTERVAL=2`, `FREQ=YEARLY;BYMONTH=11;BYDAY=3TU`, …).
- Debts attached to expense flows: balance, APR, simple/daily/monthly/continuous compounding,
  actual/365, actual/360 or 30/360 day counts, interest capitalization on/off, dated rate changes,
  balance adjustments, extra payments, payment changes and payoffs; full amortization schedules.
- A daily simulation engine that projects cash, plus scenario overlays (JSON what-ifs or shortcut
  flags such as `--settle`, `--stop-tag`, `--add-expense`), breakeven analysis between scenarios, and
  `cash earliest`: the first date a `?`-dated what-if keeps the balance above a floor, and
  `cash plan`: debt payoff plans (avalanche / snowball, with rollover) for an extra amount per month.
- Everything lives in one sqlite file. No server, no auth, no floats (exact decimals; cents only
  where cash actually moves).

## Install

```bash
brew install uv            # https://docs.astral.sh/uv/
uv sync                    # creates .venv with python-dateutil, pytest, ruff
uv run cash init           # creates the database at the default location (see below)
```

### Database location

The budget lives at `~/.config/cashcli/budget.sqlite` by default (`$XDG_CONFIG_HOME/cashcli/budget.sqlite`
if that variable is set). Override it with `$CASHCLI_DB`, or per invocation with `--db PATH`.

`uv tool install .` puts a `cash` binary on your PATH if you prefer not to prefix with `uv run`.

## Quick start

```bash
uv run cash flow add --name Salary --kind income --amount 2500 --rrule "FREQ=WEEKLY;INTERVAL=2" --dtstart 2026-09-18 --tag job
uv run cash flow add --name Rent --kind expense --amount 3000 --rrule "FREQ=MONTHLY;BYMONTHDAY=1" --dtstart 2026-10-01 --tag housing
uv run cash flow add --name "Car loan" --kind expense --amount 386.66 --rrule "FREQ=MONTHLY;BYMONTHDAY=1" --dtstart 2026-11-01 --tag car
uv run cash debt set "Car loan" --balance 20000 --balance-as-of 2026-10-01 --rate 6% --compounding monthly
uv run cash flow add --name "Car insurance" --kind expense --amount 120 --rrule "FREQ=MONTHLY;BYMONTHDAY=15" --dtstart 2026-10-15 --tag car

uv run cash project --starting-balance 3000 --months 6         # balance in 6 months, min/max, series
uv run cash summary --tag car                                   # monthly/annual car spend
uv run cash debt schedule "Car loan"                            # amortization table, payoff date
uv run cash breakeven --scenario sell-car.json                  # see `cash schema` for the JSON format
uv run cash earliest --floor 5000 --starting-balance 3500 \
  --settle "Car loan:29500@?" --add-expense "Flight:550@?" --stop-tag "car@?"   # first date that keeps the floor
uv run cash plan --extra 500 --strategy snowball                 # debt-free date with an extra $500/month
uv run cash --pretty project --starting-balance 3000            # human-readable rendering
```

Run `uv run cash schema` for the complete reference (commands, scenario format, recurrence
cheat-sheet, schema, worked examples). That document is what an agent should read first.

## Development

```bash
uv run pytest          # ~70 tests incl. amortization tables verified to the cent
uv run ruff check .    # lint
uv run ruff format .   # format
```

Layout: `src/cashcli/` — `cli.py` (argparse + JSON envelope), `repo.py` (sqlite CRUD),
`recurrence.py` (dateutil rrule), `debt.py` (interest math), `engine.py` (daily simulation),
`scenario.py` (what-if overlay), `queries/` (project / summary / debt_schedule / compare),
`reference.md` (the `cash schema` document).
