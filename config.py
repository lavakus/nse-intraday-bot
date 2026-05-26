# ── TELEGRAM ────────────────────────────────────────────────────
TELEGRAM_TOKEN   = "8856759442:AAFLBXDVV9OESxbiKj-HRIOfeGFtSWqOdRM"
TELEGRAM_CHAT_ID = "8873804319"

# ── STRATEGY  (ORB + VWAP + Breakout+Retest, 150-pt scale) ─────
STRONG_SCORE   = 80     # minimum score to fire an alert  (out of 150)
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
MAX_TRADES_PER_SESSION  = 3    # hard cap per trading day
DAILY_LOSS_LIMIT_PCT    = 0.02 # 2% daily loss limit → stop trading
MAX_CONSECUTIVE_LOSSES  = 2    # block session after N losses in a row
