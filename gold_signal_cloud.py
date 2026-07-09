# -*- coding: utf-8 -*-
import sys, os, json, argparse, urllib.request
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd

YF_SYMBOL = "GC=F"; TF_INTERVAL = "1h"; RANGE = "3mo"
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state", "last_bar.txt")
LINE_TOKEN = os.environ.get("LINE_TOKEN", "")
EMA_FAST=50; EMA_SLOW=200; ADX_PERIOD=14; ADX_MIN=22.0
LOOKBACK=20; ATR_PERIOD=14; ATR_SL=2.0; REWARD_R=1.8

def wilder(s,p): return s.ewm(alpha=1/p, adjust=False).mean()

def fetch():
    url=(f"https://query1.finance.yahoo.com/v8/finance/chart/{YF_SYMBOL}"
         f"?interval={TF_INTERVAL}&range={RANGE}")
    req=urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
    d=json.loads(urllib.request.urlopen(req, timeout=20).read())
    r=d["chart"]["result"][0]; ts=r["timestamp"]; q=r["indicators"]["quote"][0]
    return pd.DataFrame({"time":pd.to_datetime(ts,unit="s"),"open":q["open"],
        "high":q["high"],"low":q["low"],"close":q["close"]}).dropna().reset_index(drop=True)

def add_indicators(df):
    c,h,l = df["close"],df["high"],df["low"]
    df["ema_fast"]=c.ewm(span=EMA_FAST,adjust=False).mean()
    df["ema_slow"]=c.ewm(span=EMA_SLOW,adjust=False).mean()
    pc=c.shift(1)
    tr=pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    df["atr"]=wilder(tr,ATR_PERIOD)
    up=h.diff(); dn=-l.diff()
    pdm=pd.Series(np.where((up>dn)&(up>0),up,0.0),index=df.index)
    mdm=pd.Series(np.where((dn>up)&(dn>0),dn,0.0),index=df.index)
    a=wilder(tr,ADX_PERIOD); pdi=100*wilder(pdm,ADX_PERIOD)/a; mdi=100*wilder(mdm,ADX_PERIOD)/a
    dx=100*(pdi-mdi).abs()/(pdi+mdi).replace(0,np.nan)
    df["adx"]=wilder(dx,ADX_PERIOD)
    return df

def evaluate(df):
    i=len(df)-2
    ef=df["ema_fast"].iloc[i]; es=df["ema_slow"].iloc[i]
    adx=df["adx"].iloc[i]; atr=df["atr"].iloc[i]; close=df["close"].iloc[i]
    hh=df["high"].iloc[i-LOOKBACK:i].max(); ll=df["low"].iloc[i-LOOKBACK:i].min()
    trend="上昇" if ef>es else "下降"
    sig="NONE"; reason=[]
    if adx < ADX_MIN: reason.append(f"ADX {adx:.1f} < {ADX_MIN} トレンド弱く見送り")
    else:
        if ef>es and close>=hh: sig="BUY"
        elif ef<es and close<=ll: sig="SELL"
        else: reason.append("ブレイク未成立")
    out=dict(bar_time=str(df["time"].iloc[i]),price=float(close),trend=trend,
             adx=float(adx),atr=float(atr),signal=sig,reason=" / ".join(reason))
    if sig!="NONE":
        d=1 if sig=="BUY" else -1; sld=atr*ATR_SL; tpd=sld*REWARD_R
        out.update(entry=float(close),sl=float(close-sld*d),tp=float(close+tpd*d),
                   risk_usd=float(sld*100*0.01),reward_usd=float(tpd*100*0.01))
    return out

def notify_line(text):
    if not LINE_TOKEN: print("LINE_TOKEN未設定"); return
    try:
        req=urllib.request.Request("https://api.line.me/v2/bot/message/broadcast",
            data=json.dumps({"messages":[{"type":"text","text":text[:4900]}]}).encode("utf-8"),
            headers={"Authorization":"Bearer "+LINE_TOKEN,"Content-Type":"application/json"},method="POST")
        urllib.request.urlopen(req, timeout=10); print("LINE送信OK")
    except Exception as e: print("LINE失敗:", e)

def load_last():
    try:
        with open(STATE_FILE, encoding="utf-8") as f: return f.read().strip()
    except FileNotFoundError: return ""

def save_last(t):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE,"w",encoding="utf-8") as f: f.write(t)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--dry",action="store_true")
    args=ap.parse_args()
    df=add_indicators(fetch()); s=evaluate(df)
    print(f"[{s['bar_time']}] {s['price']:.2f} {s['trend']} ADX{s['adx']:.0f} -> {s['signal']}")
    if s["signal"]=="NONE": return
    if s["bar_time"]==load_last(): print("通知済みスキップ"); return
    mark="🟢買い(BUY)" if s["signal"]=="BUY" else "🔴売り(SELL)"
    msg=(f"【GOLDスイングシグナル】\n{mark}\nエントリー: {s['entry']:.2f} 付近\n"
         f"損切りSL: {s['sl']:.2f}\n利確TP: {s['tp']:.2f}\n"
         f"トレンド: {s['trend']} / ADX {s['adx']:.0f}\n判定足(H1): {s['bar_time']} UTC\n"
         f"0.01ロット時: 損失-${s['risk_usd']:.1f} / 利益+${s['reward_usd']:.1f}\n"
         f"※価格はGC=F基準。MT5(GOLD#)の実値でSL/TPを入れて手動発注。")
    print(msg)
    if args.dry: return
    notify_line(msg); save_last(s["bar_time"])

if __name__=="__main__": main()
