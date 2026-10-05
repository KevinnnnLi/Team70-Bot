# Roostoo competition bot — build exactly this

You are writing an autonomous trading bot for the Hong Kong vs Australia vs India Quant Trading Hackathon. The exchange is Roostoo’s mock API. Prices track the live market. Fills and balances are mock. Implement the strategy in this file exactly. Do not add coins, factors, a shorter lookback, volatility targeting, stops other than the drawdown halt, or a machine-learning model.

This file is the whole spec. Official API reference, if a field is unclear: https://github.com/roostoo/Roostoo-API-Documents

## Contest

- Live window: 4–17 October 2026 (HKT). Open-source the repo on GitHub before 14 October 2026.
- Teams of 1–4. Original code. One public repo with a README.
- Screen 1: autonomous only. Disqualification if someone trades by hand on the website or by hand-called API requests, or if the commit history does not match the running strategy.
- Screen 2: top 20 teams per region by portfolio return, `(Final − Initial) / Initial`.
- Screen 3: `0.4 × Sortino + 0.3 × Sharpe + 0.3 × Calmar`. Risk-free rate 0. In our research, hourly returns were annualized with `sqrt(24 × 365)`, and Calmar was CAGR / max drawdown. The organizers publish the exact formulas on finale day.
- At least 8 separate days must have strategy-driven trades. This signal often holds the same position for many days. Log every daily decision. Send an order only when the target position changes. Do not add trades that are not part of this signal.
- Spot only, 1x long or 1x short. No leverage. No HFT, no market making, no arbitrage. A tight request loop will get failed responses.
- Do not trade a price gap between Roostoo and Binance. Binance is only the history for the 30-day return. Orders go to Roostoo, sized off the Roostoo price.
- Cloud: one `t3.medium` in `ap-southeast-2` only, from template `Hackathon-Starter-Template`, Session Manager only (no SSH). 30 GB disk. No other AWS services. Run under `tmux`. Portal: https://d-906625dad1.awsapps.com/start . Guide: https://roostoo.notion.site/Hackathon-Guide-How-to-Sign-In-AWS-and-Launch-Your-Bot-309ba22fed798071b4dde6d1e8666816
- Fees on normal orders: MARKET is 0.1% taker, LIMIT is 0.05% maker. Use MARKET. Short open and short close are also charged 0.1% (see the short section).
- Mock starting cash is whatever `GET /v3/exchangeInfo` returns in `InitialWallet` and whatever `GET /v3/balance` shows. Do not hardcode 50000 or 100000. The public doc example shows USD 50000. The contest brief said 100000. Trust the balance endpoint.

## Universe

Only these two pairs. Do not trade any other crypto pair and do not trade the tokenized stock pairs.

| Coin | Roostoo pair | Binance symbol for the signal |
|---|---|---|
| Bitcoin | `BTC/USD` | `BTCUSDT` |
| Ethereum | `ETH/USD` | `ETHUSDT` |

On startup, `GET /v3/exchangeInfo` and require `CanTrade: true` for both. Read `AmountPrecision`, `PricePrecision`, and `MiniOrder` from that response. `MiniOrder` is a minimum notional: an order is allowed when `price × quantity > MiniOrder`.

## The strategy

Once per UTC date, using the last **completed** Binance 1-hour candle (drop the candle that is still forming):

```text
b = BTC close[t] / BTC close[t - 720 hours] - 1
e = ETH close[t] / ETH close[t - 720 hours] - 1
```

720 hours is 30 days. The two closes in one return must both be Binance closes. Do not mix a Roostoo price into the return.

Then:

1. If `b > 0` and `e > 0`: put 100% of equity into the coin with the larger return.
2. If only one of `b` or `e` is above 0: put 100% of equity into that coin.
3. If `b <= 0` and `e <= 0`: short Bitcoin for 100% of equity. Do not short Ethereum. Do not hold both coins. Do not stay in cash.

There is no minimum gap. `+0.001` beats `-0.20`. Equal positive returns: hold Bitcoin.

Leave that position until the next UTC date. If the new target is already the current position, send no order.

As of the research bar 2026-10-04 08:00 UTC, `b` was `+0.049` and `e` was `+0.068`, so the target was long Ethereum. Recompute live. Do not hardcode the side.

### When to decide

- Decide once per UTC date, at or after 00:00 UTC, after the hourly candle that contains that midnight has closed. If the process was down at midnight, decide on the next loop, still only once that UTC date.
- Persist the UTC date of the last decision in a local file. A restart must not send the same rebalance twice.
- Between decisions, the 5-minute loop only retries a failed order and checks the drawdown halt. It does not recompute a new target.

### Python, the decision only

```python
def target(btc_ret_30d: float, eth_ret_30d: float) -> str:
    """Return 'long_btc', 'long_eth', or 'short_btc'."""
    b = btc_ret_30d
    e = eth_ret_30d
    if b > 0 and e > 0:
        return "long_btc" if b >= e else "long_eth"
    if b > 0:
        return "long_btc"
    if e > 0:
        return "long_eth"
    return "short_btc"
```

## Signal data

Binance public klines, no key:

```text
GET https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1h&limit=1000
GET https://api.binance.com/api/v3/klines?symbol=ETHUSDT&interval=1h&limit=1000
```

Each row is `[open_time_ms, open, high, low, close, volume, close_time_ms, ...]`. Use the close, parsed as float. Drop the last row if its candle is still open (`close_time_ms` is in the future, or `open_time` is the current hour). You need at least 721 completed closes. `return = closes[-1] / closes[-721] - 1`.

Roostoo does not provide a long enough candle history for this. Do not use Roostoo `Change` (that field is a 24-hour percentage, and on this API it is a fraction like `-0.0112`, not a 30-day return).

## How you are marked to market

Roostoo ticker, timestamp required, not HMAC-signed:

```text
GET /v3/ticker?timestamp=<13 digit ms>&pair=BTC/USD
GET /v3/ticker?timestamp=<13 digit ms>&pair=ETH/USD
```

Use `Data[pair].LastPrice` to convert coin quantity to USD. Use `MaxBid` only as the doc’s description of where a market short opens, and `MinAsk` as where a market short closes. You do not send those prices on a market order.

Equity in USD:

```text
equity = USD.Free + USD.Lock
       + BTC quantity × BTC LastPrice
       + ETH quantity × ETH LastPrice
       + UnrealizedPNL of each open short
```

`USD.Lock` already contains short collateral, so do not add `Collateral` again. `UnrealizedPNL` comes from `GET /v6/short_positions`. If that list is empty, the short term is 0. Coin quantity is `Free + Lock` for that coin.

## Roostoo signing

Base URL: `https://mock-api.roostoo.com`

Headers on every signed call:

- `RST-API-KEY`: the API key
- `MSG-SIGNATURE`: hex HMAC-SHA256

Timestamp is 13-digit milliseconds. Signed calls are rejected if it is more than 60 seconds from `GET /v3/serverTime` (`ServerTime`). Keep an offset: `offset = serverTime - localTime`, send `localTime + offset`.

Build the signature from the parameters the endpoint lists, plus `timestamp`. Stringify every value. Sort the keys. Join `key=value` with `&`. HMAC-SHA256 that string with the secret, hex digest. Do not include any extra parameter. The server signs only the listed parameters, so an extra key makes the signature fail.

POST body is `application/x-www-form-urlencoded`. GET puts the same pairs in the query string. A failed trade often still returns HTTP 200 with `Success: false` and `ErrMsg`. Always check `Success`.

```python
import hashlib, hmac

def sign(secret: str, params: dict) -> str:
    payload = {k: str(v) for k, v in params.items()}
    total = "&".join(f"{k}={payload[k]}" for k in sorted(payload))
    return hmac.new(secret.encode(), total.encode(), hashlib.sha256).hexdigest()
```

Environment variables, never committed:

```text
ROOSTOO_API_KEY
ROOSTOO_SECRET_KEY
ROOSTOO_BASE_URL=https://mock-api.roostoo.com
```

## Orders

### Long and flat — `/v3`

`GET /v3/balance` with `timestamp`. Wallet entries look like `{"USD": {"Free": 100000, "Lock": 0}, "BTC": {"Free": 0, "Lock": 0}, "ETH": {...}}`.

`POST /v3/place_order` parameters: `pair`, `side` (`BUY` or `SELL`), `type` (`MARKET`), `quantity`, `timestamp`. `quantity` is the coin amount, not USD. Floor it to `AmountPrecision`. Notional `price × quantity` must be greater than `MiniOrder`. Skip any dust order below about 75 USD so the 0.1% fee is not spent on a remainder.

`POST /v3/query_order` and `POST /v3/cancel_order` exist. This strategy uses market orders, so cancels are only for a short limit order you did not intend to leave open. Do not place limit orders.

Market buy of Bitcoin with the free USD:

```text
spend = USD.Free / 1.001          # leave the 0.1% taker fee
qty = floor(spend / BTC LastPrice, AmountPrecision)
POST /v3/place_order  pair=BTC/USD side=BUY type=MARKET quantity=<qty>
```

Market sell: `quantity` is the coin `Free` balance, floored to `AmountPrecision`.

### Short Bitcoin — `/v6`, same host, same key, same signature

These routes are `/v6`, not `/v3`.

Open, market (do not send `order_type`, or any limit price):

```text
POST /v6/short_open
pair=BTC/USD
collateral=<USD to lock>
timestamp=<ms>
```

There is no `side` and no `quantity`. The exchange sets `ShortQty = collateral / EntryPrice`, floored to `AmountPrecision`. A market short fills at `MaxBid`. The open fee is 0.1% of notional, charged immediately, including if you had sent a limit. Free USD must cover `collateral + fee`.

To be 1x short after the longs are sold:

```text
collateral = USD.Free / 1.001
```

Minimum collateral is 1. Send `collateral` as a string. Floor it to cents.

Response `Success: true` includes `ID`, `Pair`, `EntryPrice`, `ShortQty`, `Collateral`, `OpenFee`, `Status`. `Status: OPEN` means filled. `Status: PENDING` would be a limit order. This strategy must not leave a pending short. If you ever see `PENDING`, cancel that order id with `POST /v3/cancel_order`.

Close the whole Bitcoin short (omit `close_qty` and `close_pct`):

```text
POST /v6/short_close
pair=BTC/USD
timestamp=<ms>
```

The close fills at `MinAsk`. Close fee is 0.1% of the closed value. Loss cannot exceed the collateral. `FullyClosed: true` means it is gone.

List open shorts:

```text
GET /v6/short_positions?timestamp=<ms>
```

`Positions` is a list, `[]` when flat. Each item has `Pair`, `ShortQty`, `Collateral`, `UnrealizedPNL`, `PositionValue`.

If `short_open` returns `Success: false` and `ErrMsg` is `this competition does not allow short positions`, do not invent another way to short. Stay in cash until the signal is a long. Log that error. Any other `ErrMsg` (`insufficient balance`, `pair not found`, `minimum collateral is $1`, `your do not have permission to trade`) is a failure to retry with backoff, not a reason to change the signal.

A missing numeric field in a short response means 0. The server omits zeros.

## How to move from one target to the next

Always read balance and `GET /v6/short_positions` before trading. Close the old risk first, then open the new one. After each call, re-read balances. If a call fails, stop the sequence, log it, and retry the same sequence on the next loop. Do not stack a second copy of the position.

| Current | Target | Actions, in order |
|---|---|---|
| Flat | Long Bitcoin | Market buy BTC with `USD.Free / 1.001` |
| Flat | Long Ethereum | Market buy ETH with `USD.Free / 1.001` |
| Flat | Short Bitcoin | `short_open` BTC with collateral `USD.Free / 1.001` |
| Long Ethereum | Long Bitcoin | Market sell all ETH. Then market buy BTC with the new free USD. |
| Long Bitcoin | Long Ethereum | Market sell all BTC. Then market buy ETH. |
| Long Ethereum | Short Bitcoin | Market sell all ETH. Then `short_open` BTC with the new free USD. |
| Long Bitcoin | Short Bitcoin | Market sell all BTC. Then `short_open` BTC. |
| Short Bitcoin | Long Ethereum | `short_close` BTC with no quantity. Then market buy ETH. |
| Short Bitcoin | Long Bitcoin | `short_close` BTC. Then market buy BTC. |
| Already the target | Same target | No order |

“All” of a coin means its `Free` balance, floored to `AmountPrecision`. Ignore a leftover below 75 USD notional.

## Drawdown halt

Persist `peak_equity` in the same state file as the last decision date.

Every loop:

```text
equity = mark to market as above
peak_equity = max(stored peak, equity)
if equity <= peak_equity × 0.80:
    flatten (sell every long, short_close every short)
    set halted = true
```

While `halted` is true, do not open a new long or short. Keep logging equity. The halt stays on for the rest of the contest, including across restarts. 20% is wider than a 12% halt on purpose: this book’s normal dip on the six-month test was about 12%, and a 12% halt would have shut it off on an ordinary pullback.

## Process loop

Every 300 seconds:

1. Sync server time if the last sync is older than a few minutes, and again if a call fails with a timestamp error.
2. Mark equity. Update the peak. If the halt trips, flatten and stop.
3. If not halted and today’s UTC date has no successful decision yet, and the latest Binance hour is closed: compute `b` and `e`, store them, and trade toward `target(b, e)` if the live position is different.
4. If today’s decision was attempted but an order failed, retry that sequence. Do not compute a second target.
5. Append equity to `logs/equity.csv`. Append orders to `logs/trades.csv`. Append the decision, including “no order”, to `logs/decisions.csv`.

Also write a human log line: time, `b`, `e`, target, equity, peak, halted, and whether an order was sent.

CSV columns:

```text
decisions.csv: utc_time,btc_ret_30d,eth_ret_30d,target,equity,peak_equity,halted,order_sent,note
trades.csv: utc_time,action,pair,request,success,err_msg,response
equity.csv: utc_time,equity,peak_equity,btc_qty,eth_qty,usd_free,short_btc_qty,halted
```

Retry network errors and HTTP failures 3 times with sleeps of 2s, 4s, 8s. Then wait for the next loop. Do not spin.

## What was already tested

Same rule, same two coins, same “short Bitcoin when both are down”, only the lookback changed. Hourly Binance data from 2025-04-04 through 2026-10-04 08:00 UTC. Cost in the test was 0.1% of the change in weight. A full Bitcoin hold over the last 90 days of that sample made +34.9%. A full Ethereum hold made +52.3%. Over the last year both of those holds were down about 30% to 40%.

| Lookback | 14 days | 1 month | 3 months | 6 months | 1 year | Position on the last bar |
|---|---:|---:|---:|---:|---:|---|
| 30 days | +4.8% | +6.8% | +50.2% | +76.2% | +73.8% | Long Ethereum |
| 21 days | +5.3% | −11.1% | +6.7% | +26.0% | +7.2% | Long Bitcoin |
| 14 days | +4.2% | −11.1% | +15.7% | +17.7% | +32.6% | Long Bitcoin |
| 7 days | −1.2% | −20.3% | −20.1% | +11.0% | −37.5% | Long Bitcoin |
| 3 days | +5.6% | −8.5% | −26.8% | −32.2% | −58.5% | Long Bitcoin |
| 1 day | +2.4% | −1.3% | −8.8% | −11.1% | −20.5% | Long Ethereum |

Thirty days is the one that stayed ahead of holding Bitcoin from one month through one year. The contest being 14 days long is not a reason to shorten the lookback. On the earlier declining part of the sample (from about 3 June 2025 to 6 July 2026) this 30-day rule made about +65% with a 27% max drawdown, while holding Bitcoin made about −40%. Those figures are research, not a promise for the contest window.

Over the last 14 days this 30-day book did not trade. It was already long Ethereum. That is expected.

## Run it

Python 3. Dependencies: `requests` is enough.

```text
python bot.py
```

The process:

1. Load env. Refuse to start if the key or secret is empty.
2. `GET /v3/serverTime`, then `GET /v3/exchangeInfo`.
3. Load `state.json` if it exists (`last_decision_date`, `peak_equity`, `halted`).
4. Enter the 300-second loop above.
5. On SIGTERM, finish the current order if one is in flight, flush logs, exit. Do not flatten just because the process is restarting. The halt is the only flatten.

Deploy:

```text
# on the single ap-southeast-2 instance, via Session Manager
sudo dnf install -y tmux python3 python3-pip
git clone <the public repo>
cd <repo>
pip install requests
# put the three env vars in a file that is not committed, and source it
tmux new -s bot
python bot.py
# detach with Ctrl-B then D
# reattach with: tmux attach -t bot
```

Do not start a second instance. Do not stop the instance until the contest is over.

## README to ship in the repo

State this in plain language: once a UTC day, the bot holds whichever of Bitcoin or Ethereum has the higher 30-day Binance return, if that return is positive, and shorts Bitcoin on Roostoo when both 30-day returns are negative. The position is 100% of equity, 1x. A 20% drawdown from the bot’s own peak flattens the account and stays flat. Say how to set the three environment variables and how to run `python bot.py` under tmux. Point at `logs/decisions.csv` and `logs/trades.csv`.

Do not describe a different strategy than the one in this file.
