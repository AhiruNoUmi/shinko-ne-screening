import os, json, requests, traceback
from datetime import datetime
import pytz

JST        = pytz.timezone("Asia/Tokyo")
TODAY      = datetime.now(JST).strftime("%Y/%m/%d")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")

STOCKS = [
    {"code": "6857.T", "name": "アドバンテスト",    "conds": [0,1,1,1,1,1,1,1]},
    {"code": "4062.T", "name": "イビデン",           "conds": [0,1,1,1,1,1,1,1]},
    {"code": "5805.T", "name": "SWCC",               "conds": [0,1,0,1,1,1,1,1]},
    {"code": "5803.T", "name": "フジクラ",           "conds": [0,1,1,0,1,1,0,0]},
    {"code": "2802.T", "name": "味の素(ABF)",        "conds": [0,1,1,1,0,1,1,1]},
]

def fetch(code):
    try:
        import yfinance as yf
        ticker = yf.Ticker(code)

        # ★ fix①: dropna() で NaN 行を除去してから使う
        h5 = ticker.history(period="5d").dropna(subset=["Close"])
        if h5.empty:
            print(f"    [WARN] {code}: データなし（休場日の可能性）")
            return None

        close = float(h5["Close"].iloc[-1])
        prev  = float(h5["Close"].iloc[-2]) if len(h5) >= 2 else close
        chg   = (close - prev) / prev * 100

        h2y   = ticker.history(period="2y").dropna(subset=["High"])
        hi2y  = float(h2y["High"].max()) if not h2y.empty else close
        pct2y = close / hi2y * 100

        try:
            per = float(ticker.info.get("trailingPE") or 0) or None
        except Exception:
            per = None

        return {"close": close, "chg": chg, "pct2y": pct2y, "per": per}

    except Exception as e:
        print(f"    [WARN] {code}: {e}")
        return None

def build_message(results):
    lines = [f"\n新高値スクリーニング {TODAY}\n" + "-"*24]
    for r in results:
        d = r["data"]
        if d is None:
            lines.append(f"\n{r['name']}: 取得失敗（休場 or エラー）")
            continue
        arrow = "+" if d["chg"] >= 0 else ""
        c1    = "OK" if d["pct2y"] >= 95 else ("△" if d["pct2y"] >= 85 else "NG")
        c8    = f"{d['per']:.0f}x" if d.get("per") else "?"
        score = r["score"]
        lines.append(
            f"\n[{score}/8] {r['name']}\n"
            f"  {d['close']:,.0f}yen ({arrow}{d['chg']:.2f}%)\n"
            f"  2yr-high: {d['pct2y']:.1f}% [{c1}]  PER:{c8}"
        )
    lines.append("\n" + "-"
