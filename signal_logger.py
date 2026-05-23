"""
Logs every alert to signals_log.json.
Checks live price to update status: TARGET HIT / SL HIT / OPEN.
"""
import json, os
from datetime import datetime

LOG_FILE   = "signals_log.json"
EVAL_FILE  = "evaluations_log.jsonl"   # one JSON per line — blocked/near-miss log

# When running on Render (no local file), fetch from GitHub raw URL
GITHUB_RAW = os.environ.get(
    "SIGNALS_JSON_URL",
    "https://raw.githubusercontent.com/lavakus/nse-intraday-bot/main/signals_log.json"
)


def _load() -> list:
    # 1) Try local file
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    # 2) Fallback: fetch from GitHub (for Render / remote host)
    try:
        import requests as _req
        r = _req.get(GITHUB_RAW, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return []


def _save(data: list):
    with open(LOG_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)


def log_signal(sig: dict):
    """Save a new alert to the log file."""
    data = _load()
    tp   = sig.get("trade_params", {})

    record = {
        "id":             len(data) + 1,
        "datetime":       datetime.now().strftime("%Y-%m-%d %H:%M"),
        "date":           datetime.now().strftime("%Y-%m-%d"),
        "symbol":         sig["symbol"],
        "direction":      sig["direction"],
        "signal":         sig.get("signal", "BUY" if sig["direction"] == "LONG" else "SELL"),
        "score":          sig["score"],
        "score_pct":      sig.get("score_pct", round(sig["score"] / 150 * 100, 1)),
        "signal_strength": sig.get("signal_strength", "GOOD"),
        "kill_zone":      sig.get("kill_zone", "?"),
        "phase_scores":   sig.get("phase_scores", {}),
        "must_have_checklist": sig.get("must_have_checklist", {}),
        "entry":          tp.get("entry", sig.get("entry")),
        "t1":             tp.get("t1",    sig.get("t1")),
        "target":         tp.get("t2",    sig.get("target", sig.get("t2"))),
        "sl":             tp.get("sl",    sig.get("sl")),
        "rr":             tp.get("rr_ratio", sig.get("rr")),
        "sl_pct":         tp.get("sl_pct",   sig.get("sl_pct")),
        "rsi":            sig.get("rsi", 0),
        "vwap":           sig.get("vwap", 0),
        "vol_ratio":      sig.get("vol_ratio", 0),
        "reasons":        sig.get("reasons", []),
        "status":         "OPEN",
        "exit_price":     None,
        "pnl_pts":        None,
        "pnl_pct":        None,
    }
    data.append(record)
    _save(data)
    print(f"[LOG] Saved signal #{record['id']} — {record['symbol']} "
          f"{record['signal']} score={record['score']}/150")


def log_evaluation(sym: str, score: int, blocked_reason: str, phase_scores: dict):
    """
    Log a near-miss evaluation (passed Phase 1 but failed hard rule or score).
    Appended to evaluations_log.jsonl for weekly review.
    """
    try:
        entry = {
            "datetime":      datetime.now().strftime("%Y-%m-%d %H:%M"),
            "symbol":        sym,
            "score":         score,
            "blocked_reason": blocked_reason,
            "phase_scores":  phase_scores,
        }
        with open(EVAL_FILE, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception:
        pass


def update_statuses() -> list:
    """Fetch live prices and update status of all OPEN signals."""
    import yfinance as yf
    data    = _load()
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
                    rec.update(status="TARGET HIT", exit_price=price,
                               pnl_pts=round(price - entry, 2),
                               pnl_pct=round((price - entry) / entry * 100, 2))
                    changed += 1
                elif price <= sl:
                    rec.update(status="SL HIT", exit_price=price,
                               pnl_pts=round(price - entry, 2),
                               pnl_pct=round((price - entry) / entry * 100, 2))
                    changed += 1
                else:
                    rec["exit_price"] = price   # live price for open trade
            else:  # SHORT
                if price <= target:
                    rec.update(status="TARGET HIT", exit_price=price,
                               pnl_pts=round(entry - price, 2),
                               pnl_pct=round((entry - price) / entry * 100, 2))
                    changed += 1
                elif price >= sl:
                    rec.update(status="SL HIT", exit_price=price,
                               pnl_pts=round(entry - price, 2),
                               pnl_pct=round((entry - price) / entry * 100, 2))
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
    total = len(data)
    if total == 0:
        return {"total": 0, "wins": 0, "losses": 0,
                "open": 0, "win_rate": 0, "total_pnl": 0,
                "avg_score": 0, "excellent": 0, "good": 0, "weak": 0}

    wins   = [r for r in data if r["status"] == "TARGET HIT"]
    losses = [r for r in data if r["status"] == "SL HIT"]
    open_  = [r for r in data if r["status"] == "OPEN"]
    closed = len(wins) + len(losses)
    win_rate  = round(len(wins) / closed * 100, 1) if closed > 0 else 0
    total_pnl = round(sum(r["pnl_pts"] or 0 for r in data if r.get("pnl_pts")), 2)
    avg_score = round(sum(r.get("score", 0) for r in data) / total, 1)

    excellent = sum(1 for r in data if r.get("signal_strength") == "EXCELLENT")
    good      = sum(1 for r in data if r.get("signal_strength") == "GOOD")
    weak      = sum(1 for r in data if r.get("signal_strength") == "WEAK")

    return {
        "total":     total,
        "wins":      len(wins),
        "losses":    len(losses),
        "open":      len(open_),
        "win_rate":  win_rate,
        "total_pnl": total_pnl,
        "avg_score": avg_score,
        "excellent": excellent,
        "good":      good,
        "weak":      weak,
    }
