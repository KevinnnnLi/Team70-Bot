# Roostoo 30-Day Relative Momentum Bot

Autonomous trading bot for the **Hong Kong vs Australia vs India Quant Trading
Hackathon**, running against the Roostoo mock exchange. Universe: `BTC/USD` and
`ETH/USD` only. Spot, 1x, market orders, no leverage.

The strategy, research, and competition rules are specified in
[STRATEGY_HANDOFF.md](STRATEGY_HANDOFF.md).

## What the bot does

Once per UTC day, using the last **completed** 1-hour Binance candle, the bot
computes a 30-day return for Bitcoin (`b`) and Ethereum (`e`):

```
b = BTCUSDT close[t] / BTCUSDT close[t - 720 hours] - 1
e = ETHUSDT close[t] / ETHUSDT close[t - 720 hours] - 1
```

* both returns positive: hold **100% of equity** in whichever coin has the
  larger return (a tie goes to Bitcoin)
* only one return positive: hold **100% of equity** in that coin
* both returns zero or negative: **short Bitcoin** for 100% of equity
* the target is already the current position: send no order

The position is held until the next UTC day. The bot is long or short exactly
one asset and is never in cash by choice, except after a halt.

A **20% drawdown from the bot's own peak equity** (marked on Roostoo prices)
flattens every position and halts trading for the rest of the contest,
including across restarts.

Binance is used only for the 30-day return. Orders are sized off the Roostoo
`LastPrice` and sent to Roostoo.

## Files

| Path | Purpose |
| --- | --- |
| `bot.py` | Entry point: preflight, dry run, and the 300-second loop |
| `roostoo/strategy.py` | The `target(b, e)` rule |
| `roostoo/binance.py` | Binance klines, completed-candle handling, 30-day return |
| `roostoo/client.py` | Roostoo REST client: signing, retries, response parsing |
| `roostoo/signing.py` | HMAC-SHA256 request signing and server-time offset |
| `roostoo/engine.py` | Decision loop, rebalancing, drawdown halt, logging |
| `roostoo/positions.py` | Live position detection and the rebalance action table |
| `roostoo/sizing.py` | Precision flooring, taker-fee reservation, dust limits |
| `roostoo/equity.py` | Mark-to-market equity, including open shorts |
| `roostoo/state.py` | `state.json` persistence with an automatic backup |
| `roostoo/logging_utils.py` | CSV logs and the human-readable `logs/bot.log` |
| `roostoo/preflight.py` | Read-only `--check` diagnostics |
| `tests/` | `unittest` suite covering every rule above |

## Requirements

Python 3.9 or newer and the `requests` package. Nothing else.

## Setup

### Environment variables

Three variables are read at startup. The bot **refuses to start** if either
credential is empty.

```bash
cp env.example env.sh
nano env.sh                     # paste your Roostoo key and secret
set -a; . ./env.sh; set +a
```

| Variable | Meaning |
| --- | --- |
| `ROOSTOO_API_KEY` | API key issued by the organisers |
| `ROOSTOO_SECRET_KEY` | API secret issued by the organisers |
| `ROOSTOO_BASE_URL` | Defaults to `https://mock-api.roostoo.com` |
| `ROOSTOO_STATE_PATH` | Where `state.json` lives. Defaults to `./state.json` |
| `ROOSTOO_LOG_DIR` | Where the CSVs and `bot.log` live. Defaults to `./logs` |
| `BINANCE_BASE_URL` | Testing only. Leave unset so the signal comes from Binance |

`env.sh` is git-ignored. Never commit it and never print its contents into a log.

### Install

```bash
pip install -r requirements.txt
```

On the hackathon EC2 instance, `bash setup.sh` installs Python, `pip`, `tmux`,
git, and the dependency in one step.

## Running

**1. Preflight, read-only, sends no orders:**

```bash
python3 bot.py --check
```

This checks the credentials, server time offset, `exchangeInfo` (including
`CanTrade`, `AmountPrecision`, `PricePrecision`, `MiniOrder`), balance, tickers,
the live Binance signal, the current position, equity, and the persisted state.
Exit code `0` means healthy.

**2. Deployment rehearsal, runs the real loop but never sends an order:**

```bash
python3 bot.py --dry-run
```

Use this only to prove the deployment works. It still writes `state.json`, so
switch to a live run within the same UTC day and the pending decision will be
executed then. Do not leave `--dry-run` running during the competition.

**3. Live, under tmux:**

```bash
tmux new -s bot 'python3 bot.py'
# detach with Ctrl-B then D
tmux attach -t bot
```

The loop wakes every 300 seconds: it refreshes server time, marks equity,
updates the peak, checks the halt, and decides at most once per UTC day.

`python3 bot.py --once` runs a single loop and exits, which is useful for
scripted restarts.

## Logs

All three files are appended to on every loop, with a header row written on
first use.

* `logs/decisions.csv` — `utc_time,btc_ret_30d,eth_ret_30d,target,equity,peak_equity,halted,order_sent,note`
* `logs/trades.csv` — `utc_time,action,pair,request,success,err_msg,response`
* `logs/equity.csv` — `utc_time,equity,peak_equity,btc_qty,eth_qty,usd_free,short_btc_qty,halted`

`logs/bot.log` holds the same information as human-readable lines: time, `b`,
`e`, target, equity, peak, halted, and whether an order was sent.

The logs are git-ignored by default. To keep them in the repository as evidence
of autonomous execution, commit the three CSVs after each trading day. The
`decisions.csv` row written on every loop is the record that the bot was active
on that UTC date even when the signal held the same position and no order was
sent, which is what the competition's "active trading days" requirement asks
for. Only `logs/bot.log` is ignored.

## State and restarts

`state.json` stores the last decision date, the decided target, the returns
behind it, whether it finished executing, the peak equity, and the halt flag. It
is written atomically and a `.bak` copy of the previous version is kept. A
restart therefore never re-sends a rebalance that already happened, and a
failed order is retried against the **same** target rather than recomputing one.

## Deploying on the hackathon AWS account

The event runs in `ap-southeast-2` (Sydney) on a single `t3.medium` launched
from the `Hackathon-Starter-Template`, reached through Session Manager only.

```bash
cd ~
git clone <your-repo-url>
cd <repo>
bash setup.sh
cp env.example env.sh && nano env.sh
set -a; . ./env.sh; set +a
python3 bot.py --check        # must print RESULT: OK
tmux new -s bot 'python3 bot.py'
# Ctrl-B then D to detach
```

Do not launch a second instance and do not stop the instance during the
competition.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

The suite covers the decision rule, precision flooring and fee reservation,
completed-candle selection, the full rebalance action table, equity with open
shorts, drawdown halting, restart idempotency, order-failure retries, and the
HMAC signature vectors.

## Notes and caveats

* Decisions are made once the **00:00 UTC hourly candle has closed**, i.e. from
  about 01:00 UTC, using the newest closed candle.
* `/v3/serverTime`, `/v3/exchangeInfo`, and `/v3/ticker` are sent unsigned;
  every endpoint that touches the account is signed with the parameters the API
  documents, plus `timestamp`.
* Missing numeric fields in a Roostoo short response are treated as `0`.
* Order sizing reserves the 0.1% taker fee, floors to `AmountPrecision`, and
  skips any remainder below the exchange `MiniOrder` or the 75 USD dust floor.
* Market orders only. If a `short_open` ever returned `Status: PENDING`, the
  engine cancels it and retries the decision.

### Verified against the live mock API

Checked on 2026-10-05 (HKT) with the testing credentials:

* `GET /v3/exchangeInfo` returns `IsRunning`, `InitialWallet`, and `TradePairs`
  with **no `Success` flag**, so the client treats a flag-less HTTP 200 body as
  success and still fails on a body that carries an `ErrMsg`.
* `GET /v3/balance` wraps the wallets in **`SpotWallet`**, and the wallet entries
  carry extra `PendingOrders` and `ShortCollateral` fields that are ignored.
* The account reported `InitialWallet: {"USD": 50000}` and `USD.Free = 50000`;
  the bot reads that live and never hardcodes a starting balance.
* `BTC/USD` and `ETH/USD` both report `CanTrade: true`, `MiniOrder: 1`,
  `AmountPrecision` 5 and 4, and `PricePrecision` 2.
* Binance klines and the 30-day returns compute correctly over the public API.
* One full live cycle was run with `python3 bot.py --once`. The bot computed the
  signal itself and placed the resulting order: `BUY 18.4615 ETH/USD`, OrderID
  `3422089`, `Status: FILLED`, `Role: TAKER`, average price `2705.63`. The fill
  used `49949.988` USD plus `49.949988` USD commission (`CommissionPercent:
  0.001`), so notional plus fee stayed inside the `50000` balance, and the
  restart guard then reported the target as already held.

The short endpoints (`/v6/short_open`, `/v6/short_close`) are exercised by the
test suite against a fake exchange but have not been triggered against the live
account, because they only fire when both 30-day returns are negative. They are
never called by hand.

## Licence

MIT. See [LICENSE](LICENSE).
