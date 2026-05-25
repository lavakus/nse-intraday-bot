"""
Flask web dashboard — unified view for NSE India, Gold, and Bitcoin signals.
Run with:  python dashboard.py
Then open: http://localhost:5000
"""
import os, json, threading
from flask import Flask, render_template, Response, request, jsonify
from signal_logger import (
    get_all, get_summary,
    LOG_FILE, GOLD_LOG_FILE, BTC_LOG_FILE,
    _load,
)
from run_swing   import get_swing_data
from run_options import get_options_data
from backtest    import load_backtest_results, backtest_gold, backtest_btc, save_results
from datetime import datetime, timezone, timedelta

app = Flask(__name__)

BOT_STATE_FILE = "bot_state.json"

# ── Helpers ──────────────────────────────────────────────────────

def _ist_now() -> str:
    ist = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    return ist.strftime("%d %b %Y  %H:%M:%S IST")


def _load_bot_state() -> dict:
    try:
        with open(BOT_STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"NSE": {"paused": False}, "GOLD": {"paused": False}, "BTC": {"paused": False}}


def _save_bot_state(state: dict):
    with open(BOT_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def _get_asset_signals(log_file: str) -> list:
    """Load one asset log without triggering yfinance calls (read-only)."""
    return _load(log_file)


# ── Routes ───────────────────────────────────────────────────────

@app.route("/")
def index():
    # Per-asset data (no live price refresh on page load — too slow)
    nse_signals  = list(reversed(_get_asset_signals(LOG_FILE)))
    gold_signals = list(reversed(_get_asset_signals(GOLD_LOG_FILE)))
    btc_signals  = list(reversed(_get_asset_signals(BTC_LOG_FILE)))

    # Recent combined feed (last 20 across all assets, newest first)
    all_signals = sorted(
        nse_signals + gold_signals + btc_signals,
        key=lambda r: r.get("datetime", ""),
        reverse=True
    )[:20]

    nse_summary  = get_summary(nse_signals)
    gold_summary = get_summary(gold_signals)
    btc_summary  = get_summary(btc_signals)
    overall      = get_summary(nse_signals + gold_signals + btc_signals)

    bot_state    = _load_bot_state()
    now          = _ist_now()
    swing_data   = get_swing_data()
    options_data = get_options_data()

    backtest_data = load_backtest_results()

    return render_template(
        "dashboard.html",
        # per-asset intraday
        nse_signals=nse_signals[:30],
        gold_signals=gold_signals[:30],
        btc_signals=btc_signals[:30],
        nse_summary=nse_summary,
        gold_summary=gold_summary,
        btc_summary=btc_summary,
        # unified feed
        all_signals=all_signals,
        overall=overall,
        # swing trading
        swing_week_picks=swing_data["week_picks"],
        swing_all_picks=swing_data["all_picks"],
        swing_summary=swing_data["summary"],
        # options
        options_active=options_data["active"],
        options_history=options_data["history"],
        options_summary=options_data["summary"],
        options_market=options_data["market"],
        options_expiry=options_data["expiry"],
        # backtest
        backtest=backtest_data,
        # controls
        bot_state=bot_state,
        now=now,
    )


@app.route("/api/signals")
def api_signals():
    """JSON endpoint — all assets combined."""
    asset = request.args.get("asset", "ALL").upper()
    signals = get_all(asset)
    summary = get_summary(signals)
    payload = {"asset": asset, "summary": summary, "signals": signals}
    return Response(json.dumps(payload, default=str), mimetype="application/json")


@app.route("/api/asset-status")
def api_asset_status():
    """Quick status for all three assets."""
    bot_state = _load_bot_state()
    nse  = _get_asset_signals(LOG_FILE)
    gold = _get_asset_signals(GOLD_LOG_FILE)
    btc  = _get_asset_signals(BTC_LOG_FILE)

    def _open_count(data):
        return sum(1 for r in data if r.get("status") == "OPEN")

    return jsonify({
        "NSE":  {"paused": bot_state.get("NSE",  {}).get("paused", False), "open": _open_count(nse)},
        "GOLD": {"paused": bot_state.get("GOLD", {}).get("paused", False), "open": _open_count(gold)},
        "BTC":  {"paused": bot_state.get("BTC",  {}).get("paused", False), "open": _open_count(btc)},
    })


@app.route("/api/swing")
def api_swing():
    """JSON endpoint for swing picks."""
    data = get_swing_data()
    return Response(json.dumps(data, default=str), mimetype="application/json")


@app.route("/api/control/<asset>/<action>", methods=["POST"])
def api_control(asset: str, action: str):
    """Pause / resume a bot. POST /api/control/GOLD/pause"""
    asset  = asset.upper()
    action = action.lower()
    if asset not in ("NSE", "GOLD", "BTC") or action not in ("pause", "resume"):
        return jsonify({"error": "invalid"}), 400

    state = _load_bot_state()
    state.setdefault(asset, {})["paused"] = (action == "pause")
    _save_bot_state(state)
    return jsonify({"asset": asset, "paused": state[asset]["paused"]})


@app.route("/api/backtest")
def api_backtest():
    """Return saved backtest results as JSON."""
    data = load_backtest_results()
    return Response(json.dumps(data, default=str), mimetype="application/json")


@app.route("/api/run-backtest", methods=["POST"])
def api_run_backtest():
    """Trigger a fresh backtest run in background thread."""
    days = int(request.json.get("days", 50)) if request.is_json else 50

    def _run():
        try:
            gold = backtest_gold(days)
            btc  = backtest_btc(days)
            save_results(gold, btc, days)
        except Exception as e:
            print(f"[BACKTEST] Background run error: {e}")

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return jsonify({"status": "running", "days": days,
                    "message": "Backtest started — refresh in ~2 minutes"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("=" * 55)
    print("  Unified Trading Bot Dashboard — NSE + GOLD + BTC")
    print(f"  Open: http://localhost:{port}")
    print("=" * 55)
    app.run(host="0.0.0.0", port=port, debug=False)
