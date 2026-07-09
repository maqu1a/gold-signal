# -*- coding: utf-8 -*-
import sys, os, json, argparse, urllib.request
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd

YF_SYMBOL="GC=F"
STATE_FILE=os.path.join(os.path.dirname(os.path.abspath(__file__)),"state","last_bar_daytrade.txt")
LINE_TOKEN=os.environ.get("LINE_TOKEN","")
RSI_P=14; ATR_P=14; EMA_F=20; EMA_S=50; BREAK_LOOKBACK=20
SL_ATR=1.2; TP_ATR=1.8; SESSION_START=9; SESSION_END=19; JST_OFFSET=9

def wilder(s,p): return s.ewm(alpha=1/p,adjust=False).mean()

def fetch(interval,rng):
    url=(f"https://query1.finance.yahoo.com/v8/finance/chart/{YF_SYMBOL}"
         f"?interval={interval}&range={rng}")
    req=urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
    d=json.loads(urllib.request.urlopen(req, timeout=20).read())
    r=d["chart"]["result"][0]; ts=r["timestamp"]; q=r["indicators"]["quote"][0]
    return pd.DataFrame({"time":pd.to_datetime(ts,unit="s"),"open":q["open"],
        "high":q["high"],"low":q["low"],"close":q["close"]}).dropna().reset_index(drop=True)

def add_ind(df):
    c,h,l=df["close"],df["high"],df["low"]
    df["ema_f"]=c.ewm(span=EMA_F,adjust=False).mean()
    df["ema_s"]=c.ewm(span=EMA_S,adjust=False).mean()
    d=c.diff(); up=d.clip(lower=0); dn=-d.clip(upper=0)
    rs=wilder(up,RSI_P)/wilder(dn,RSI_P).replace(0,np.nan)
    df["rsi"]=100-100/(1+rs)
    pc=c.shift(1); tr=pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    df["atr"]=wilder(tr,ATR_P); return df

def trend_dir(dft):
    c=dft["close"]
    ema50=c.ewm(span=50,adjust=False).mean().iloc[-2]
    ema200=c.ewm(span=200,adjust=False).mean().iloc[-2]
    slope=c.ewm(span=50,adjust=False).mean().diff().iloc[-2]
    if ema50>ema200 and slope>0: return "上昇",1
    if ema50<ema200 and slope<0: return "下降",-1
    return "レンジ",0

def evaluate():
    dfb=add_ind(fetch("5m","1mo")); dft=fetch("15m","1mo")
    i=len(dfb)-2
    close=dfb["close"].iloc[i]; rsi=dfb["rsi"].iloc[i]; atr=dfb["atr"].iloc[i]
    ef=dfb["ema_f"].iloc[i]; es=dfb["ema_s"].iloc[i]
    hh=dfb["high"].iloc[i-BREAK_LOOKBACK:i].max(); ll=dfb["low"].iloc[i-BREAK_LOOKBACK:i].min()
    tname,tdir=trend_dir(dft)
    jst=(int(dfb["time"].iloc[i].hour)+JST_OFFSET)%24
    in_session=SESSION_START<=jst<SESSION_END
    f=[]; lp=0; sp=0
    if tdir==1: lp+=1; f.append("M15上昇")
    elif tdir==-1: sp+=1; f.append("M15下降")
    else: f.append("M15レンジ")
    if ef>es: lp+=1; f.append("EMA上向き")
    elif ef<es: sp+=1; f.append("EMA下向き")
    if close>=hh: lp+=1; f.append("高値ブレイク")
    elif close<=ll: sp+=1; f.append("安値ブレイク")
    else: f.append("レンジ内")
    if rsi>=55: lp+=1; f.append(f"RSI{rsi:.0f}強気")
    elif rsi<=45: sp+=1; f.append(f"RSI{rsi:.0f}弱気")
    else: f.append(f"RSI{rsi:.0f}中立")
    bias="WAIT"; d=0
    if lp>=3 and lp>sp: bias="BUY寄り"; d=1
    elif sp>=3 and sp>lp: bias="SELL寄り"; d=-1
    out=dict(time=str(dfb["time"].iloc[i]),jst=jst,price=float(close),rsi=float(rsi),
             trend=tname,factors=f,lp=lp,sp=sp,bias=bias,dir=d,in_session=in_session)
    if d!=0 and in_session:
        out.update(entry=float(close),sl=float(close-atr*SL_ATR*d),tp=float(close+atr*TP_ATR*d),
                   risk=float(atr*SL_ATR*100*0.01),reward=float(atr*TP_ATR*100*0.01))
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
        with open(STATE_FILE, encoding="utf-8") as fp: return fp.read().strip()
    except FileNotFoundError: return ""

def save_last(t):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE,"w",encoding="utf-8") as fp: fp.write(t)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--dry",action="store_true")
    args=ap.parse_args(); s=evaluate()
    print(f"[{s['time']} JST{s['jst']}] {s['price']:.2f} 買{s['lp']}売{s['sp']} -> "
          f"{s['bias'] if s['in_session'] else '時間外'}")
    if s["dir"]==0 or not s["in_session"]: return
    if s["time"]==load_last(): print("通知済みスキップ"); return
    head="🟢買い寄り(BUY)" if s["dir"]==1 else "🔴売り寄り(SELL)"
    msg=(f"【GOLDデイトレ補助】※優位性未検証・裁量用\n{head}\n"
         f"エントリー: {s['entry']:.2f} 付近\nSL: {s['sl']:.2f} / TP: {s['tp']:.2f}\n"
         f"根拠: 買{s['lp']}/売{s['sp']}点 "+" / ".join(s["factors"])+"\n"
         f"上位足: {s['trend']} / RSI {s['rsi']:.0f}\nM5足: {s['time']} UTC(JST約{s['jst']}時)\n"
         f"0.01ロット時: 損失-${s['risk']:.1f} / 利益+${s['reward']:.1f}\n"
         f"※当日中に手仕舞い。指標時は見送り。MT5(GOLD#)実値で手動発注。")
    print(msg)
    if args.dry: return
    notify_line(msg); save_last(s["time"])

if __name__=="__main__": main()
