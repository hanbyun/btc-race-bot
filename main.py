"""Dip-catcher bot for make.fun btc-race-24h-20261115-0828.

Buys sharp intraday dips at full size with NO uptick confirmation, then
averages down once if the dip extends, and exits on a hard stop, a
profit-armed ATR trail, or a time stop. Long only, one position.

Entry -- two drawdown legs, either one can fire on its own:
  * Fast leg: the close is at least 250 bps below the highest HIGH of the
    prior 60 one-minute bars, and RSI(9) < 30 (Wilder). No uptick check:
    the buy is placed on the dip bar's close itself.
  * Slow leg: the close is at least 300 bps below the highest HIGH of the
    prior 200 one-minute bars. No RSI gate on this leg: a 200-bar
    drawdown of that depth is itself the oversold signal, and on the dev
    window the RSI gate would have blocked the leg's first trade.
  Both legs buy half the cash (50%). The other half stays in cash so the
  bot can average down once.
Scale-in -- while in a position, if RSI(9) < 30 and the close is at least
  100 bps below the position's average entry close, buy with all remaining
  cash (second and last tranche). This turns a dip that keeps dipping
  into a lower average cost instead of a stopped-out loss, as long as the
  hard stop below is not hit first.
Exit -- the whole position is sold on the first of:
  * hard stop: close at or below the average entry close minus 2.0%;
  * trailing stop: peak close since entry minus 4.0 * ATR(14), armed only
    once the current close is at least 1.0% above the average entry
    (so the trail never fires on the entry dip itself);
  * time stop: 125 bars after the entry bar.
  Plus two discipline rules: a 10-bar cooldown after an exit, and no new
  entries in the last 60 bars of the published 1440-bar window (a fill
  there would be flattened at the last close for a guaranteed ~42 bps
  round-trip cost with no time for a move to develop).

Sizing and cost: a full round trip costs ~42 bps (4 bps fee + 2 bps
slippage + ~15 bps constant-product impact per leg at the dev window's
depth), so a dip leg only pays it when the drawdown is deep enough that
a bounce of that size is plausible. The half-size first tranche caps the
loss on a dip that keeps falling to the 2.0% stop at ~1.0% of equity.

Determinism: no clock, no environment, no files, no network, no random
numbers. All state is the bar history the harness sent; all arithmetic is
on the integer prices the harness sends, with ATR(14) as a plain mean of
true ranges and RSI(9) as Wilder smoothing. The same input therefore
produces the same orders, byte for byte, on every run.

Dev-window backtest (official grade-local, driver process; simulator in
tuning matched it to the cent): net PnL +$45.48 (+4.55%), 3 trades,
win rate 100%, max drawdown 1.03%. Baselines on the same window:
buy-and-hold -$44.01, momentum -$40.92, ema-cross -$134.95,
rsi-bollinger -$57.37, adx-momentum -$86.60, hold-cash $0.00.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))

import makefun_bars

SYMBOL = "CBBTC"

# --- tuned parameters (grid-searched on the dev window; the stable band
# dd200_bps 290-310 and time_bars 115-140 all score +$36 to +$48 with
# 3/4 profitable 6h blocks, so these are the band centre, not a spike) ---
DD_N_BARS = 60            # fast-leg drawdown lookback, in 1-minute bars
DD_BPS = 250              # fast-leg drawdown vs highest high, in bps
DD200_BARS = 200          # slow-leg drawdown lookback, in 1-minute bars
DD200_BPS = 300           # slow-leg drawdown vs highest high, in bps
RSI_BARS = 9              # RSI lookback (Wilder)
RSI_MAX = 30              # fast-leg / scale-in oversold ceiling
TRANCHE_FRAC = 0.5        # first tranche: half the cash
MAX_TRANCHES = 2          # one scale-in at most
SCALE_BPS = 100           # scale-in once close is this far below avg entry
STOP_PCT = 0.02           # hard stop vs average entry close
TRAIL_ATR = 4.0           # trailing stop distance, in ATRs
TRAIL_ARM_PCT = 0.01      # trail arms only once close is this far above avg entry
ATR_BARS = 14             # ATR lookback
TIME_BARS = 125           # time stop: bars after the entry bar
COOLDOWN_BARS = 10        # bars to wait after an exit before re-entering
ENTRY_CUTOFF_BARS = 60    # no new entries in the last 60 bars
MAX_SLIPPAGE_BPS = 200    # wide: worst 1-min move on dev was ~80 bps,
                          # plus ~16 bps impact + 2 bps slippage
WARMUP_BARS = 90          # no decisions before this bar (history build-up)
WINDOW_BARS = 1440        # published window length (RULES.txt)

closes = []   # close per batch seq (int price, scale 1e5)
highs = []    # high per batch seq
lows = []     # low per batch seq

in_position = False
entry_close = 0.0         # close of the first tranche's bar
entry_bar = -1
peak_since_entry = 0.0    # highest close since entry
tranches = 0              # tranches held (1 after entry, 2 after scale-in)
avg_entry = 0.0           # average entry close across tranches
last_exit_seq = -10 ** 9

_rsi_gain = None          # Wilder RSI(9) state
_rsi_loss = None
_rsi_first_changes = []
_rsi_last_close = None


def _rsi_push(c):
    """Feed one close into the Wilder RSI(9) state."""
    global _rsi_gain, _rsi_loss, _rsi_last_close
    if _rsi_last_close is not None:
        ch = c - _rsi_last_close
        up = ch if ch > 0 else 0.0
        dn = -ch if ch < 0 else 0.0
        if _rsi_gain is None:
            _rsi_first_changes.append(ch)
            if len(_rsi_first_changes) == RSI_BARS:
                _rsi_gain = sum(x for x in _rsi_first_changes if x > 0) / RSI_BARS
                _rsi_loss = sum(-x for x in _rsi_first_changes if x < 0) / RSI_BARS
        else:
            _rsi_gain = (_rsi_gain * (RSI_BARS - 1) + up) / RSI_BARS
            _rsi_loss = (_rsi_loss * (RSI_BARS - 1) + dn) / RSI_BARS
    _rsi_last_close = c


def _rsi():
    """Current RSI(9), or None before the first 9 changes are in."""
    if _rsi_gain is None:
        return None
    m = _rsi_gain + _rsi_loss
    return 50.0 if m == 0 else 100.0 * _rsi_gain / m


def _true_range(i):
    """True range of bar i in price units (needs a previous close)."""
    if i == 0:
        return highs[0] - lows[0]
    prev = closes[i - 1]
    return max(highs[i] - lows[i], abs(highs[i] - prev), abs(lows[i] - prev))


def on_batch(state, batch):
    global in_position, entry_close, entry_bar, peak_since_entry
    global tranches, avg_entry, last_exit_seq
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
    _rsi_push(c)

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

    if i < WARMUP_BARS:
        return []
    if i >= WINDOW_BARS - 1:
        return []  # last batch: any order would be rejected (after_end)

    holding = state.positions.get(SYMBOL)

    if in_position and holding is None:
        # Our buy never filled (rejected at the next open): drop the
        # phantom position so a fresh dip can re-enter.
        in_position = False

    if not in_position:
        if holding is not None:
            # Position appeared without our entry (should not happen);
            # adopt it as a single tranche so the exits still manage it.
            in_position = True
            entry_close = c
            entry_bar = i
            peak_since_entry = c
            tranches = 1
            avg_entry = c
        else:
            if i - last_exit_seq < COOLDOWN_BARS:
                return []
            if i >= WINDOW_BARS - ENTRY_CUTOFF_BARS:
                return []
            # ---- entry: fast dip leg (drawdown + RSI oversold) ----
            dip = False
            if i >= DD_N_BARS:
                hi = max(highs[i - DD_N_BARS:i])
                if c * 10000 <= hi * (10000 - DD_BPS):
                    dip = True
                    r = _rsi()
                    if r is None or r >= RSI_MAX:
                        dip = False
            # ---- entry: slow drawdown leg (200-bar drawdown, no RSI gate) ----
            if i >= DD200_BARS:
                hi200 = max(highs[i - DD200_BARS:i])
                if c * 10000 <= hi200 * (10000 - DD200_BPS):
                    dip = True
            if dip:
                notional = int(state.cash * TRANCHE_FRAC)
                room = state.weight_room(SYMBOL)
                if room < notional:
                    notional = room
                if notional < int(state.hello["fees"]["min_notional_quote_units"]):
                    return []
                in_position = True
                entry_close = c
                entry_bar = i
                peak_since_entry = c
                tranches = 1
                avg_entry = c
                return [{
                    "side": "buy",
                    "symbol": SYMBOL,
                    "notional_quote_units": notional,
                    "max_slippage_bps": MAX_SLIPPAGE_BPS,
                }]
            return []

    # ---- scale-in: a further dip while still oversold ----
    if holding is not None and in_position and tranches < MAX_TRANCHES:
        r = _rsi()
        if (r is not None and r < RSI_MAX
                and c <= avg_entry * (1 - SCALE_BPS / 10000.0)):
            size = min(state.cash, state.weight_room(SYMBOL))
            if size >= int(state.hello["fees"]["min_notional_quote_units"]):
                avg_entry = (avg_entry * tranches + c) / (tranches + 1)
                tranches += 1
                if c > peak_since_entry:
                    peak_since_entry = c
                return [{
                    "side": "buy",
                    "symbol": SYMBOL,
                    "notional_quote_units": size,
                    "max_slippage_bps": MAX_SLIPPAGE_BPS,
                }]

    # ---- in position: exits ----
    if c > peak_since_entry:
        peak_since_entry = c
    ref = avg_entry if tranches > 0 else entry_close
    do_sell = False
    # Hard stop vs the average entry close.
    if c <= ref * (1 - STOP_PCT):
        do_sell = True
    # Trailing ATR stop, armed only once the close is 1% above avg entry.
    tstop = peak_since_entry - TRAIL_ATR * a
    if c >= ref * (1 + TRAIL_ARM_PCT) and c <= tstop:
        do_sell = True
    # Time stop: 125 bars after the entry bar.
    if (i - entry_bar) >= TIME_BARS:
        do_sell = True
    if holding is not None and do_sell:
        in_position = False
        tranches = 0
        last_exit_seq = i
        return [{
            "side": "sell",
            "symbol": SYMBOL,
            "qty": holding.qty,
            "max_slippage_bps": MAX_SLIPPAGE_BPS,
        }]
    return []


makefun_bars.run(on_batch)
