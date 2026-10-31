#!/usr/bin/env python3
"""PAPER-TRADING pump.fun bot. Simulation only: no wallet, no keys, no real orders."""
import os, asyncio, json, time, sqlite3, threading, requests, websockets, html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
WS="wss://pumpportal.fun/api/data"; PORT=int(os.environ.get("PORT","8811")); DB="trades.db"
S={"cash_usd":1500.0,"start":1500.0,"sol_usd":0.0,"positions":{},"feed":[],"seen":0,"rejected":0,"watch":{},
   "rules":{"pos_pct":0.03,"watch_s":45,"min_buyers":10,"min_buy_ratio":1.5,"min_mc_sol":30,"max_mc_sol":80,
            "max_top10_pct":30,"max_dev_pct":5,"min_score_norm":0,"max_score_norm":5,
            "tp":0.6,"sl":-0.2,"time_stop_s":300,"trail":0.25},"rule_log":[],"chat":[],"names":[],"long":{},"rc":{}}
AG=["Scout","Sniper","Curve","Graduate"]
FEE=0.01; SLIP=0.02; NET=0.000005*2+0.0005  # pump fee 1%, slippage 2%, tx+priority fee SOL
db=sqlite3.connect(DB,check_same_thread=False)
db.execute("create table if not exists trades(ts,mint,symbol,side,usd,price_sol,pnl_usd,reason,agent)")
db.execute("create table if not exists rules(ts,change,why)")
def say(m):
    S["feed"].insert(0,time.strftime("%H:%M:%S")+"  "+m); del S["feed"][200:]; print(m,flush=True)
def sol_price():
    try:
        p=requests.get("https://api.dexscreener.com/latest/dex/tokens/So11111111111111111111111111111111111111112",timeout=10).json()["pairs"]
        p=[x for x in p if x["quoteToken"]["symbol"] in("USDC","USDT")]; S["sol_usd"]=float(p[0]["priceUsd"])
    except Exception as e: print("solprice err",e)
def rug(mint):
    try: return requests.get(f"https://api.rugcheck.xyz/v1/tokens/{mint}/report",timeout=12).json()
    except Exception: return None
def x_mentions(sym):  # no free X source works from the box; placeholder for future X data
    return None
def chat(agent,m):
    S["chat"].insert(0,dict(a=agent,m=m,t=time.time())); del S["chat"][40:]
def safety(t):
    R=S["rules"]; c=S["rc"].get(t["mint"])
    r=c[1] if c and time.time()-c[0]<60 else rug(t["mint"])
    if r: S["rc"][t["mint"]]=(time.time(),r)
    why=[]
    if not r: return ["rugcheck unavailable"]
    if r.get("mintAuthority"): why.append("mint authority NOT revoked")
    if r.get("freezeAuthority"): why.append("freeze authority NOT revoked")
    if r.get("rugged"): why.append("flagged rugged")
    sn=r.get("score_normalised") or 0
    if sn>R["max_score_norm"]: why.append(f"rugcheck risk score {sn}")
    bc=t.get("bc"); top=[h for h in r.get("topHolders") or [] if h.get("owner")!=bc]
    t10=sum(h.get("pct",0) for h in top[:10])
    if t10>R["max_top10_pct"]: why.append(f"top10 holders own {t10:.0f}%")
    if any(h.get("insider") for h in top[:10]): why.append("insider wallets in top holders")
    dev=next((h.get("pct",0) for h in top if h.get("owner")==t["dev"]),0)
    if dev>R["max_dev_pct"]: why.append(f"dev holds {dev:.1f}%")
    ct=r.get("creatorTokens") or []
    if len(ct)>=3: why.append(f"dev launched {len(ct)} other tokens (serial launcher)")
    for k in r.get("risks") or []:
        if k.get("level")=="danger": why.append("rugcheck: "+k.get("name",""))
    if t["dev_sold"]: why.append("dev already sold")
    t["info"]=f"top10 {t10:.0f}%, dev {dev:.1f}%, {t.get('nb',0)} buys/{t.get('ns',0)} sells, score {sn}"
    return why
def momentum(t,agent):
    R=S["rules"]; why=[]
    mb=R["min_buyers"]-(3 if agent in("Sniper","Scout") else 0)
    if agent=="Graduate": mb=R["min_buyers"]*2
    if t.get("nb",0)<mb: why.append(f"only {t.get('nb',0)} buys")
    if t.get("ns",0)>0 and t.get("nb",0)/t["ns"]<R["min_buy_ratio"]: why.append("sell pressure too high")
    lo,hi={"Sniper":(29,50),"Graduate":(200,400)}.get(agent,(R["min_mc_sol"],R["max_mc_sol"]))
    if not(lo<=t["mc"]<=hi): why.append(f"mcap {t['mc']:.0f} SOL out of range")
    return why
def check(t,agent): return safety(t) or momentum(t,agent)
def buy(t,agent):
    usd=min(S["cash_usd"],S["cash_usd"]*S["rules"]["pos_pct"]+0) ; usd=min(usd,(S["cash_usd"]+inv())*S["rules"]["pos_pct"])
    if usd<5 or not S["sol_usd"]: return
    sol=usd/S["sol_usd"]; eff=t["price"]*(1+SLIP)
    tokens=(sol*(1-FEE)-NET)/eff; S["cash_usd"]-=usd
    S["positions"][t["mint"]]=dict(sym=t["sym"],dev=t["dev"],tokens=tokens,cost=usd,entry=t["price"],peak=t["price"],ts=time.time(),agent=agent,price=t["price"],info=t.get("info",""))
    db.execute("insert into trades values(?,?,?,?,?,?,?,?,?)",(time.time(),t["mint"],t["sym"],"BUY",usd,t["price"],0,t.get("info",""),agent));db.commit()
    chat(agent,{"Scout":f"{t.get('trend',0)} launches on this narrative → buying ${t['sym']}","Sniper":f"sniping ${t['sym']} right after launch","Curve":f"${t['sym']} on the curve → riding it","Graduate":f"${t['sym']} about to graduate → in"}[agent])
    say(f"🟢 [{agent}] BUY ${t['sym']} ${usd:.0f} at mcap {t['mc']:.0f} SOL — passed anti-rug ({t.get('info')})")
def val(p): return p["tokens"]*p["price"]*(1-SLIP)*(1-FEE)*S["sol_usd"]-NET*S["sol_usd"]
def inv(): return sum(val(p) for p in S["positions"].values())
LESSON={"dev sold":("max_dev_pct",-1,1,"dev dumped → tolerate less dev holding"),
        "stop-loss":("min_buyers",2,25,"price dumped → require more unique buyers before entry"),
        "time stop":("min_buy_ratio",0.25,4,"no momentum → require stronger buy/sell ratio")}
def sell(mint,reason):
    p=S["positions"].pop(mint); v=max(val(p),0); pnl=v-p["cost"]; S["cash_usd"]+=v
    db.execute("insert into trades values(?,?,?,?,?,?,?,?,?)",(time.time(),mint,p["sym"],"SELL",v,p["price"],pnl,reason,p["agent"]));db.commit()
    chat(p["agent"],f"sold ${p['sym']} {pnl/p['cost']*100:+.0f}% ({reason})")
    if pnl>=0: say(f"✅ SELL ${p['sym']} +${pnl:.2f} ({pnl/p['cost']*100:+.0f}%) — {reason}")
    else:
        expl={"dev sold":"the creator sold his bag; we exited at once but price was already hit",
              "stop-loss":"buyers dried up and price fell below our -20% stop",
              "time stop":"the hype never came; price drifted so we freed the capital"}
        k=next((k for k in LESSON if reason.startswith(k)),None)
        say(f"🔴 SELL ${p['sym']} -${-pnl:.2f} ({pnl/p['cost']*100:+.0f}%) — {reason}. What went wrong: {expl.get(k,reason)}.")
        if k:
            f,d,lim,why=LESSON[k]; R=S["rules"]; old=R[f]; R[f]=round(min(R[f]+d,lim) if d>0 else max(R[f]+d,lim),2)
            ch=f"{f}: {old} → {R[f]}"; S["rule_log"].insert(0,time.strftime("%H:%M ")+ch+" ("+why+")")
            db.execute("insert into rules values(?,?,?)",(time.time(),ch,why));db.commit(); say("🛠 Rule adjusted: "+ch)
def safety_fail(why): return any(k in w for w in why for k in("authority","rugged","risk","top10","insider","dev","rugcheck","serial"))
async def main():
    sol_price()
    async with websockets.connect(WS,ping_interval=20) as ws:
        await ws.send(json.dumps({"method":"subscribeNewToken"})); say("Connected to PumpPortal live feed (paper mode, $1500 virtual)")
        async def sub(keys,m=None): pass  # per-token trade stream needs a funded PumpPortal key -> we poll DexScreener instead
        async def poll():
            k=0
            while True:
                await asyncio.sleep(5); k+=1
                ms=list(S["positions"])+list(S["watch"])+list(S["long"])
                for i in range(0,len(ms),30):
                    try: ps=await asyncio.to_thread(lambda b=ms[i:i+30]: requests.get("https://api.dexscreener.com/tokens/v1/solana/"+",".join(b),timeout=10).json())
                    except Exception: continue
                    for pr in ps or []:
                        m=pr["baseToken"]["address"]; px=float(pr.get("priceNative") or 0)
                        if not px: continue
                        for t in (S["watch"].get(m),S["long"].get(m)):
                            if t:
                                tx=pr.get("txns",{}).get("h1",{}); t["price"]=px; t["mc"]=(pr.get("marketCap") or pr.get("fdv") or 0)/max(S["sol_usd"],1)
                                t["nb"]=tx.get("buys",0); t["ns"]=tx.get("sells",0)
                        p=S["positions"].get(m)
                        if p: p["price"]=px; p["peak"]=max(p["peak"],px)
                if k%4==0:
                    for m,p in list(S["positions"].items()):
                        r=await asyncio.to_thread(rug,m)
                        cb=(r or {}).get("creatorBalance")
                        if cb is None: continue
                        if p.get("devbal") is None: p["devbal"]=cb
                        elif cb<p["devbal"]*0.98 and m in S["positions"]: sell(m,"dev sold — emergency exit")
        asyncio.create_task(poll())
        async def tick():
            while True:
                await asyncio.sleep(3); now=time.time(); R=S["rules"]
                if int(now)%60<3: await asyncio.to_thread(sol_price)
                full=len(S["positions"])>=10
                for m,t in list(S["watch"].items()):
                    age=now-t["t0"]
                    if age>=15 and not t.get("sn") and not full:
                        t["sn"]=1
                        if not momentum(t,"Sniper") and not await asyncio.to_thread(check,t,"Sniper"):
                            del S["watch"][m]; buy(t,"Sniper"); continue
                    if age>=R["watch_s"]:
                        del S["watch"][m]; ag="Scout" if t["trend"]>=3 else "Curve"
                        why=await asyncio.to_thread(check,t,ag)
                        if not why and not full: buy(t,ag); continue
                        S["rejected"]+=1; say(f"⛔ skip ${t['sym']}: "+"; ".join(why[:3]))
                        if not safety_fail(why) and len(S["long"])<60: S["long"][m]=t
                        else: await sub([m],"unsubscribeTokenTrade")
                for m,t in list(S["long"].items()):
                    if now-t["t0"]>1200: del S["long"][m]; await sub([m],"unsubscribeTokenTrade")
                    elif t["mc"]>=200 and not full:
                        del S["long"][m]; why=await asyncio.to_thread(check,t,"Graduate")
                        if not why: buy(t,"Graduate")
                        else: say(f"⛔ [Graduate] skip ${t['sym']}: "+"; ".join(why[:2])); await sub([m],"unsubscribeTokenTrade")
                for m,p in list(S["positions"].items()):
                    ch=p["price"]/p["entry"]-1
                    if ch>=R["tp"]: sell(m,f"take-profit hit (+{ch*100:.0f}%)")
                    elif ch<=R["sl"]: sell(m,f"stop-loss ({ch*100:.0f}%)")
                    elif p["peak"]>p["entry"]*1.3 and p["price"]<p["peak"]*(1-R["trail"]): sell(m,"trailing stop after pump")
                    elif now-p["ts"]>R["time_stop_s"]: sell(m,f"time stop ({ch*100:+.0f}% after {R['time_stop_s']}s)")
                    else: continue
                    await sub([m],"unsubscribeTokenTrade")
        asyncio.create_task(tick())
        async for raw in ws:
            d=json.loads(raw); m=d.get("mint")
            if not m or "vSolInBondingCurve" not in d: continue
            price=d["vSolInBondingCurve"]/d["vTokensInBondingCurve"]; tx=d.get("txType")
            if tx=="create":
                S["seen"]+=1; nm=(d.get("name","")+" "+d.get("symbol","")).lower()
                words={x for x in nm.split() if len(x)>2}; S["names"]=[(a,b) for a,b in S["names"] if time.time()-a<600]
                trend=sum(1 for a,b in S["names"] if b&words); S["names"].append((time.time(),words))
                if len(S["watch"])<40:
                    S["watch"][m]=dict(mint=m,sym=d.get("symbol","?")[:12],dev=d["traderPublicKey"],bc=d.get("bondingCurveKey"),t0=time.time(),price=price,mc=d["marketCapSol"],buyers=set(),buys_sol=0,sells_sol=0,dev_sold=False,trend=trend)
                    await sub([m])
                continue
            w=S["watch"].get(m) or S["long"].get(m); p=S["positions"].get(m); tr=d.get("traderPublicKey")
            if w:
                w["price"]=price; w["mc"]=d["marketCapSol"]
                if tx=="buy": w["buyers"].add(tr); w["buys_sol"]+=d.get("solAmount",0)
                else:
                    w["sells_sol"]+=d.get("solAmount",0)
                    if tr==w["dev"]: w["dev_sold"]=True
            if p:
                p["price"]=price; p["peak"]=max(p["peak"],price)
                if tx=="sell" and tr==p["dev"]: sell(m,"dev sold — emergency exit"); await sub([m],"unsubscribeTokenTrade")
HERE=os.path.dirname(os.path.abspath(__file__))
PAGE=lambda:open(os.path.join(HERE,"ui.html"),encoding="utf-8").read()
STATIC={"/manifest.json":"application/manifest+json","/apple-touch-icon.png":"image/png","/icon-192.png":"image/png","/icon-512.png":"image/png","/favicon.png":"image/png"}
def stats():
    rows=db.execute("select symbol,pnl_usd,usd,agent,ts from trades where side='SELL' order by ts desc").fetchall()
    ag={a:0.0 for a in AG}
    for r in rows: ag[r[3]]+=r[1]
    for p in S["positions"].values(): ag[p["agent"]]+=val(p)-p["cost"]
    eq=S["cash_usd"]+inv(); n=db.execute("select count(*) from trades where side='BUY'").fetchone()[0]
    return dict(equity=eq,start=S["start"],profit=eq-S["start"],sol=S["sol_usd"],trades=n,closed=len(rows),wins=sum(r[1]>0 for r in rows),
      agents=ag,seen=S["seen"],rej=S["rejected"],
      closedT=[dict(sym=r[0],pnl=r[1],pct=r[1]/(r[2]-r[1])*100 if r[2]-r[1] else 0,agent=r[3]) for r in rows[:30]],
      pos=[dict(sym=p["sym"],agent=p["agent"],cost=p["cost"],ch=p["price"]/p["entry"]-1) for p in S["positions"].values()],
      chat=S["chat"][:12],feed=S["feed"][:40],rules=S["rule_log"][:10])
class H(BaseHTTPRequestHandler):
    def log_message(s,*a): pass
    def do_GET(s):
        if s.path.startswith("/events"):
            s.send_response(200); s.send_header("Content-Type","text/event-stream"); s.send_header("Cache-Control","no-cache"); s.end_headers()
            try:
                while True: s.wfile.write(("data: "+json.dumps(stats())+"\n\n").encode()); s.wfile.flush(); time.sleep(2)
            except Exception: return
        p=s.path.split("?")[0]
        if p in STATIC:
            b=open(os.path.join(HERE,"static",p.lstrip("/")),"rb").read(); ct=STATIC[p]
        elif p.startswith("/api"): b=json.dumps(stats()).encode(); ct="application/json"
        else: b=PAGE().encode(); ct="text/html; charset=utf-8"
        s.send_response(200); s.send_header("Content-Type",ct); s.send_header("Content-Length",str(len(b))); s.send_header("Cache-Control","no-cache"); s.end_headers(); s.wfile.write(b)
def snap():
    while True:
        time.sleep(15)
        try: json.dump(dict(t=time.time(),equity=S["cash_usd"]+inv(),cash=S["cash_usd"],rules=S["rules"],positions={k:{**v} for k,v in S["positions"].items()}),open("status.json","w"),default=str)
        except Exception: pass
if __name__=="__main__":
    threading.Thread(target=ThreadingHTTPServer(("0.0.0.0",PORT),H).serve_forever,daemon=True).start()
    threading.Thread(target=snap,daemon=True).start()
    while True:
        try: asyncio.run(main())
        except Exception as e: print("reconnect after error:",e,flush=True); time.sleep(5)
