"""
Flask web dashboard — shows all past signals with live status.
Run with:  python dashboard.py
Then open: http://localhost:5000
"""
import os
from flask import Flask, render_template
from signal_logger import get_all, get_summary
from datetime import datetime, timezone, timedelta

app = Flask(__name__)


def _ist_now() -> str:
    ist = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    return ist.strftime("%d %b %Y  %H:%M:%S IST")


@app.route("/")
def index():
    signals  = get_all()          # fetches live prices + updates statuses
    summary  = get_summary(signals)
    now      = _ist_now()
    return render_template("dashboard.html",
                           signals=signals,
                           summary=summary,
                           now=now)


@app.route("/api/signals")
def api_signals():
    """JSON endpoint — useful for future integrations."""
    import json
    from flask import Response
    signals = get_all()
    summary = get_summary(signals)
    payload = {"summary": summary, "signals": signals}
    return Response(json.dumps(payload, default=str),
                    mimetype="application/json")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("=" * 50)
    print("  NSE Intraday Bot — Dashboard")
    print(f"  Open: http://localhost:{port}")
    print("=" * 50)
    app.run(host="0.0.0.0", port=port, debug=False)
