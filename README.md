# Breakout / Volatility-Expansion BTC Bot — make.fun `btc-race-24h-20261115-0828`

Long-only 1-minute cbBTC/USDC bot. Starts with $1,000 USDC, one position,
100% of equity per trade, fills at the next bar's open.

## Strategy

**Entry — a genuine Donchian breakout, not flat-bar noise.** All four must hold
at a bar's close:

1. Close breaks above the highest **high** of the prior 30 one-minute bars
   (Donchian channel).
2. Momentum: the same close is at least **70 bps** above the close 30 bars ago.
3. Volatility is alive: **ATR(14) ≥ 4 bps** of price. Dead/flat bars
   (`open == high == low == close`) never qualify.
4. The breakout bar closed near its high: `close >= high - 0.5 * ATR`
   (a spike that faded inside the minute does not count).

**Exit — trailing ATR stop.** Stop = highest close since entry minus
**3.0 × ATR(14)**, ratcheted up only. A close at or below it sells the whole
position. Plus two discipline rules: a 10-bar cooldown after an exit (no
re-entry on the same noise), and **no new entries in the last 60 bars** of
the published 1440-bar window — a fill there would be flattened at the last
close for a guaranteed ~42 bps round-trip cost with no time for a move.

**Why so selective:** a full-size round trip costs ~42 bps (4 bps fee +
2 bps slippage + ~15 bps constant-product impact per leg at the dev
window's depth), while the median 1-minute move is ~12 bps. A trade only
pays that cost when a multi-bar trend is actually under way.

**Parameters** (grid-searched on the dev window; the plateau N=28–30,
momentum 70–80 bps, trail 2.8–3.5×ATR all score +$27 to +$30, so these are
the plateau centre, not a single-bar spike): `DONCHIAN_BARS=30`,
`MOMENTUM_BPS=70`, `ATR_BARS=14`, `ATR_MIN_BPS=4`, `TRAIL_ATR=3.0`,
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
| Net PnL | **+$29.07 (+2.91%)** |
| Trades (round trips) | 2 (4 fills, 0 rejected) |
| Win rate | 50% (1 win +$31.82, 1 loss −$2.75) |
| Max drawdown | **0.62%** (guardrail: ≤25%) |
| PnL first half (bars 0–719) | −$2.75 |
| PnL second half (bars 720–1439) | +$31.82 |
| Determinism | two runs, identical action logs (sha256 `bd4f0145f518716d1e9eb450d6db0e6843b7d1a273fafe42367dffaef3c0514c`) |

The winning trade caught the window's one big up-leg: bought ~$63,086 at
bar 1057, sold ~$65,152 at bar 1131 (+3.2% before costs, held 75 bars).
The losing trade was a small false breakout (+$65,823 → $65,694, −$2.75
after costs, held 11 bars) — the trailing stop kept the loss to one
round-trip cost plus a small adverse move.

**Baselines on the same dev window** (official `grade-local --driver process`):
buy-and-hold −$44.01 (1 trade), momentum −$40.92 (1 trade), ema-cross
−$134.95 (63 trades), rsi-bollinger −$57.37 (12 trades), adx-momentum
−$86.60 (35 trades), hold-cash $0.00 (0 trades, fails the dev gate).
Every baseline fails the dev gate (net PnL ≤ $0); this bot passes it by
+$29.07. Note `grade-local --driver process` cannot run a Python bot
(Node-only; Docker is unavailable in this environment), hence the
protocol-replay verification above.

## How this differs from the momentum baseline

`baselines/momentum/main.ts` rebalances every 24 bars to the asset with the
best trailing 24-bar return; on a single-asset universe that is just
"buy on batch 24 and hold" — it holds through the whole −4% downtrend
(−$40.92). This bot instead:

* never holds through a downtrend by default — it is flat unless a breakout
  is under way, and exits on a trailing stop;
* enters only on a **range breakout + momentum + volatility-expansion**
  confirmation (Donchian high, +70 bps / 30 bars, ATR floor, close-near-high),
  not on a trailing-return ranking;
* manages risk per-trade with an ATR trailing stop instead of holding to
  the end of the window, so a false breakout costs ~$3, not the full
  downtrend.

## Files

* `main.py` — the bot (Python 3.13, standard library only; speaks
  `agent-fun/bars-replay/v1` via the vendored shim).
* `vendor/makefun_bars.py` — byte-for-byte copy of the kit SDK shim
  (`sdk/makefun_bars.py`, sha256
  `80452b00d2eb1e9c959e73d41cda6ca726cdbe7bfa4065d48278c22eccd276ff`).
* `LICENSE` — MIT.

Determinism: no clock, no environment, no files, no network, no randomness.
All state is the bar history the harness sent.
