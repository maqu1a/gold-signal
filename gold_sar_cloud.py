# -*- coding: utf-8 -*-
"""
GOLD 5分足 パラボリックSAR 転換サイン（クラウド無料版 / MT5不要）
================================================================
  - パラボリックSAR (ステップ0.020 / 最大0.200、Wilder式=MT5のiSARと同じ計算)
  - 価格ソース: Yahoo Finance チャートAPI (GC=F, 5分足, キー不要・無料)
    ※GOLD#と数十セントずれることがある。転換タイミングも1本前後ずれ得る。
  - GitHub Actions で5分ごとに実行 → SARの向きが前回実行時から変わっていたらLINE通知
    ※GitHubのcronは混雑時に数分遅れる/たまにスキップされる。「瞬間」通知が
      必要ならローカル版 gold_sar_signal.py --loop を使うこと。
  - state/last_sar_dir.txt に前回の向きを保存して重複通知を防止

ローカル確認:
  $env:LINE_TOKEN="xxxx"; python gold_sar_cloud.py --dry
"""
import sys, os, json, argparse, urllib.request
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd

# ===== 設定 =====
YF_SYMBOL="GC=F"
SAR_STEP=0.020
SAR_MAX =0.200
STATE_FILE=os.path.join(os.path.dirname(os.path.abspath(__file__)), "state", "last_sar_dir.txt")
LINE_TOKEN=os.environ.get("LINE_TOKEN","")   # ★直書きしない。GitHub Secretで渡す
JST_OFFSET=9                                 # YahooはUTC固定

def fetch(interval, rng):
    url=(f"https://query1.finance.yahoo.com/v8/finance/chart/{YF_SYMBOL}"
         f"?interval={interval}&range={rng}")
    req=urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
    d=json.loads(urllib.request.urlopen(req, timeout=20).read())
    r=d["chart"]["result"][0]; ts=r["timestamp"]; q=r["indicators"]["quote"][0]
    return pd.DataFrame({"time":pd.to_datetime(ts,unit="s"),
                         "open":q["open"],"high":q["high"],
                         "low":q["low"],"close":q["close"]}).dropna().reset_index(drop=True)

def parabolic_sar(high, low, step=SAR_STEP, maxaf=SAR_MAX):
    """Wilder式パラボリックSAR。trend: +1=上昇(ドットが下), -1=下降(ドットが上)"""
    n=len(high)
    sar=np.zeros(n); trend=np.zeros(n,dtype=int)
    trend[0]=1; sar[0]=low[0]; ep,af=high[0],step
    for i in range(1,n):
        prev=sar[i-1]
        if trend[i-1]==1:
            cur=prev+af*(ep-prev)
            cur=min(cur, low[i-1], low[i-2] if i>=2 else low[i-1])
            if low[i]<cur:                       # 下抜け → 下降へ転換
                trend[i]=-1; cur=ep; ep,af=low[i],step
            else:
                trend[i]=1
                if high[i]>ep: ep=high[i]; af=min(af+step,maxaf)
        else:
            cur=prev+af*(ep-prev)
            cur=max(cur, high[i-1], high[i-2] if i>=2 else high[i-1])
            if high[i]>cur:                      # 上抜け → 上昇へ転換
                trend[i]=1; cur=ep; ep,af=high[i],step
            else:
                trend[i]=-1
                if low[i]<ep: ep=low[i]; af=min(af+step,maxaf)
        sar[i]=cur
    return sar,trend

def evaluate():
    df=fetch("5m","5d")
    # 進行中の足も含めて計算する。SARの転換は一度成立するとその足の中で
    # 取り消されない性質があるので、途中足での転換検知も安全。
    sar,trend=parabolic_sar(df["high"].values, df["low"].values)
    i=len(df)-1
    t=df["time"].iloc[i]
    jst_hour=(int(t.hour)+JST_OFFSET)%24
    return dict(time=str(t), jst_hour=jst_hour,
                price=float(df["close"].iloc[i]),
                sar=float(sar[i]), dir=int(trend[i]))

def notify_line(text):
    if not LINE_TOKEN:
        print("  → LINE_TOKEN未設定のため送信スキップ"); return
    try:
        req=urllib.request.Request(
            "https://api.line.me/v2/bot/message/broadcast",
            data=json.dumps({"messages":[{"type":"text","text":text[:4900]}]}).encode("utf-8"),
            headers={"Authorization":"Bearer "+LINE_TOKEN,"Content-Type":"application/json"},
            method="POST")
        urllib.request.urlopen(req, timeout=10); print("  → LINE通知 送信OK")
    except Exception as e:
        print("  → LINE通知 失敗:", e)

def load_last():
    try:
        with open(STATE_FILE, encoding="utf-8") as f: return f.read().strip()
    except FileNotFoundError: return ""

def save_last(d):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE,"w",encoding="utf-8") as f: f.write(str(d))

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--dry",action="store_true")
    args=ap.parse_args()
    s=evaluate()
    dir_txt="上昇(ドットが下)" if s["dir"]==1 else "下降(ドットが上)"
    print(f"[M5 {s['time']}UTC/JST約{s['jst_hour']}時] {s['price']:.2f} "
          f"SAR {s['sar']:.2f} → {dir_txt}")

    last=load_last()
    if last=="":
        # 初回は基準を作るだけで通知しない
        print("  → 初回実行。向きを保存のみ")
        if not args.dry: save_last(s["dir"])
        return
    if int(last)==s["dir"]:
        print("  → 向き変わらず。通知なし"); return

    arrow="🔴→🟢 上昇へ転換!" if s["dir"]==1 else "🟢→🔴 下降へ転換!"
    msg=(f"【GOLD 5分足 SAR転換 (クラウド)】\n{arrow}\n"
         f"価格: {s['price']:.2f} (GC=F参考値)\n"
         f"SARドット: {s['sar']:.2f}\n"
         f"足: {s['time']} UTC (JST約{s['jst_hour']}時)\n"
         f"※cron遅延で数分遅れることあり。発注はMT5(GOLD#)実値・チャート確認の上で。")
    print(msg)
    if args.dry: print("  → --dry のため送信・保存しません"); return
    notify_line(msg); save_last(s["dir"])

if __name__=="__main__":
    main()
