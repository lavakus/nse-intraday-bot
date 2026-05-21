"""
Logs every alert to signals_log.json
Checks live price to update status: TARGET HIT / SL HIT / OPEN
"""
import json, os
from datetime import datetime

LOG_FILE = "signals_log.json"


def _load() -> list:
    if not os.path.exists(LOG_FILE):
        return []
    try:
        with open(LOG_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []


def _save(data: list):
    with open(LOG_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)


def log_signal(sig: dict):
    """Save a new alert to the log file."""
    data = _load()
    record = {
        "id":        len(data) + 1,
        "datetime":  datetime.now().strftime("%Y-%m-%d %H:%M"),
        "date":      datetime.now().strftime("%Y-%m-%d"),
        "symbol":    sig["symbol"],
        "direction": sig["direction"],
        "score":     sig["score"],
        "entry":     sig["entry"],
        "target":    sig["target"],
        "sl":        sig["sl"],
        "rr":        sig["rr"],
        "rsi":       sig.get("rsi", 0),
        "vwap":      sig.get("vwap", 0),
        "vol_ratio": sig.get("vol_ratio", 0),
        "reasons":   sig.get("reasons", []),
        "status":    "OPEN",      # OPEN / TARGET HIT / SL HIT
        "exit_price": None,
        "pnl_pts":   None,
        "pnl_pct":   None,
    }
    data.append(record)
    _save(data)
    print(f"[LOG] Saved signal #{record['id']} — {record['symbol']}")


def update_statuses():
    """Check live prices and update status of all OPEN signals."""
    import yfinance as yf
    data = _load()
    changed = 0

    for rec in data:
        if rec["status"] != "OPEN":
            continue
        try:
            ticker = yf.Ticker(f"{rec['symbol']}.NS")
            price  = float(ticker.fast_info["last_price"])
            entry  = float(rec["entry"])
            target = float(rec["target"])
            sl     = float(rec["sl"])
            d      = rec["direction"]

            if d == "LONG":
                if price >= target:
                    rec["status"]     = "TARGET HIT"
                    rec["exit_price"] = price
                    rec["pnl_pts"]    = round(price - entry, 2)
                    rec["pnl_pct"]    = round((price - entry) / entry * 100, 2)
                    changed += 1
                elif price <= sl:
                    rec["status"]     = "SL HIT"
                    rec["exit_price"] = price
                    rec["pnl_pts"]    = round(price - entry, 2)
                    rec["pnl_pct"]    = round((price - entry) / entry * 100, 2)
                    changed += 1
                else:
                    rec["exit_price"] = price   # live price for open trades
            else:  # SHORT
                if price <= target:
                    rec["status"]     = "TARGET HIT"
                    rec["exit_price"] = price
                    rec["pnl_pts"]    = round(entry - price, 2)
                    rec["pnl_pct"]    = round((entry - price) / entry * 100, 2)
                    changed += 1
                elif price >= sl:
                    rec["status"]     = "SL HIT"
                    rec["exit_price"] = price
                    rec["pnl_pts"]    = round(entry - price, 2)
                    rec["pnl_pct"]    = round((entry - price) / entry * 100, 2)
                    changed += 1
                else:
                    rec["exit_price"] = price
        except Exception:
            pass

    if changed:
        _save(data)
    return data


def get_all() -> list:
    return update_statuses()


def get_summary(data: list) -> dict:
    total    = len(data)
    if total == 0:
        return {"total": 0, "wins": 0, "losses": 0,
                "open": 0, "win_rate": 0, "total_pnl": 0}

    wins     = [r for r in data if r["status"] == "TARGET HIT"]
    losses   = [r for r in data if r["status"] == "SL HIT"]
    open_    = [r for r in data if r["status"] == "OPEN"]
    closed   = len(wins) + len(losses)
    win_rate = round(len(wins) / closed * 100, 1) if closed > 0 else 0
    total_pnl = round(sum(r["pnl_pts"] or 0 for r in data if r["pnl_pts"]), 2)

    return {
        "total":     total,
        "wins":      len(wins),
        "losses":    len(losses),
        "open":      len(open_),
        "win_rate":  win_rate,
        "total_pnl": total_pnl,
    }
