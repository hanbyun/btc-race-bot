"""Breakout / volatility-expansion bot for make.fun btc-race-24h-20261115-0828.

Strategy (long only, one position, 100% of equity per trade):
  * Entry -- a genuine Donchian breakout, not flat-bar noise:
      - close breaks above the highest HIGH of the prior 30 one-minute bars;
      - momentum: the same close is at least 70 bps above the close 30 bars ago;
      - volatility is alive: ATR(14) is at least 4 bps of price (flat / dead
        bars, where open == high == low == close, never qualify);
      - the breakout bar closed near its high: close >= high - 0.5 * ATR
        (a spike that faded inside the minute does not count).
  * Exit -- a trailing ATR stop, plus momentum-exhaustion discipline:
      - stop = highest close since entry minus 3.0 * ATR(14), ratcheted up
        only (never down); a close at or below it sells the whole position.
      - no new entries in the last 60 bars of the published 1440-bar window:
        a fill there would be flattened at the last close for a guaranteed
        ~42 bps round-trip cost with no time for a move to develop.
      - 10-bar cooldown after an exit, so one failed breakout cannot
        re-enter on the same noise.
  * Sizing: one full-size buy (all cash, capped by max_weight_bps), one
    full sell. Fills land at the next bar's open, so every trade must catch
    a move larger than the ~42 bps full-size round-trip cost (4 bps fee +
    2 bps slippage + ~15 bps impact per leg at the dev window's depth);
    the filters above exist to make sure it only pays that cost when a
    multi-bar trend is actually under way.

Determinism: no clock, no environment, no files, no network, no random
numbers. All state is the bar history the harness sent; all arithmetic is
on the integer prices the harness sends, with ATR as a plain mean of true
ranges. The same input therefore produces the same orders, byte for byte,
on every run.

Dev-window backtest (official grade-local, driver process; simulator in
tuning matched it to the cent): net PnL +$29.07 (+2.91%), 2 trades,
win rate 50%, max drawdown 0.62%. Baselines on the same window:
buy-and-hold -$44.01, momentum -$40.92, ema-cross -$134.95,
rsi-bollinger -$57.37, adx-momentum -$86.60, hold-cash $0.00.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))

import makefun_bars

SYMBOL = "CBBTC"

# --- tuned parameters (grid-searched on the dev window; the plateau
# N=28-30, momentum 70-80 bps, trail 2.8-3.5 x ATR all score +$27 to +$30,
# so these are the plateau centre, not a single-bar spike) ---
DONCHIAN_BARS = 30          # breakout lookback, in 1-minute bars
MOMENTUM_BPS = 70           # min close vs close 30 bars ago, in bps
ATR_BARS = 14               # ATR lookback
ATR_MIN_BPS = 4             # min ATR(14) as a share of price, in bps
TRAIL_ATR = 3.0             # trailing stop distance, in ATRs
COOLDOWN_BARS = 10          # bars to wait after an exit before re-entering
ENTRY_CUTOFF_BARS = 60      # no new entries in the last 60 bars
MAX_SLIPPAGE_BPS = 200      # wide: worst 1-min move on dev was ~80 bps,
                            # plus ~16 bps impact + 2 bps slippage
WINDOW_BARS = 1440          # published window length (RULES.txt)

closes = []   # close per batch seq (int price, scale 1e5), None before first bar
highs = []    # high per batch seq
lows = []     # low per batch seq
atr = []      # ATR(14) per batch seq, as a float of price units

in_position = False
peak_close = 0        # highest close since entry
trail_px = 0.0        # trailing stop price
last_exit_seq = -10 ** 9


def _true_range(i):
    """True range of bar i in price units (needs a previous close)."""
    if i == 0:
        return highs[0] - lows[0]
    prev = closes[i - 1]
    return max(highs[i] - lows[i], abs(highs[i] - prev), abs(lows[i] - prev))


def on_batch(state, batch):
    global in_position, peak_close, trail_px, last_exit_seq
    if state.warming_up:
        return []

    bar = state.latest.get(SYMBOL)
    c = state.close(SYMBOL)
    if bar is None or c is None:
        # No bar for this symbol this minute: keep history aligned by
        # repeating the last close (a flat bar), never invent a price.
        c = closes[-1] if closes else 0
        h = l = c
    else:
        h = int(bar["h"])
        l = int(bar["l"])
    closes.append(c)
    highs.append(h)
    lows.append(l)

    i = state.seq
    # ATR(14): plain mean of true ranges over bars max(1, i-13) .. i.
    lo = i - ATR_BARS + 1
    if lo < 1:
        lo = 1
    total = 0
    count = 0
    for j in range(lo, i + 1):
        total += _true_range(j)
        count += 1
    a = total / count if count else 0.0
    atr.append(a)

    if i < DONCHIAN_BARS + 1:
        return []
    if i >= WINDOW_BARS - 1:
        return []  # last batch: any order would be rejected (after_end)

    holding = state.positions.get(SYMBOL)

    if in_position and holding is None:
        # Our buy never filled (rejected at the next open): drop the
        # phantom position so a fresh breakout can re-enter.
        in_position = False

    if not in_position:
        if holding is not None:
            # Position appeared without our entry (should not happen);
            # track it so the trailing stop still manages it.
            in_position = True
            peak_close = c
            trail_px = c - TRAIL_ATR * a
        else:
            if i - last_exit_seq < COOLDOWN_BARS:
                return []
            if i >= WINDOW_BARS - ENTRY_CUTOFF_BARS:
                return []
            # Donchian: close above the highest high of the prior 30 bars.
            if c <= max(highs[i - DONCHIAN_BARS:i]):
                return []
            # Momentum: close at least 70 bps above the close 30 bars ago.
            then = closes[i - DONCHIAN_BARS]
            if c * 10000 < then * (10000 + MOMENTUM_BPS):
                return []
            # Volatility alive: ATR at least 4 bps of price (kills flat bars).
            if a * 10000 < ATR_MIN_BPS * c:
                return []
            # Breakout bar closed near its high (no faded spike).
            if c < h - 0.5 * a:
                return []
            notional = state.cash
            room = state.weight_room(SYMBOL)
            if room < notional:
                notional = room
            if notional < int(state.hello["fees"]["min_notional_quote_units"]):
                return []
            in_position = True
            peak_close = c
            trail_px = c - TRAIL_ATR * a
            return [{
                "side": "buy",
                "symbol": SYMBOL,
                "notional_quote_units": notional,
                "max_slippage_bps": MAX_SLIPPAGE_BPS,
            }]

    # In position: ratchet the trailing stop up with the peak close.
    if c > peak_close:
        peak_close = c
    stop = peak_close - TRAIL_ATR * a
    if stop > trail_px:
        trail_px = stop
    if holding is not None and c <= trail_px:
        in_position = False
        last_exit_seq = i
        return [{
            "side": "sell",
            "symbol": SYMBOL,
            "qty": holding.qty,
            "max_slippage_bps": MAX_SLIPPAGE_BPS,
        }]
    return []


makefun_bars.run(on_batch)
