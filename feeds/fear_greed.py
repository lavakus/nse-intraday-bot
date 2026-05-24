"""
Fear & Greed Index — alternative.me free public API.
Used by BTC strategy: ideal range 25–60 for longs.
"""
import requests

URL = "https://api.alternative.me/fng/?limit=1"


def get_fear_greed() -> dict:
    """
    Returns current Fear & Greed index value and classification.
    Scores 25–60 are ideal for bullish BTC entries.
    """
    try:
        r    = requests.get(URL, timeout=8)
        data = r.json()
        item = data["data"][0]
        value = int(item["value"])
        label = item["value_classification"]
        return {
            "value":          value,
            "label":          label,
            "extreme_fear":   value < 25,
            "fear":           25 <= value < 45,
            "neutral":        45 <= value <= 55,
            "greed":          55 < value <= 75,
            "extreme_greed":  value > 75,
            "in_ideal_range": 25 <= value <= 60,  # ideal for longs
            "error":          None,
        }
    except Exception as e:
        return {
            "value": 50, "label": "Neutral",
            "extreme_fear": False, "fear": False, "neutral": True,
            "greed": False, "extreme_greed": False, "in_ideal_range": True,
            "error": str(e),
        }
