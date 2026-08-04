"""
新高値スクリーニング 自動更新スクリプト
毎営業日 15:35 JST に GitHub Actions から実行される

8条件：
  ① 現在株価 ≥ 2年高値の95%
  ② 現在株価 ≥ ATH（上場来高値）の60%
  ③ 5年経常利益CAGR ≥ 7%  ← 財務データは固定値（決算後に手動更新）
  ④ 直近1-2年 経常利益 +20%↑  ← 同上
  ⑤ 直近Q 売上 前年同期比 +10%↑  ← 同上
  ⑥ 直近Q 経常 前年同期比 +20%↑  ← 同上
  ⑦ 成長性・強みあり  ← 固定評価
  ⑧ PER < 60倍
"""

import os, json, math, requests
from datetime import datetime, date
import pytz
import yfinance as yf
import pandas as pd

JST = pytz.timezone("Asia/Tokyo")
TODAY = datetime.now(JST).strftime("%Y/%m/%d")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")

# ────────────────────────────────────────────
# 銘柄マスター（条件③〜⑦は決算後に手動更新）
# ────────────────────────────────────────────
STOCKS = [
    {
        "code": "6857.T", "display_code": "6857",
        "name": "アドバンテスト",
        "sector": "半導体製造装置",
        # 条件③〜⑦（最新決算後に手動更新する欄）
        "cond3": True,   # 5年経常CAGR 7%以上（FY26確定値で確認済）
        "cond4": True,   # 直近1-2年 経常+20%（FY27予 +24%）
        "cond5": True,   # 直近Q 売上+10%（FY26 Q3累計 +44.7%）
        "cond6": True,   # 直近Q 経常+20%（FY26 Q3営業利益 +118.8%）
        "cond7": True,   # 成長性・強みあり（AI半導体テスト装置独走）
        "fundamental_note": "FY26確定: 売上+44.7%・営業利益+118.8%。FY27予+24%。7/29 Q1決算",
    },
    {
        "code": "4062.T", "display_code": "4062",
        "name": "イビデン",
        "sector": "電子部品・ICパッケージ基板",
        "cond3": True,
        "cond4": True,
        "cond5": True,
        "cond6": True,
        "cond7": True,
        "fundamental_note": "AIサーバー向けICパッケージ基板 世界シェア70〜80%。FY26売上+13.7%・営業利益+28.1%",
    },
    {
        "code": "5805.T", "display_code": "5805",
        "name": "SWCC",
        "sector": "非鉄金属・電線ケーブル",
        "cond3": None,   # None = △（要確認）
        "cond4": True,
        "cond5": True,
        "cond6": True,
        "cond7": True,
        "fundamental_note": "FY26経常利益+131.8%。FY27営業利益+4.3%（保守的スタート）",
    },
    {
        "code": "5803.T", "display_code": "5803",
        "name": "フジクラ",
        "sector": "非鉄金属・光ファイバ",
        "cond3": True,
        "cond4": False,  # FY27最終利益-0.7%（減益）
        "cond5": True,
        "cond6": True,
        "cond7": None,   # 原材料調達懸念
        "fundamental_note": "5/14ストップ安後低迷継続。FY27最終利益-0.7%（条件④❌）",
    },
    {
        "code": "2802.T", "display_code": "2802",
        "name": "味の素（ABF）",
        "sector": "食品・半導体材料",
        "cond3": True,
        "cond4": True,
        "cond5": False,  # 全社売上+1%（構造的問題）
        "cond6": True,
        "cond7": True,
        "fundamental_note": "ABF世界シェア95%独占。全社売上+1%が条件⑤❌の構造的壁。PER14倍で最割安",
    },
    {
        "code": "6525.T", "display_code": "6525",
        "name": "KOKUSAI ELECTRIC",
        "sector": "半導体製造装置（ALD）",
        "cond3": None,   # 上場3年未満
        "cond4": False,  # FY26減益
        "cond5": False,
        "cond6": False,
        "cond7": True,
        "fundamental_note": "バッチ式ALD装置 世界シェア1位。FY26減益。8月Q1決算でFY27+20%なら昇格候補",
    },
]


def fetch_price_data(code: str) -> dict:
    """yfinance で株価・2年高値・ATH・PER を取得"""
    try:
        ticker = yf.Ticker(code)
        hist_2y = ticker.history(period="2y")
        hist_10y = ticker.history(period="10y")
        info = ticker.fast_info  # fast_info はより安定

        if hist_2y.empty:
            return {}

        close_2y = hist_2y["Close"]
        current = float(close_2y.iloc[-1])
        prev    = float(close_2y.iloc[-2]) if len(close_2y) > 1 else current
        high_2y = float(hist_2y["High"].max())
        high_atl= float(hist_10y["High"].max()) if not hist_10y.empty else high_2y

        pct_2y  = current / high_2y * 100
        pct_atl = current / high_atl * 100
        chg_pct = (current - prev) / prev * 100

        try:
            per = float(ticker.info.get("trailingPE") or 0) or None
        except Exception:
            per = None

        return {
            "current":  current,
            "high_2y":  high_2y,
            "high_atl": high_atl,
            "pct_2y":   pct_2y,
            "pct_atl":  pct_atl,
            "chg_pct":  chg_pct,
            "per":      per,
            "cond1":    pct_2y >= 95.0,
            "cond2":    pct_atl >= 60.0,
            "cond8":    (per is not None) and (per < 60.0),
        }
    except Exception as e:
        print(f"  [WARN] {code}: {e}")
        return {}


def score_cond(val) -> tuple[str, str]:
    """条件値 → (絵文字, クラス名)"""
    if val is True:   return "✅", "ok"
    if val is False:  return "❌", "ng"
    return "△", "tri"


def calc_score(stock: dict, price_data: dict) -> int:
    conds = [
        price_data.get("cond1"),
        price_data.get("cond2"),
        stock["cond3"],
        stock["cond4"],
        stock["cond5"],
        stock["cond6"],
        stock["cond7"],
        price_data.get("cond8"),
    ]
    return sum(1 for c in conds if c is True)


# ────────────────────────────────────────────
# LINE 通知
# ────────────────────────────────────────────
def send_ntfy(message: str):
    """ntfy.sh 経由でスマホにプッシュ通知を送る（アカウント不要・無料）"""
    if not NTFY_TOPIC:
        print("[ntfy] トピック未設定のためスキップ")
        return
    r = requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=message.encode("utf-8"),
        headers={
            "Title": f"📈 新高値スクリーニング {TODAY}",
            "Priority": "default",
            "Tags": "chart_increasing",
        },
        timeout=10,
    )
    print(f"[ntfy] status={r.status_code}")


def build_line_message(results: list) -> str:
    lines = [
        "",
        f"📈 新高値スクリーニング {TODAY}",
        "━" * 20,
    ]
    for r in results:
        pd_ = r["price_data"]
        s   = r["stock"]
        if not pd_:
            lines.append(f"\n{s['display_code']} {s['name']}\n  ⚠️ データ取得失敗")
            continue
        chg_arrow = "▲" if pd_["chg_pct"] >= 0 else "▼"
        chg_sign  = "+" if pd_["chg_pct"] >= 0 else ""
        score     = r["score"]
        e1, _     = score_cond(pd_.get("cond1"))
        e8, _     = score_cond(pd_.get("cond8"))
        per_str   = f"{pd_['per']:.1f}倍" if pd_.get("per") else "不明"

        lines += [
            "",
            f"[{score}/8] {s['display_code']} {s['name']}",
            f"  ¥{pd_['current']:,.0f} {chg_arrow}{chg_sign}{pd_['chg_pct']:.2f}%",
            f"  ① 2年高値比: {pd_['pct_2y']:.1f}% {e1}",
            f"  ⑧ PER: {per_str} {e8}",
        ]
    lines += [
        "",
        "━" * 20,
        "📊 詳細: GitHub Pages でダッシュボードを確認",
    ]
    return "\n".join(lines)


# ────────────────────────────────────────────
# HTML ダッシュボード生成
# ────────────────────────────────────────────
COND_LABELS = [
    "①2年高値95%", "②ATH60%↑", "③CAGR7%",
    "④経常+20%", "⑤Q売上+10%", "⑥Q経常+20%",
    "⑦成長性", "⑧PER60倍",
]

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>新高値スクリーニング | {date}</title>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<style>
:root{{--bg:#06090f;--surface:#0c1220;--surface2:#111927;--border:rgba(255,255,255,0.06);
      --border2:rgba(255,255,255,0.13);--text:#e2eaf6;--muted:#5a7099;--dim:#8faac8;
      --accent:#00e5b0;--blue:#4f91f5;--amber:#f5a623;--green:#2ecc8a;--red:#f05252;
      --purple:#a78bfa;--star:#fbbf24;--r:10px}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--text);font-family:'Noto Sans JP',sans-serif;font-size:13px;line-height:1.7}}
.topbar{{background:var(--surface);border-bottom:1px solid var(--border);padding:13px 28px;
         display:flex;align-items:center;gap:14px;position:sticky;top:0;z-index:100}}
.tb-title{{font-family:'JetBrains Mono',monospace;font-size:15px;font-weight:600;color:var(--accent)}}
.tb-date{{font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--muted)}}
.tb-badge{{margin-left:auto;font-size:10px;padding:4px 14px;border:1px solid rgba(0,229,176,0.4);
           color:var(--accent);border-radius:20px;font-family:'JetBrains Mono',monospace}}
.page{{padding:22px 28px}}
.kpi-row{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:18px}}
.kpi{{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);
      padding:13px 15px;position:relative;overflow:hidden}}
.kpi::before{{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:var(--kc,var(--accent))}}
.kpi-l{{font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin-bottom:5px}}
.kpi-v{{font-size:22px;font-weight:700;font-family:'JetBrains Mono',monospace;color:var(--kc,var(--accent))}}
.kpi-sub{{font-size:9px;color:var(--muted);margin-top:4px}}
.charts-row{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:18px}}
.ccrd{{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:15px 17px}}
.ctitle{{font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin-bottom:3px}}
.csub{{font-size:10px;color:var(--dim);margin-bottom:10px}}
table{{width:100%;border-collapse:collapse;font-size:12px;margin-bottom:18px}}
th{{padding:7px 10px;font-size:9px;font-weight:600;color:var(--muted);text-transform:uppercase;
    letter-spacing:.07em;border-bottom:1px solid var(--border2);text-align:right;white-space:nowrap}}
th:first-child{{text-align:left}}
td{{padding:8px 10px;border-bottom:0.5px solid var(--border);font-family:'JetBrains Mono',monospace;
    font-size:12px;text-align:right}}
td:first-child{{text-align:left;font-family:'Noto Sans JP',sans-serif}}
tr:hover td{{background:rgba(255,255,255,0.02)}}
.ok{{color:#6ee7a0}}.ng{{color:#fca5a5}}.tri{{color:#fde68a}}
.badge{{display:inline-block;font-size:9px;padding:2px 7px;border-radius:10px;font-family:'JetBrains Mono',monospace}}
.badge-ok{{background:rgba(46,204,138,0.12);color:#6ee7a0;border:1px solid rgba(46,204,138,0.2)}}
.badge-ng{{background:rgba(240,82,82,0.1);color:#fca5a5;border:1px solid rgba(240,82,82,0.12)}}
.badge-tri{{background:rgba(245,166,35,0.1);color:#fde68a;border:1px solid rgba(245,166,35,0.18)}}
.sc8{{color:var(--accent);font-weight:700}}.sc7{{color:var(--blue);font-weight:600}}
.sc6{{color:var(--amber)}}.sc-low{{color:var(--red)}}
.note{{font-size:10px;color:var(--muted);line-height:1.9;padding:12px 0;border-top:1px solid var(--border);margin-top:4px}}
@keyframes fadeUp{{from{{opacity:0;transform:translateY(6px)}}to{{opacity:1;transform:none}}}}
.anim{{animation:fadeUp .4s ease both}}
</style>
</head>
<body>
<div class="topbar">
  <span class="tb-title">新高値スクリーニング</span>
  <span class="tb-date">🤖 自動更新 {date}</span>
  <span class="tb-badge">8 CONDITION SCREEN</span>
</div>
<div class="page">
  <div class="kpi-row">
    <div class="kpi" style="--kc:var(--accent)">
      <div class="kpi-l">8/8条件適合</div>
      <div class="kpi-v">{cnt_8}</div>
      <div class="kpi-sub">△含む適合: {cnt_6}銘柄</div>
    </div>
    <div class="kpi" style="--kc:var(--blue)">
      <div class="kpi-l">最高スコア銘柄</div>
      <div class="kpi-v" style="font-size:16px">{top_name}</div>
      <div class="kpi-sub">{top_score}/8</div>
    </div>
    <div class="kpi" style="--kc:var(--amber)">
      <div class="kpi-l">次回決算イベント</div>
      <div class="kpi-v" style="font-size:16px">7/29</div>
      <div class="kpi-sub">アドバンテスト Q1決算</div>
    </div>
    <div class="kpi" style="--kc:var(--green)">
      <div class="kpi-l">最終更新</div>
      <div class="kpi-v" style="font-size:14px">{time}</div>
      <div class="kpi-sub">JST 15:35 自動実行</div>
    </div>
  </div>

  <div class="charts-row">
    <div class="ccrd anim">
      <div class="ctitle">本日終値・前日比</div>
      <div class="csub">東証15:30 大引け後データ（yfinance）</div>
      <div style="position:relative;height:220px"><canvas id="barChart"></canvas></div>
    </div>
    <div class="ccrd anim">
      <div class="ctitle">2年高値比（%）— 条件①ライン: 95%</div>
      <div class="csub">95%以上で条件①✅。カーソルで詳細確認</div>
      <div style="position:relative;height:220px"><canvas id="highChart"></canvas></div>
    </div>
  </div>

  <table>
    <thead>
      <tr>
        <th style="text-align:left;min-width:180px">銘柄</th>
        <th>現在値</th><th>前日比%</th>
        <th>①2年高値%</th><th>②ATH%</th><th>③CAGR</th>
        <th>④経常+20</th><th>⑤Q売上</th><th>⑥Q経常</th>
        <th>⑦成長性</th><th>⑧PER</th>
        <th>スコア</th><th style="text-align:left">PER</th>
      </tr>
    </thead>
    <tbody>
{table_rows}
    </tbody>
  </table>

  <div class="note">
    ※ 株価・2年高値・ATH・PERは yfinance 経由の自動取得（15分ディレイ）。<br>
    ※ 条件③〜⑦は直近決算発表後に手動更新。<br>
    ※ 本資料は情報提供のみを目的とし、特定銘柄の売買を推奨するものではありません。
  </div>
</div>
<script>
const RESULTS = {results_json};
const gc='rgba(255,255,255,0.05)', tc='#5a7099';
const COLORS=['#00e5b0','#4f91f5','#f5a623','#a78bfa','#2ecc8a','#f05252'];

new Chart(document.getElementById('barChart'),{{
  type:'bar',
  data:{{
    labels:RESULTS.map(r=>r.code+' '+r.name),
    datasets:[{{
      data:RESULTS.map(r=>r.chg_pct),
      backgroundColor:RESULTS.map((r,i)=>r.chg_pct>=0?COLORS[i%COLORS.length]+'bb':'#f05252bb'),
      borderRadius:4,borderSkipped:false
    }}]
  }},
  options:{{
    indexAxis:'y',responsive:true,maintainAspectRatio:false,
    plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:ctx=>` ${{ctx.raw>=0?'+':''}}${{ctx.raw.toFixed(2)}}%`}}}}}},
    scales:{{
      x:{{grid:{{color:gc}},ticks:{{color:tc,callback:v=>(v>=0?'+':'')+v+'%'}},border:{{display:false}}}},
      y:{{grid:{{display:false}},ticks:{{color:'#8faac8',font:{{size:11}}}},border:{{display:false}}}}
    }}
  }}
}});

new Chart(document.getElementById('highChart'),{{
  type:'bar',
  data:{{
    labels:RESULTS.map(r=>r.code+' '+r.name),
    datasets:[
      {{label:'2年高値比%',data:RESULTS.map(r=>r.pct_2y),
        backgroundColor:RESULTS.map(r=>r.pct_2y>=95?'rgba(0,229,176,0.7)':r.pct_2y>=80?'rgba(79,145,245,0.6)':'rgba(240,82,82,0.5)'),
        borderRadius:4,borderSkipped:false}}
    ]
  }},
  options:{{
    indexAxis:'y',responsive:true,maintainAspectRatio:false,
    plugins:{{
      legend:{{display:false}},
      tooltip:{{callbacks:{{label:ctx=>`${{ctx.raw.toFixed(1)}}% (2年高値比)`}}}},
      annotation:{{}}
    }},
    scales:{{
      x:{{min:50,max:100,grid:{{color:gc}},ticks:{{color:tc,callback:v=>v+'%'}},border:{{display:false}}}},
      y:{{grid:{{display:false}},ticks:{{color:'#8faac8',font:{{size:11}}}},border:{{display:false}}}}
    }}
  }}
}});
</script>
</body>
</html>"""


def badge(val):
    if val is True:  return '<span class="badge badge-ok">✓</span>'
    if val is False: return '<span class="badge badge-ng">✗</span>'
    return '<span class="badge badge-tri">△</span>'


def td_cond(val):
    cls = "ok" if val is True else ("ng" if val is False else "tri")
    sym = "✓" if val is True else ("✗" if val is False else "△")
    return f'<td class="{cls}">{sym}</td>'


def build_html(results: list) -> str:
    rows = []
    for r in results:
        pd_ = r["price_data"]
        s   = r["stock"]
        score = r["score"]
        sc_cls = "sc8" if score==8 else ("sc7" if score>=7 else ("sc6" if score>=6 else "sc-low"))

        if not pd_:
            rows.append(f'<tr><td>{s["display_code"]} {s["name"]}</td>'
                        + '<td colspan="12" style="text-align:center;color:var(--muted)">データ取得失敗</td></tr>')
            continue

        chg = pd_["chg_pct"]
        chg_color = "var(--green)" if chg >= 0 else "var(--red)"
        sign = "+" if chg >= 0 else ""
        per_str = f'{pd_["per"]:.1f}倍' if pd_.get("per") else "—"

        rows.append(
            f'<tr>'
            f'<td>{s["display_code"]} {s["name"]}<br>'
            f'<span style="font-size:9px;color:var(--muted)">{s["sector"]}</span></td>'
            f'<td>¥{pd_["current"]:,.0f}</td>'
            f'<td style="color:{chg_color}">{sign}{chg:.2f}%</td>'
            f'{td_cond(pd_.get("cond1"))}'
            f'{td_cond(pd_.get("cond2"))}'
            f'{td_cond(s["cond3"])}'
            f'{td_cond(s["cond4"])}'
            f'{td_cond(s["cond5"])}'
            f'{td_cond(s["cond6"])}'
            f'{td_cond(s["cond7"])}'
            f'{td_cond(pd_.get("cond8"))}'
            f'<td class="{sc_cls}" style="font-weight:700">{score}/8</td>'
            f'<td>{per_str}</td>'
            f'</tr>'
        )

    scores = [r["score"] for r in results]
    top_idx = scores.index(max(scores))
    top = results[top_idx]
    cnt_8 = sum(1 for s in scores if s == 8)
    cnt_6 = sum(1 for s in scores if s >= 6)

    results_json = json.dumps([
        {
            "code":    r["stock"]["display_code"],
            "name":    r["stock"]["name"],
            "chg_pct": r["price_data"].get("chg_pct", 0) if r["price_data"] else 0,
            "pct_2y":  r["price_data"].get("pct_2y", 0) if r["price_data"] else 0,
        }
        for r in results
    ], ensure_ascii=False)

    now_jst = datetime.now(JST).strftime("%H:%M")

    return HTML_TEMPLATE.format(
        date=TODAY,
        time=now_jst,
        cnt_8=cnt_8,
        cnt_6=cnt_6,
        top_name=top["stock"]["name"],
        top_score=top["score"],
        table_rows="\n".join(rows),
        results_json=results_json,
    )


# ────────────────────────────────────────────
# メイン
# ────────────────────────────────────────────
def main():
    print(f"=== 新高値スクリーニング {TODAY} ===")
    results = []

    for s in STOCKS:
        print(f"  取得中: {s['code']} {s['name']}")
        pd_ = fetch_price_data(s["code"])
        score = calc_score(s, pd_) if pd_ else 0
        results.append({"stock": s, "price_data": pd_, "score": score})
        if pd_:
            chg = pd_["chg_pct"]
            sign = "+" if chg >= 0 else ""
            cond1 = "✅" if pd_.get("cond1") else ("△" if pd_.get("pct_2y", 0) > 90 else "❌")
            print(f"    ¥{pd_['current']:,.0f} ({sign}{chg:.2f}%) 2年高値比:{pd_['pct_2y']:.1f}% {cond1} スコア:{score}/8")

    # ダッシュボード HTML 書き出し
    os.makedirs("dashboard", exist_ok=True)
    html = build_html(results)
    with open("dashboard/index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("  ✅ dashboard/index.html を更新しました")

    # LINE 通知
    msg = build_line_message(results)
    send_ntfy(msg)

    print("=== 完了 ===")


if __name__ == "__main__":
    main()

