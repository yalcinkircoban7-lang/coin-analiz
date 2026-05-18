import time
import sqlite3
import requests
from datetime import datetime, timezone

OPENROUTER_API_KEY = "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"
TELEGRAM_BOT_TOKEN = "8748447906:AAE7EfjLRIvNwVoldO4WjiB7l0dgrfwAf-Q"
TELEGRAM_CHAT_ID   = "993355449"
DB_PATH            = "coins.db"
MAX_AGE_DAYS       = 365
MIN_LIQUIDITY_USD  = 5000
MIN_VOLUME_24H_USD = 1000
SCAN_INTERVAL_MIN  = 5
CHAINS = ["ethereum", "bsc", "solana", "base", "arbitrum"]
RISK_EMOJI = {1:"G",2:"G",3:"G",4:"O",5:"O",6:"O",7:"R",8:"R",9:"R",10:"R"}

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS tokens (
        pair_address TEXT PRIMARY KEY, chain_id TEXT, base_symbol TEXT,
        base_name TEXT, quote_symbol TEXT, dex_id TEXT, pair_created INTEGER,
        liquidity_usd REAL, fdv_usd REAL, volume_24h REAL, price_usd TEXT,
        buys_24h INTEGER, sells_24h INTEGER, website TEXT, twitter TEXT,
        telegram TEXT, ai_summary TEXT, risk_score INTEGER, project_type TEXT,
        notified INTEGER DEFAULT 0, discovered_at TEXT)""")
    conn.commit()
    conn.close()
    print("Veritabani hazir.")

def save_token(data):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""INSERT OR REPLACE INTO tokens VALUES (
        :pair_address,:chain_id,:base_symbol,:base_name,:quote_symbol,:dex_id,
        :pair_created,:liquidity_usd,:fdv_usd,:volume_24h,:price_usd,
        :buys_24h,:sells_24h,:website,:twitter,:telegram,
        :ai_summary,:risk_score,:project_type,:notified,:discovered_at)""", data)
    conn.commit()
    conn.close()

def is_notified(addr):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT notified FROM tokens WHERE pair_address=?", (addr,)).fetchone()
    conn.close()
    return bool(row and row[0])

def mark_notified(addr):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE tokens SET notified=1 WHERE pair_address=?", (addr,))
    conn.commit()
    conn.close()

def fetch_pairs(chain):
    try:
        url = f"https://api.dexscreener.com/latest/dex/search?q=new"
        r = requests.get(url, timeout=15)
        data = r.json()
        if isinstance(data, list):
            pairs = data
        elif isinstance(data, dict):
            pairs = data.get("pairs") or []
        else:
            pairs = []
        print(f"    {len(pairs)} cift bulundu")
        return pairs
    except Exception as e:
        print(f"Hata {chain}: {e}")
        return []

def is_new(pair):
    ms = pair.get("pairCreatedAt")
    if not ms:
        return False
    return (time.time()*1000 - ms) / (1000*86400) <= MAX_AGE_DAYS

def ok_filter(pair):
    liq = (pair.get("liquidity") or {}).get("usd", 0)
    vol = (pair.get("volume") or {}).get("h24", 0)
    return liq >= MIN_LIQUIDITY_USD and vol >= MIN_VOLUME_24H_USD

def get_socials(pair):
    info = pair.get("info") or {}
    sites = info.get("websites") or []
    socs = info.get("socials") or []
    web = sites[0].get("url","") if sites else ""
    tw = tg = ""
    for s in socs:
        if s.get("type","").lower() == "twitter":
            tw = s.get("url","")
        if s.get("type","").lower() == "telegram":
            tg = s.get("url","")
    return web, tw, tg

def analyze(pair, web, tw, tg):
    import json
    base = pair.get("baseToken",{})
    liq = pair.get("liquidity",{})
    vol = pair.get("volume",{})
    txns = pair.get("txns",{}).get("h24",{})
    prompt = f"""Token analiz et ve sadece JSON don:
{{"project_type":"Memecoin/Utility/DeFi/AI/Bilinmiyor","risk_score":5,"summary":"Turkce 2 cumle"}}
Bilgiler: {base.get("name")} ({base.get("symbol")}), Zincir:{pair.get("chainId")},
Likidite:${liq.get("usd",0):.0f}, Hacim:${vol.get("h24",0):.0f},
Alim:{txns.get("buys",0)}, Satim:{txns.get("sells",0)},
Web:{web or "yok"}, Twitter:{tw or "yok"}, Telegram:{tg or "yok"}"""
    try:
        r = requests.post("https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization":f"Bearer {OPENROUTER_API_KEY}","Content-Type":"application/json"},
            json={"model":"openai/gpt-4o-mini","max_tokens":200,"messages":[{"role":"user","content":prompt}]},
            timeout=30)
        raw = r.json()["choices"][0]["message"]["content"].strip()
        return json.loads(raw[raw.find("{"):raw.rfind("}")+1])
    except Exception as e:
        print(f"AI hata: {e}"); import traceback; traceback.print_exc()
        return {"project_type":"Bilinmiyor","risk_score":5,"summary":"Analiz yapilamadi."}

def send_tg(d):
    r = d["risk_score"]
    emoji = RISK_EMOJI.get(r,"?")
    msg = f"""Yeni Token: {d["base_name"]} ({d["base_symbol"]})
Zincir: {d["chain_id"]} | DEX: {d["dex_id"]}
Likidite: ${d["liquidity_usd"]:,.0f} | Hacim: ${d["volume_24h"]:,.0f}
Tip: {d["project_type"]} | Risk: {emoji} {r}/10
{d["ai_summary"]}
https://dexscreener.com/{d["chain_id"]}/{d["pair_address"]}"""
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id":TELEGRAM_CHAT_ID,"text":msg},timeout=10)
        print(f"Bildirim gonderildi: {d['base_symbol']}")
    except Exception as e:
        print(f"Telegram hata: {e}")

def scan():
    print(f"\nTarama: {datetime.now().strftime('%H:%M:%S')}")
    found = 0
    for chain in CHAINS:
        print(f"  {chain} taraniyor...")
        for pair in fetch_pairs(chain):
            if not is_new(pair) or not ok_filter(pair):
                continue
            addr = pair.get("pairAddress","")
            if not addr or is_notified(addr):
                continue
            web, tw, tg = get_socials(pair)
            print(f"  Yeni token: {pair.get('baseToken',{}).get('symbol','?')}")
            ai = analyze(pair, web, tw, tg)
            time.sleep(0.5)
            base = pair.get("baseToken",{})
            liq = pair.get("liquidity",{})
            vol = pair.get("volume",{})
            txns = pair.get("txns",{}).get("h24",{})
            d = {"pair_address":addr,"chain_id":pair.get("chainId",""),
                "base_symbol":base.get("symbol",""),"base_name":base.get("name",""),
                "quote_symbol":(pair.get("quoteToken") or {}).get("symbol",""),
                "dex_id":pair.get("dexId",""),"pair_created":pair.get("pairCreatedAt",0),
                "liquidity_usd":liq.get("usd",0),"fdv_usd":pair.get("fdv",0),
                "volume_24h":vol.get("h24",0),"price_usd":str(pair.get("priceUsd","0")),
                "buys_24h":txns.get("buys",0),"sells_24h":txns.get("sells",0),
                "website":web,"twitter":tw,"telegram":tg,
                "ai_summary":ai.get("summary",""),"risk_score":ai.get("risk_score",5),
                "project_type":ai.get("project_type","Bilinmiyor"),
                "notified":0,"discovered_at":datetime.now(timezone.utc).isoformat()}
            save_token(d)
            send_tg(d)
            mark_notified(addr)
            found += 1
        time.sleep(0.3)
    print(f"Bitti. {found} yeni token.")

init_db()
while True:
    scan()
    print(f"{SCAN_INTERVAL_MIN} dakika bekleniyor...")
    time.sleep(SCAN_INTERVAL_MIN * 60)