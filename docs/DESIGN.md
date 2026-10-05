# Design notes

The full specification, research, and competition rules live in
[`STRATEGY_HANDOFF.md`](../STRATEGY_HANDOFF.md). This note explains how the code
is organised rather than restating the strategy.

## Shape of the system

`bot.py` wires together four pieces and does nothing else:

1. a `RoostooClient` built on a swappable `Transport`
2. a `StateStore` for `state.json`
3. a `LogBundle` for the three CSVs
4. an `Engine` that owns the 300-second loop

Everything that encodes a rule is a pure function in its own module, so the
rules can be tested without a network, a clock, or real money:

| Module | Responsibility |
| --- | --- |
| `strategy.target` | the `b`/`e` decision, nothing else |
| `binance.completed_closes` | drop the still-forming candle, require 721 closes |
| `binance.return_30d` | `close[-1] / close[-721] - 1` |
| `sizing` | `Decimal` flooring, taker-fee reservation, `MiniOrder`/dust checks |
| `positions.live_position` | what the account actually holds right now |
| `positions.plan_actions` | the current-to-target action table |
| `equity.equity_usd` | mark to market, adding unrealised short P&L once |
| `signing` | sort-keys HMAC-SHA256 payload |

## Loop

`Engine.run_once` performs, in order:

1. `GET /v3/serverTime` if the offset is stale, then load `state.json`
2. mark equity on Roostoo prices, ratchet `peak_equity`
3. if `equity <= peak x 0.80`, flatten and set `halted`, then stop
4. if halted, make sure the account is flat and log, without opening anything
5. on a new UTC date, fetch the Binance signal and store the target **before**
   trading, so a crash mid-rebalance leaves the same target to retry
6. rebalance: read balance and short positions, close the old risk, open the new
   position, re-reading balances between steps
7. append to `decisions.csv` and `equity.csv` and write the human log line

## Idempotency and failure handling

The state file is the contract between runs. A decision is recorded with
`decision_complete: false`, and only flips to `true` once every action in the
plan succeeds. Consequences:

* restarting the process never re-sends a completed rebalance
* an order that fails is retried on the next loop against the stored target, and
  the signal is not recomputed
* a `short_open` rejected with "this competition does not allow short positions"
  is terminal for that day: it is logged, the decision is marked handled, and the
  bot stays flat until the signal becomes a long

Transport errors and HTTP 5xx responses are retried three times with 2s, 4s, and
8s backoff inside the client. A `Success: false` body is raised as `ApiError`
and stops the current sequence; the next loop retries it.

## Testing

`tests/` uses the standard library `unittest`, so the suite runs with no extra
dependency. `tests/fakes.py` provides an in-memory Roostoo account and a fake
transport, which lets the engine tests assert on real order sequences rather
than on mocks of internal calls.

`tests/test_client.py` additionally pins the exact payload shapes returned by
the live mock API, including the `Success`-less `exchangeInfo` body and the
`SpotWallet` balance envelope, so a future refactor cannot silently reintroduce
the parsing bugs those shapes caused.
