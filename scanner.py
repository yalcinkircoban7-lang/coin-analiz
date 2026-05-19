import os, time, json, sqlite3, requests, random
from datetime import datetime, timezone

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "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")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8748447906:AAE7EfjLRIvNwVoldO4WjiB7l0dgrfwAf-Q")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "993355449")
DB_PATH            = "coins.db"
MAX_AGE_DAYS       = 60
MIN_LIQUIDITY_USD  = 5000
MIN_VOLUME_24H_USD = 1000
SCAN_INTERVAL_MIN  = 5
CHAINS = ["ethereum","bsc","solana","base","arbitrum"]
KEYWORDS = ["pump","launch","gem","fair","alpha","micro","nano","mini","new","stealth"]

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS tokens (
        pair_address TEXT PRIMARY KEY, chain_id TEXT, base_symbol TEXT,
        base_name TEXT, quote_symbol TEXT, dex_id TEXT, pair_created INTEGER,
        liquidity_usd REAL, fdv_usd REAL, volume_24h REAL, price_usd TEXT,
        buys_24h INTEGER, sells_24h INTEGER, website TEXT, twitter TEXT,
        telegram TEXT, ai_summary TEXT, risk_score INTEGER, project_type TEXT,
        liq_status TEXT, notified INTEGER DEFAULT 0, discovered_at TEXT)""")
    conn.commit()
    conn.close()
    print("Veritabani hazir.")

def is_notified(addr):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT pair_address FROM tokens WHERE pair_address=?", (addr,)).fetchone()
    conn.close()
    return bool(row)

def save_token(data):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""INSERT OR REPLACE INTO tokens VALUES (
        :pair_address,:chain_id,:base_symbol,:base_name,:quote_symbol,:dex_id,
        :pair_created,:liquidity_usd,:fdv_usd,:volume_24h,:price_usd,
        :buys_24h,:sells_24h,:website,:twitter,:telegram,
        :ai_summary,:risk_score,:project_type,:liq_status,:notified,:discovered_at)""", data)
    conn.commit()
    conn.close()

def fetch_pairs(keyword):
    try:
        r = requests.get(f"https://api.dexscreener.com/latest/dex/search?q={keyword}", timeout=15)
        data = r.json()
        return data.get("pairs") or [] if isinstance(data, dict) else []
    except Exception as e:
        print(f"Hata: {e}")
        return []

def is_new(pair):
    ms = pair.get("pairCreatedAt")
    if not ms: return False
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
        t = s.get("type","").lower()
        if t == "twitter": tw = s.get("url","")
        if t == "telegram": tg = s.get("url","")
    return web, tw, tg

def check_liquidity_lock(token_address, chain_id):
    chain_map = {"ethereum":"1","bsc":"56","base":"8453","arbitrum":"42161","solana":"900"}
    chain = chain_map.get(chain_id, "1")
    try:
        url = f"https://api.gopluslabs.io/api/v1/token_security/{chain}?contract_addresses={token_address}"
        r = requests.get(url, timeout=10)
        data = r.json()
        result = data.get("result", {})
        if not result:
            return "Bilgi yok"
        token_data = list(result.values())[0]
        if str(token_data.get("is_honeypot","0")) == "1":
            return "HONEYPOT - Satis yapilamaz!"
        if str(token_data.get("lp_locked","0")) == "1":
            return "Likidite kilitli"
        return "Likidite KILITLI DEGIL"
    except:
        return "Kontrol yapilamadi"

def analyze(pair, web, tw, tg):
    base = pair.get("baseToken",{})
    liq  = pair.get("liquidity",{})
    vol  = pair.get("volume",{})
    txns = pair.get("txns",{}).get("h24",{})
    buys = txns.get("buys",0)
    sells = txns.get("sells",0)
    prompt = f"""Kripto token analiz et. Sadece JSON don:
{{"project_type":"Memecoin","risk_score":5,"wash_trading":false,"summary":"Turkce 2 cumle"}}
Token: {base.get("name","?")} ({base.get("symbol","?")})
Zincir: {pair.get("chainId","?")} / {pair.get("dexId","?")}
Likidite: ${liq.get("usd",0):.0f} | Hacim: ${vol.get("h24",0):.0f}
Alim: {buys} | Satim: {sells}
Web: {web or "yok"} | Twitter: {tw or "yok"} | Telegram: {tg or "yok"}
- project_type: Memecoin/Utility/DeFi/AI/GameFi/Bilinmiyor
- risk_score: 1-10
- wash_trading: alim ve satim cok yakinsa true
- summary: 2 Turkce cumle"""
    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
            json={"model": "openai/gpt-4o-mini", "max_tokens": 300, "messages": [{"role": "user", "content": prompt}]},
            timeout=30
        )
        result = r.json()
        if "choices" not in result:
            print(f"API yaniti: {result}")
            return {"project_type":"Bilinmiyor","risk_score":5,"wash_trading":False,"summary":"Analiz yapilamadi."}
        raw = result["choices"][0]["message"]["content"].strip()
        return json.loads(raw[raw.find("{"):raw.rfind("}")+1])
    except Exception as e:
        print(f"AI hata: {e}")
        return {"project_type":"Bilinmiyor","risk_score":5,"wash_trading":False,"summary":"Analiz yapilamadi."}

def send_tg(d):
    r = d["risk_score"]
    emoji = "🟢" if r<=3 else "🟡" if r<=6 else "🔴"
    wash = "⚠️ WASH TRADING TESPİT EDİLDİ!\n" if d.get("wash_trading") else ""
    liq_emoji = "✅" if "kilitli" in d["liq_status"].lower() and "degil" not in d["liq_status"].lower() else "⚠️" if "honeypot" in d["liq_status"].lower() else "❌"
    msg = f"""🚨 Yeni Token: {d["base_name"]} ({d["base_symbol"]})
🔗 {d["chain_id"]} | {d["dex_id"]}
💧 Likidite: ${d["liquidity_usd"]:,.0f} | Hacim: ${d["volume_24h"]:,.0f}
📈 Alım: {d["buys_24h"]} | Satım: {d["sells_24h"]}
🏷️ Tip: {d["project_type"]} | Risk: {emoji} {r}/10
{liq_emoji} {d["liq_status"]}
{wash}📝 {d["ai_summary"]}
🔎 https://dexscreener.com/{d["chain_id"]}/{d["pair_address"]}"""
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=10)
        print(f"Bildirim: {d['base_symbol']}")
    except Exception as e:
        print(f"Telegram hata: {e}")

def scan():
    keyword = random.choice(KEYWORDS)
    print(f"\nTarama: {datetime.now().strftime('%H:%M:%S')} | Kelime: {keyword}")
    found = 0
    pairs = fetch_pairs(keyword)
    print(f"  {len(pairs)} cift bulundu")
    for pair in pairs:
        if not is_new(pair) or not ok_filter(pair): continue
        addr = pair.get("pairAddress","")
        if not addr or is_notified(addr): continue
        web, tw, tg = get_socials(pair)
        token_addr = (pair.get("baseToken") or {}).get("address","")
        liq_status = check_liquidity_lock(token_addr, pair.get("chainId",""))
        print(f"  Yeni: {pair.get('baseToken',{}).get('symbol','?')} ({pair.get('chainId','')})")
        ai = analyze(pair, web, tw, tg)
        time.sleep(1)
        base = pair.get("baseToken",{})
        liq  = pair.get("liquidity",{})
        vol  = pair.get("volume",{})
        txns = pair.get("txns",{}).get("h24",{})
        d = {
            "pair_address": addr, "chain_id": pair.get("chainId",""),
            "base_symbol": base.get("symbol",""), "base_name": base.get("name",""),
            "quote_symbol": (pair.get("quoteToken") or {}).get("symbol",""),
            "dex_id": pair.get("dexId",""), "pair_created": pair.get("pairCreatedAt",0),
            "liquidity_usd": liq.get("usd",0), "fdv_usd": pair.get("fdv",0),
            "volume_24h": vol.get("h24",0), "price_usd": str(pair.get("priceUsd","0")),
            "buys_24h": txns.get("buys",0), "sells_24h": txns.get("sells",0),
            "website": web, "twitter": tw, "telegram": tg,
            "ai_summary": ai.get("summary",""), "risk_score": ai.get("risk_score",5),
            "project_type": ai.get("project_type","Bilinmiyor"),
            "liq_status": liq_status, "notified": 1,
            "discovered_at": datetime.now(timezone.utc).isoformat()
        }
        d["wash_trading"] = ai.get("wash_trading", False)
        save_token(d)
        send_tg(d)
        found += 1
    print(f"Bitti. {found} yeni token.")

init_db()
print(f"API Key: {OPENROUTER_API_KEY[:20]}...")
while True:
    scan()
    print(f"{SCAN_INTERVAL_MIN} dakika bekleniyor...")
    time.sleep(SCAN_INTERVAL_MIN * 60)
