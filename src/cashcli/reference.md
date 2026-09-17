# cashcli reference

`cash` is a local personal-budget calculator. It stores incomes, expenses and debts in ONE sqlite
file and answers cash-flow questions. It is designed to be driven by an LLM agent from a shell:
every command prints a single JSON object; nothing else goes to stdout.

```
cash [--db PATH] [--pretty] COMMAND [ARGS]        # global flags may also follow the command
```

- `--db PATH` — sqlite file. Default: `$CASHCLI_DB`, else `~/Documents/Backups/cashcli/budget.sqlite`.
- `--pretty` — human-readable text instead of JSON (agents should NOT use it).
- `--no-cleanup` — skip the automatic prior-month cleanup (see below).
- `--select PATHS` — output only these comma-separated dotted paths of `data`, e.g.
  `--select spare_balance,spare.committed_total,series[-1].balance`. **Use this**: it keeps answers
  small. `--compact` prints single-line JSON.
- `--verbose` — include bulky sections (`flows_used`, per-debt detail, the full scenario spec,
  lifestyle rows in the ledger). Off by default.
- `CASHCLI_TODAY=YYYY-MM-DD` — override "today" (default as-of date and cleanup month).
- Envelope: `{"ok": true, "command": "...", "data": {...}, "warnings": [...]}` or
  `{"ok": false, "command": "...", "error": {"code": "...", "message": "..."}}`.
  Exit code 0 = ok, 1 = domain error (e.g. `unknown_flow`), 2 = usage error.
- **Always read `warnings`.** They flag things like negative amortization, a debt paid off
  before the as-of date, or a scenario tag that matched nothing.
- A `cleanup` key appears in the envelope whenever the automatic cleanup changed something.

## Automatic cleanup (prior months are irrelevant)

Before every command that opens the database, `cash` removes data that only concerns months before
the current one, and reports what it did under `cleanup` (or run `cash cleanup` explicitly):

- a one-off flow dated before the 1st of the current month is removed;
- a flow whose last occurrence (`until`, or `COUNT`) is before the current month is removed;
- a debt that is paid off before the current month is removed together with its payment flow;
- a debt whose balance date is before the current month is **rolled forward**: its balance becomes the
  simulated balance at the end of the previous month (scheduled payments and events assumed to have
  happened), `balance_as_of` moves to that date, and events on or before it are dropped;
- tags no longer used by any flow are removed.

## Concepts

| term | meaning |
|---|---|
| flow | an income or an expense: name, positive amount, tags, recurrence (`rrule` + `dtstart` + optional `until`), notes, active flag |
| one-off | a flow with no `rrule`; it happens once on `dtstart` |
| weekend rule | per flow: `none` (occurs on the weekend day), `next` (moves to the following Monday, i.e. ACH-pulled), `previous` (moves to the preceding Friday). `--ach` = `--weekend next` |
| debt | extra record attached to an **expense** flow (the loan payment). Holds balance, rate, compounding, day count, capitalization, payment mode. The flow's amount + rrule is the scheduled payment |
| debt event | dated change on a debt: `rate_change`, `balance_adjustment` (signed), `extra_payment`, `payment_change`, `payoff` |
| scenario | ephemeral JSON what-if overlay passed to a query; never stored |
| starting balance | cash on hand at as-of. Never stored; always a query parameter |
| weekly spend | `--weekly-spend A` on project/compare/breakeven: variable lifestyle spending (groceries, incidentals) per week, prorated per day after as-of, exact to the cent over any span. Included in totals, the ledger (kind `lifestyle`) and spare balances. A scenario may override it with `"weekly_spend"` |
| spare balance | the balance on a date minus every expense that lands after that date and before the next income. **This is the number to report when the user asks "how much will I have on X"**; the raw end-of-day balance is `ending_balance` |

Money: amounts are strings like `"386.66"`, `"1,234"`, `"$1,234.56"`; always positive (the kind gives
the sign). Rates: `"0.06"` or `"6%"`. Dates: `YYYY-MM-DD`. Flows are referenced by numeric id or
unique case-insensitive name. Output money values are strings with two decimals.

Internals never round: balances and interest are exact decimals; only actual cash movements are
whole cents (a payment, the final payoff) and only displayed values are rounded.

## Recurrence (RFC 5545 RRULE, via dateutil)

Pass only the rule body. `DTSTART`/`UNTIL` inside the string are rejected (use `--dtstart`/`--until`);
`COUNT` is allowed. `until` is inclusive. If `dtstart` doesn't match the rule, the first occurrence is
the first matching date after it.

| want | rrule |
|---|---|
| every day | `FREQ=DAILY` |
| every week on the dtstart weekday | `FREQ=WEEKLY` |
| fortnightly | `FREQ=WEEKLY;INTERVAL=2` |
| every Monday and Thursday | `FREQ=WEEKLY;BYDAY=MO,TH` |
| monthly on the 1st | `FREQ=MONTHLY;BYMONTHDAY=1` |
| last day of every month | `FREQ=MONTHLY;BYMONTHDAY=-1` |
| 15th and last day | `FREQ=MONTHLY;BYMONTHDAY=15,-1` |
| first Friday each month | `FREQ=MONTHLY;BYDAY=1FR` |
| every 3 months | `FREQ=MONTHLY;INTERVAL=3` |
| yearly on dtstart's month/day | `FREQ=YEARLY` |
| 3rd Tuesday each November | `FREQ=YEARLY;BYMONTH=11;BYDAY=3TU` |
| every 3 years | `FREQ=YEARLY;INTERVAL=3` |
| last day of February (leap-safe) | `FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=-1` |
| 12 monthly payments then stop | `FREQ=MONTHLY;COUNT=12` |

Gotchas: `BYMONTHDAY=31` skips months without a 31st (use `-1` for "last day"); `FREQ=YEARLY`
from Feb 29 only fires in leap years.

Weekend rule: the rrule produces the nominal date; the flow's `weekend` setting then moves Saturday /
Sunday dates to the following Monday (`next`) or the preceding Friday (`previous`). Public holidays
are not modelled.

## Commands

### Setup
```
cash init [--force]                 # create the db (parent dirs too); --force recreates
cash config set weekly_spend 200    # stored defaults; `config get|unset|list`. weekly_spend is the
                                    # default --weekly-spend for project/compare/breakeven
cash schema                         # this document ({"reference": "...markdown..."})
cash help --all                     # argparse help for every command
cash export [-o FILE]               # full JSON backup (stdout by default)
cash import FILE [--replace]        # restore; --replace wipes first (required if db not empty)
cash sql "SELECT ..." [--limit N]   # read-only SQL (SELECT/WITH/EXPLAIN/PRAGMA only)
```

### Flows
```
cash flow add --name N --kind income|expense --amount A --dtstart D
              [--rrule R] [--until D] [--tag T ...] [--notes S] [--inactive]
              [--weekend none|next|previous | --ach]
cash flow list [--kind K] [--tag T] [--include-inactive]
cash flow show FLOW
cash flow update FLOW [--name N] [--amount A] [--rrule R | --one-off] [--dtstart D]
                      [--until D | --no-until] [--active | --inactive] [--notes S]
                      [--weekend W | --ach]
                      [--add-tag T ...] [--remove-tag T ...] [--set-tags [T ...]]
cash cleanup                        # explicit run of the automatic prior-month cleanup
cash flow remove FLOW               # also removes its debt record, events and tag links
cash tag list | rename OLD NEW | remove NAME
```
Inactive flows are ignored by every query unless a scenario re-enables them
(`summary --include-inactive` also shows them).

### Debts
```
cash debt set FLOW --balance A --balance-as-of D --rate R --compounding simple|daily|monthly|continuous
              [--day-count actual/365|actual/360|30/360] [--capitalize | --no-capitalize]
              [--payment-mode fixed|interest_only|percent_of_balance] [--payment-pct P]
              [--original-principal A] [--posting-day 1-31]   # creates or replaces
cash debt show FLOW | cash debt unset FLOW
cash debt events add FLOW --type T --date D [--rate R] [--amount A] [--notes S]
cash debt events list FLOW | cash debt events remove EVENT_ID
cash debt schedule FLOW [--as-of D] [--until D | --months N] [--scenario ...] [--solve-payment MONTHS]
                        [--max-rows N]
```
- `--balance` is what is owed right AFTER anything due on `--balance-as-of`. Best practice: use a
  statement date / payment due date and the post-payment balance.
- Interest: `daily` accrues `P·r/basis` each day; `continuous` accrues `P·(e^(r/basis) − 1)`;
  `monthly` posts `P·r/12` once a month on `posting_day` (default: the balance date's day; clamped
  to month length; set it to the payment due day so interest posts right before the payment);
  `simple` accrues daily but NEVER capitalizes. With `--capitalize` (default for
  daily/monthly/continuous) unpaid interest is added to principal; with `--no-capitalize` it accrues
  in a separate bucket that payments clear first.
- Day count: `actual/365` (default), `actual/360`, `30/360` (every month counts 30 days).
- Payment modes: `fixed` = the flow amount; `interest_only` = exactly the interest since the last
  payment; `percent_of_balance` = `max(flow amount, balance × payment_pct)` (credit-card style).
- Payments are capped at the amount owed; the final payment pays exactly the remaining balance.
  Scheduled payments after payoff are skipped. If a payment is smaller than the period's interest
  you get a `negative amortization` warning.
- Events: `rate_change --rate`, `balance_adjustment --amount` (signed, e.g. `-250`),
  `extra_payment --amount`, `payment_change --amount` (new scheduled payment from that date),
  `payoff` (pays the full balance that day). Same-day order: parameter events → interest →
  scheduled payment → extra/payoff.
- `debt schedule` output: `balance_at_as_of`, `payoff_date`, `payments_remaining`,
  `total_paid_remaining`, `total_interest_remaining`, `rows[{n,date,payment,interest,principal,
  balance,kind}]`. `--solve-payment N` adds the level monthly payment that pays off in N months.

### Queries
```
cash project [--starting-balance A] [--weekly-spend A] [--as-of D] [--until D | --months N]
             [--granularity monthly|daily] [--ledger] [--no-spare] [--scenario FILE|- | --scenario-json JSON]
cash summary [--as-of D] [--mode steady|actual] [--months N] [--by tag|flow|both] [--tag T]
             [--include-inactive] [--scenario ...]
cash compare [--baseline FILE] (--scenario FILE | --scenario-json JSON) [--starting-balance A]
             [--weekly-spend A] [--as-of D] [--until D | --months N] [--granularity ...]
cash breakeven [--baseline FILE] (--scenario FILE | --scenario-json JSON) [--weekly-spend A]
               [--as-of D] [--until D | --months N]
```
- `--as-of` defaults to today; `--months` defaults to 12 (breakeven: 120; schedule: 600).
- **project** → `weekly_spend`, `lifestyle_total` (what the weekly spend added up to in the window),
  `ending_balance` (raw end-of-day cash on `until`), **`spare_balance`** (that
  balance minus the expenses due after `until` and before the next income; the default answer to
  "how much will I have"), `spare{next_income{date,name,amount}, committed_total,
  committed_before_next_income[{date,name,amount}]}`, `min_balance{date,balance}`, `max_balance`,
  `totals{income,expense,net,interest_paid,principal_paid}`, `series[{date,balance,income,expense,net}]`
  (monthly = as-of row + every month end + the until date; `income`/`expense` are the period since the
  previous row; each row also carries its `spare` balance), `debts[{balance_at_as_of,balance_at_until,interest_accrued_in_window,paid_off_on}]`,
  `flows_used[{occurrences,total}]`, `total_debt_at_until`, and `ledger[]` with `--ledger`.
  Balances are end-of-day. A debt whose balance date is before as-of is rolled forward silently
  (payments and interest between the two dates are applied, cash is not tracked before as-of).
- **summary** `steady` (default): each recurring flow contributes `amount × occurrences_per_year / 12`
  per month (occurrences counted over an 84-year window, so fortnightly = 26.095/yr, monthly = 12).
  One-offs are listed under `one_offs`, not counted. `actual`: sums real occurrences in the next
  `--months` months and divides by that. Output: `net{income_monthly,expense_monthly,net_monthly,
  *_annual}`, `by_flow[]`, `by_tag[]` (a flow with several tags counts under each), `untagged`.
  Debt flows contribute their scheduled payment (cash view).
- **compare** runs A (stored budget, or `--baseline FILE` scenario) and B (`--scenario`) and returns
  `a`, `b` (each with `ending_balance`, `min_balance`, `series`), `difference{ending, series[{date,a,b,diff}]}`
  and `breakeven`. **breakeven** is the same without series (default horizon 120 months).
  `breakeven.status`: `reached` (with `date`), `immediate` (B never behind A), `never_in_horizon`
  (with `caveat`, `trend_per_month_since_worst`, `extrapolated_date` when the gap is closing),
  `identical`. `max_shortfall` is the worst point of B relative to A. Differences do not depend on
  the starting balance.

## What-if shortcuts (prefer these for one or two tweaks)

`project`, `summary`, `debt schedule`, `compare` and `breakeven` accept repeatable flags that build a
scenario for you (and merge with `--scenario`/`--scenario-json` if also given):

```
--disable FLOW                 --disable-tag TAG             --enable FLOW
--payoff "FLOW@DATE"           --extra-payment "FLOW:AMOUNT@DATE"
--set-payment "FLOW:AMOUNT@DATE"                             --rate-change "FLOW:RATE@DATE"
--add-income "NAME:AMOUNT@DATE"                              --add-expense "NAME:AMOUNT@DATE"
--set-amount "FLOW:AMOUNT[@FROM]"
```
Amount is taken after the last `:` and date after the last `@`, so names may contain spaces.
Example: `cash project --starting-balance 3000 --until 2026-11-13 --extra-payment "Mini Cooper:15000@2026-11-13" --select spare_balance,spare`

## Scenario JSON (for anything the shortcuts can't express)

Pass with `--scenario FILE`, `--scenario FILE` = `-` for stdin, or `--scenario-json '{...}'`. Every key
is optional. Flow references accept id or name.

```json
{
  "name": "sell the car",
  "weekly_spend": "150",
  "disable": { "flow_ids": [3], "flows": ["Car insurance"], "tags": ["car"] },
  "enable":  { "flows": ["Bus pass"] },
  "amount_changes": [ { "flow": "Rent", "amount": "1650", "from": "2027-01-01", "until": null } ],
  "add_flows": [
    { "name": "Car sale", "kind": "income", "amount": "15000", "on": "2026-10-15", "tags": ["car"] },
    { "name": "Bus pass", "kind": "expense", "amount": "90", "rrule": "FREQ=MONTHLY;BYMONTHDAY=1",
      "dtstart": "2026-11-01", "until": null, "tags": ["transport"], "weekend": "next" },
    { "name": "New loan", "kind": "expense", "amount": "386.66", "rrule": "FREQ=MONTHLY;BYMONTHDAY=1",
      "dtstart": "2026-11-01",
      "debt": { "balance": "20000", "balance_as_of": "2026-10-01", "annual_rate": "6%",
                "compounding": "monthly", "day_count": "actual/365", "capitalize_interest": true,
                "payment_mode": "fixed", "posting_day": 1 } }
  ],
  "debt_events": [
    { "flow": "Car loan", "type": "payoff", "date": "2026-10-15" },
    { "flow": "Car loan", "type": "extra_payment", "date": "2026-10-15", "amount": "5000" },
    { "flow": "Car loan", "type": "rate_change", "date": "2027-01-01", "rate": "0.05" },
    { "flow": "Car loan", "type": "balance_adjustment", "date": "2027-01-01", "amount": "-250" },
    { "flow": "Car loan", "type": "payment_change", "date": "2027-01-01", "amount": "450" },
    { "flow": "s:3", "type": "extra_payment", "date": "2027-06-01", "amount": "1000" }
  ]
}
```
Rules:
- `enable` runs before `disable`; disable wins. Unknown flow → error `scenario_unknown_flow`;
  a tag matching nothing → warning.
- Disabling a debt's payment flow removes the debt AND its payments from the projection (with a
  warning) — unless the scenario also gives it a `payoff` event, in which case the flow is kept:
  payments continue until the payoff date, then stop. So "sell the car" = disable tag `car` +
  payoff on the sale date + one-off sale income.
- Ad-hoc flows are keyed `s:1`, `s:2`, … (in order) and can be referenced by `debt_events`.
- `amount_changes` are piecewise: `from` (inclusive, default = as-of) and optional `until`.
- Output echoes the scenario under `scenario` and lists what it did under `scenario_applied`.

## Worked examples

**"Assuming I have $3,000 right now, how much will I have in 6 months?"** (ask the user for a
weekly lifestyle budget, or use the one they usually quote)
```
cash project --starting-balance 3000 --months 6 --weekly-spend 200
# → data.spare_balance (money actually free to use: balance minus bills due before the next paycheck)
#   data.ending_balance is the raw end-of-day balance; data.spare lists the bills that were deducted
```

**"How much am I paying on car-related expenses each month?"**
```
cash summary --tag car        # → data.by_tag[0].expense_monthly (and by_flow for the breakdown)
```

**"If I sell the car for $15,000 on Oct 15, pay off the loan, and drop the insurance, when do I break even?"**
```
cat > sell.json <<'JSON'
{"name":"sell car","disable":{"tags":["car"]},
 "add_flows":[{"name":"Car sale","kind":"income","amount":"15000","on":"2026-10-15"}],
 "debt_events":[{"flow":"Car loan","type":"payoff","date":"2026-10-15"}]}
JSON
cash breakeven --scenario sell.json          # → data.breakeven.date / status / max_shortfall
cash compare --scenario sell.json --months 24 # → side-by-side series
# or, without a file:
cash breakeven --disable-tag car --add-income "Car sale:15000@2026-10-15" --payoff "Car loan@2026-10-15" --select breakeven
```

**"What does my loan look like if I pay an extra $200 a month?"**
```
cash debt schedule "Car loan" --scenario-json '{"debt_events":[{"flow":"Car loan","type":"payment_change","date":"2026-11-01","amount":"586.66"}]}'
```

**"Lowest my balance will get this year?"** → `cash project --starting-balance 3000 --months 12` → `data.min_balance`.

## Database schema (sqlite, single file)

All money columns are integer cents; rates are decimal strings; dates are ISO text.

```sql
CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);

CREATE TABLE flow (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL COLLATE NOCASE UNIQUE,
  kind TEXT NOT NULL CHECK (kind IN ('income','expense')),
  amount_cents INTEGER NOT NULL CHECK (amount_cents >= 0),
  rrule TEXT,                        -- RRULE body; NULL = one-off on dtstart
  dtstart TEXT NOT NULL, until TEXT, -- ISO dates, until inclusive
  active INTEGER NOT NULL DEFAULT 1,
  notes TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  weekend TEXT NOT NULL DEFAULT 'none' CHECK (weekend IN ('none','next','previous')));

CREATE TABLE tag (id INTEGER PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE);
CREATE TABLE flow_tag (flow_id INTEGER REFERENCES flow ON DELETE CASCADE,
                       tag_id INTEGER REFERENCES tag ON DELETE CASCADE, PRIMARY KEY (flow_id, tag_id));

CREATE TABLE debt (
  flow_id INTEGER PRIMARY KEY REFERENCES flow(id) ON DELETE CASCADE,
  original_principal_cents INTEGER,
  balance_cents INTEGER NOT NULL, balance_as_of TEXT NOT NULL,
  annual_rate TEXT NOT NULL,
  compounding TEXT NOT NULL CHECK (compounding IN ('simple','daily','monthly','continuous')),
  day_count TEXT NOT NULL DEFAULT 'actual/365',
  capitalize_interest INTEGER NOT NULL DEFAULT 1,
  payment_mode TEXT NOT NULL DEFAULT 'fixed', payment_pct TEXT,
  posting_day INTEGER);               -- monthly compounding: day interest posts

CREATE TABLE debt_event (
  id INTEGER PRIMARY KEY, flow_id INTEGER NOT NULL REFERENCES debt(flow_id) ON DELETE CASCADE,
  date TEXT NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('rate_change','balance_adjustment','extra_payment','payment_change','payoff')),
  rate TEXT, amount_cents INTEGER, notes TEXT);
```
Useful SQL: `cash sql "SELECT f.name, f.amount_cents/100.0 AS amount, group_concat(t.name) AS tags FROM flow f LEFT JOIN flow_tag ft ON ft.flow_id=f.id LEFT JOIN tag t ON t.id=ft.tag_id GROUP BY f.id"`.

## Error codes
`usage`, `db_not_found`, `db_exists`, `db_not_empty`, `db_newer_than_cli`, `unknown_flow`,
`duplicate_flow`, `invalid_name`, `invalid_amount`, `negative_amount`, `invalid_rate`, `invalid_date`,
`invalid_rrule`, `invalid_tag`, `unknown_tag`, `duplicate_tag`, `debt_requires_expense`, `no_debt`,
`invalid_debt`, `invalid_event`, `unknown_event`, `invalid_scenario`, `scenario_unknown_flow`,
`scenario_no_debt`, `scenario_not_found`, `readonly_sql`, `sql_error`, `invalid_import`,
`file_not_found`, `integrity`.
