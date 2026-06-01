# ── TELEGRAM ────────────────────────────────────────────────────
TELEGRAM_TOKEN   = "8856759442:AAFLBXDVV9OESxbiKj-HRIOfeGFtSWqOdRM"
TELEGRAM_CHAT_ID = "8873804319"

# ── STRATEGY  (ORB + VWAP + Breakout+Retest, 150-pt scale) ─────
STRONG_SCORE   = 95     # minimum score to fire an alert  (out of 150) — ~9.5/10
SCAN_WORKERS   = 6      # parallel threads
SCAN_INTERVAL  = 5      # minutes between scans during market hours
MAX_STOCKS     = 250    # scan top-N from live NSE list

# ── RISK MANAGEMENT ─────────────────────────────────────────────
CAPITAL        = 100_000   # Rs — account size for position sizing
RISK_PCT       = 0.01      # 1.0% of capital per trade  (Rs 1,000 on Rs 1L)

# ── MARKET HOURS (IST) ──────────────────────────────────────────
MARKET_OPEN    = "09:15"
MARKET_CLOSE   = "15:30"

# ── SESSION LIMITS ──────────────────────────────────────────────
MAX_TRADES_PER_SESSION  = 50   # effectively unlimited — alert ALL qualifying stocks each day
DAILY_LOSS_LIMIT_PCT    = 0.02 # 2% daily loss limit → stop trading
MAX_CONSECUTIVE_LOSSES  = 2    # block session after N losses in a row

# ── SWING TRADING (5-Layer SMC, score out of 10) ─────────────────
SWING_MIN_SCORE      = 7.0    # minimum score to generate a signal
SWING_STOP_LOSS_PCT  = 0.025  # 2.5% maximum stop loss
SWING_TARGET1_PCT    = 0.06   # 6%  first target (book 50%)
SWING_TARGET2_PCT    = 0.10   # 10% final target
SWING_MAX_HOLD_DAYS  = 15     # force-close after N days
SWING_TOP_N          = 5      # top picks to alert per day
SWING_SCAN_STOCKS    = 200    # max stocks to scan per day
CALL_OI_INCREASE_MIN = 0.30   # 30% call OI increase → Layer 5 pass
PCR_MIN              = 0.8    # put-call ratio lower bound
PCR_MAX              = 1.3    # put-call ratio upper bound
