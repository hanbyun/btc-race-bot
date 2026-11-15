# Dip-Catcher BTC Bot — make.fun `btc-race-24h-20261115-0828`

[![make.fun · btc-race-24h-20261115-0828](https://make.fun/badge/btc-race-24h-20261115-0828.svg)](https://make.fun/bounty/btc-race-24h-20261115-0828?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261115-0828)
[![rank](https://make.fun/badge/btc-race-24h-20261115-0828/hanbyun/btc-race-bot/rank.svg)](https://make.fun/bounty/btc-race-24h-20261115-0828/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261115-0828)
[![reward](https://make.fun/badge/btc-race-24h-20261115-0828/hanbyun/btc-race-bot/reward.svg)](https://make.fun/bounty/btc-race-24h-20261115-0828?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261115-0828)

Built for the [make.fun bounty "Race a BTC trading bot live for 24 hours"](https://make.fun/bounty/btc-race-24h-20261115-0828), $250 in USDC.

Long-only 1-minute cbBTC/USDC bot. Starts with $1,000 USDC, one position,
fills at the next bar's open. Buys sharp intraday dips at full size with
**no uptick confirmation**, averages down once if the dip extends, and
exits on a hard stop, a profit-armed ATR trail, or a time stop.

## Strategy

**Entry — two drawdown legs; either one can fire on its own.** A buy is
placed on the dip bar's close itself (no waiting for a green bar):

1. **Fast leg:** the close is at least **250 bps** below the highest
   **high** of the prior 60 one-minute bars, and **RSI(9) < 30**
   (Wilder). This is the sharp-dip leg: it fires on the fast drop at
   bar ~995 of the dev window (with the scale-in at ~1031).
2. **Slow leg:** the close is at least **300 bps** below the highest
   **high** of the prior 200 one-minute bars. No RSI gate on this leg: a
   200-bar drawdown of that depth is itself the oversold signal, and on
   the dev window the RSI gate would have blocked the leg's first trade
   (bar ~421, RSI above 30 on a slow grind).

**Sizing — half first, average down once.** Each leg buys **50% of cash**,
not 100%. The other half stays in cash so the bot can buy once more if
the dip extends: while in a position, if **RSI(9) < 30** and the close is
at least **100 bps** below the position's average entry close, it buys
with all remaining cash (second and last tranche). This turns a dip that
keeps dipping into a lower average cost instead of a stopped-out loss,
as long as the hard stop below is not hit first.

**Exit — the whole position is sold on the first of:**

* **Hard stop:** close at or below the average entry close minus **2.0%**.
* **Trailing stop:** peak close since entry minus **4.0 × ATR(14)**,
  armed only once the current close is at least **1.0%** above the
  average entry — so the trail never fires on the entry dip itself.
* **Time stop:** **125 bars** after the entry bar.

Plus two discipline rules: a 10-bar cooldown after an exit, and **no new
entries in the last 60 bars** of the published 1440-bar window — a fill
there would be flattened at the last close for a guaranteed ~42 bps
round-trip cost with no time for a move.

**Why half-size first:** a full-size round trip costs ~42 bps (4 bps fee
+ 2 bps slippage + ~15 bps constant-product impact per leg at the dev
window's depth). A dip that keeps falling past the entry costs the full
2.0% stop on a full-size position (~$20); on a half-size first tranche
it costs ~$10, and the scale-in only deploys the second half when the
dip is deeper *and* still oversold.

**Parameters** (grid-searched on the dev window; the stable band
`dd200_bps` 290–310 and `time_bars` 115–140 all score +$36 to +$48 with
3/4 profitable 6h blocks, so these are the band centre, not a spike):
`DD_N_BARS=60`, `DD_BPS=250`, `DD200_BARS=200`, `DD200_BPS=300`,
`RSI_BARS=9`, `RSI_MAX=30`, `TRANCHE_FRAC=0.5`, `MAX_TRANCHES=2`,
`SCALE_BPS=100`, `STOP_PCT=0.02`, `TRAIL_ATR=4.0`,
`TRAIL_ARM_PCT=0.01`, `ATR_BARS=14`, `TIME_BARS=125`,
`COOLDOWN_BARS=10`, `ENTRY_CUTOFF_BARS=60`, `MAX_SLIPPAGE_BPS=200`.

## Backtest — dev window (1440 bars, BTC −4.00% over the window)

Verified two ways, agreeing to the cent:

* **Protocol replay of `main.py` itself** (spawned as the grader does:
  `python3 -P -s main.py`, `PYTHONHASHSEED=0`; fills resolved with the
  exact integer model from the kit's `contracts/bars-protocol.ts`):
  run twice, action logs byte-for-byte identical.
* **Independent simulator** using the same fill model — it reproduces the
  official `grade-local` scores for buy-and-hold (−$44.009846) and momentum
  (−$40.924874) to the micro-USDC, so the fill model is exact.

| Metric | This bot |
|---|---|
| Net PnL | **+$45.48 (+4.55%)** |
| Final equity | $1,045.48 |
| Trades (round trips) | 3 (7 fills, 0 rejected) |
| Win rate | 100% (3 wins: +$1.61, +$3.15, +$40.72) |
| Max drawdown | **1.03%** (guardrail: ≤25%) |
| Fees paid | $1.62 |
| PnL per 6h block (mark-to-market) | bars 0–359: +$0.00; 360–719: +$1.61; 720–1079: +$31.34; 1080–1439: +$12.53 |
| Block bootstrap (1h blocks, 200 resamples, seed 0) | median +$37.59, p10 +$5.73, p90 +$81.27, 93% > $0 |
| Determinism | two runs, identical action logs (sha256 `368effc0da4d471883e1196db591557f11f16a7af4904179c7d979f969dac72c`) |

The three trades, in order:

1. **Bar 421 → 546 (+$1.61):** slow leg bought $500 at ~$65,278 after a
   300+ bps 200-bar drawdown, sold at ~$65,540 on the time stop.
2. **Bar 820 → 945 (+$3.15):** slow leg bought $500 at ~$63,859 near the
   window's second trough, sold at ~$64,313 on the time stop, just after
   the bounce peak.
3. **Bar 995 (+$502) → scale-in 1031 (+$502) → 1120 (+$40.72):** fast
   leg bought the dip at ~$62,972, averaged down at ~$62,251 when the
   dip extended a further 100+ bps while still oversold, and sold the
   combined position at ~$65,199 on the time stop, riding the window's
   one big up-leg (bars ~1031–1113).

**Baselines on the same dev window** (official `grade-local --driver process`):
buy-and-hold −$44.01 (1 trade), momentum −$40.92 (1 trade), ema-cross
−$134.95 (63 trades), rsi-bollinger −$57.37 (12 trades), adx-momentum
−$86.60 (35 trades), hold-cash $0.00 (0 trades, fails the dev gate).
Every baseline fails the dev gate (net PnL ≤ $0); this bot passes it by
+$45.48. Note `grade-local --driver process` cannot run a Python bot
(Node-only; Docker is unavailable in this environment), hence the
protocol-replay verification above.

## Comparison with the breakout entry (same simulator, same bootstrap)

| Metric | Dip-catcher v3 | Breakout-vol v1 |
|---|---|---|
| Net PnL | **+$45.48** | +$29.07 |
| Final equity | $1,045.48 | $1,029.07 |
| Round trips / fills | 3 / 7 | 2 / 4 |
| Win rate | 100% | 50% |
| Max drawdown | 1.03% | 0.62% |
| Profitable 6h blocks | **3 / 4** | 2 / 4 |
| Bootstrap median (200 resamples, seed 0) | **+$37.59** | +$23.57 |
| Bootstrap p10 / p90 | +$5.73 / +$81.27 | −$2.75 / +$52.05 |
| Bootstrap % > $0 | 93% | 86% |

Verdict against the pre-set rule (a variant only counts as better if it
beats breakout-vol on **both** bootstrap-median PnL **and** profitable
6h blocks, with dev PnL also higher): v3 beats v1 on all three —
median +$37.59 vs +$23.57, blocks 3/4 vs 2/4, dev PnL +$45.48 vs
+$29.07 — so v3 replaces v1. The margin on blocks is thin (see
fragility below).

## Fragility — read before trusting this in the race window

* **PnL concentration: 89% of the net (+$40.72 of +$45.48) comes from
  one trade** (the 995/1031 scale-in into the 1031–1113 rally). If that
  leg does not repeat in the race window, the bot is near breakeven
  (+$4.76 from the other two trades). The breakout entry has the same
  shape (its one winner is 109% of its net), so this is a property of
  the dev window, not of this bot alone — but it is the main risk.
* **The blocks win rests on +$1.61.** The third profitable block (bars
  360–719) is a single small trade. A slightly worse exit there flips
  the block count back to 2/4.
* **The slow-leg threshold has a cliff.** `DD200_BPS` is stable at
  290–310 (PnL +$43.85 to +$47.04, 3/4 blocks throughout), but 315
  kills the first trade entirely (the 200-bar drawdown at that bar is
  ~319 bps) and drops the bot back to 2/4 blocks.
* **The time stop is load-bearing.** `TIME_BARS` 115–140 all pass
  (PnL +$36.06 to +$48.25); 90 fails the block count and 180 collapses
  the PnL to +$7.83 (the second trade bleeds −$15.08 when held too
  long). 125 is the centre of the stable band, not the peak (130 scores
  +$48.25).
* **The slow leg has no RSI gate** while the fast leg does — an
  asymmetry tuned on this window. On a slow grind that keeps grinding,
  the slow leg can enter early and sit through a further decline; the
  2.0% hard stop is the only protection, and it never bound on the dev
  window (widening it to 2.5% or narrowing it to 1.5% changes nothing
  here, which means it is untested, not proven).
* **Max drawdown is worse than v1** (1.03% vs 0.62%): averaging down
  means holding a losing position longer.
* **Still below the observed competitor.** The best public entry seen on
  the leaderboard ("No-Uptick Full-Size Dip Catcher", +$67.18, rank #10
  of 1692) scores higher on the same dev window. This bot closes about
  half the gap from v1 (+$29.07) toward that mark.

## How this differs from the breakout entry

The breakout entry waits for a Donchian high break with momentum and
volatility confirmation, then rides the trend on a trailing stop. This
bot does the opposite on entries: it buys the dip itself, with no
confirmation, in two tranches — and it only exits on a stop, a
profit-armed trail, or time. On the dev window that catches three
separate legs (bars ~421, ~820, ~995) instead of one breakout
(~1057), at the cost of holding through the dip's extension on the
third leg.

## Files

* `main.py` — the bot (Python 3.13, standard library only; speaks
  `agent-fun/bars-replay/v1` via the vendored shim).
* `vendor/makefun_bars.py` — byte-for-byte copy of the kit SDK shim
  (`sdk/makefun_bars.py`, sha256
  `80452b00d2eb1e9c959e73d41cda6ca726cdbe7bfa4065d48278c22eccd276ff`).
* `LICENSE` — MIT.

Determinism: no clock, no environment, no files, no network, no randomness.
All state is the bar history the harness sent.
