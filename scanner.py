import os, time, json, sqlite3, requests, random
from datetime import datetime, timezone

OPENROUTER_API_KEY  = os.environ.get("OPENROUTER_API_KEY", "")
TELEGRAM_BOT_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN", "8748447906:AAE7EfjLRIvNwVoldO4WjiB7l0dgrfwAf-Q")
TELEGRAM_CHAT_ID    = os.environ.get("TELEGRAM_CHAT_ID", "993355449")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "-1003973970557")
ETHERSCAN_API_KEY   = "VHGHSNQZXBBCBRPJ8N88W8X2G21D8J3MZX"
BITQUERY_TOKEN      = "ory_at_6HnqUctQJy74XNlxyDoBPbymV6Xa-5tw0FG8JoVmOcU.4LB6zwLGXk1xf_RLYdbc3AdbyrOoJVykd8uFwaTfJ_o"
DB_PATH             = "coins.db"
MAX_AGE_DAYS        = 14
MIN_LIQUIDITY_USD   = 30000
MIN_VOLUME_24H_USD  = 3000
SCAN_INTERVAL_MIN   = 5
KEYWORDS = ["launch","gem","fair","alpha","micro","nano","mini","stealth","vault","protocol"]

STABLE_AND_MAJOR = {
    "USDT","USDC","DAI","BUSD","TUSD","FRAX","LUSD","GUSD","USDP",
    "WETH","WBTC","BTC","ETH","BNB","WBNB","SOL","WSOL",
    "MATIC","WMATIC","AVAX","WAVAX","FTM","OP","ARB","LINK","UNI","AAVE",
    "CRV","MKR","SNX","COMP","SUSHI","YFI","BAL","1INCH","LDO","RPL"
}

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS tokens (
        pair_address TEXT PRIMARY KEY, chain_id TEXT, base_symbol TEXT,
        base_name TEXT, quote_symbol TEXT, dex_id TEXT, pair_created INTEGER,
        liquidity_usd REAL, fdv_usd REAL, volume_24h REAL, price_usd TEXT,
        buys_24h INTEGER, sells_24h INTEGER, website TEXT, twitter TEXT,
        telegram TEXT, ai_summary TEXT, risk_score INTEGER, project_type TEXT,
        liq_status TEXT, holder_status TEXT, web_summary TEXT,
        notified INTEGER DEFAULT 0, discovered_at TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS coingecko_notified (
        coin_id TEXT PRIMARY KEY, notified_at TEXT)""")
    conn.commit()
    conn.close()
    print("Veritabani hazir.")

def is_notified(addr):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT pair_address FROM tokens WHERE pair_address=?", (addr,)).fetchone()
    conn.close()
    return bool(row)

def is_coingecko_notified(coin_id):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT coin_id FROM coingecko_notified WHERE coin_id=?", (coin_id,)).fetchone()
    conn.close()
    return bool(row)

def mark_coingecko_notified(coin_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT OR REPLACE INTO coingecko_notified VALUES (?,?)",
        (coin_id, datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()

def save_token(data):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""INSERT OR REPLACE INTO tokens VALUES (
        :pair_address,:chain_id,:base_symbol,:base_name,:quote_symbol,:dex_id,
        :pair_created,:liquidity_usd,:fdv_usd,:volume_24h,:price_usd,
        :buys_24h,:sells_24h,:website,:twitter,:telegram,
        :ai_summary,:risk_score,:project_type,:liq_status,:holder_status,
        :web_summary,:notified,:discovered_at)""", data)
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
        t = s.get("type","").lower()
        if t == "twitter": tw = s.get("url","")
        if t == "telegram": tg = s.get("url","")
    return web, tw, tg

def get_pair_age(pair_created_ms):
    if not pair_created_ms:
        return "Bilinmiyor"
    age_seconds = (time.time() * 1000 - pair_created_ms) / 1000
    if age_seconds < 3600:
        return f"{int(age_seconds/60)} dakika once listelendi"
    elif age_seconds < 86400:
        return f"{int(age_seconds/3600)} saat once listelendi"
    else:
        return f"{int(age_seconds/86400)} gun once listelendi"

def get_top_transactions(chain_id, pair_address):
    try:
        url = f"https://api.dexscreener.com/latest/dex/pairs/{chain_id}/{pair_address}"
        r = requests.get(url, timeout=10)
        data = r.json()
        pairs = data.get("pairs") or []
        if not pairs:
            return ""
        pair = pairs[0]
        txns = pair.get("txns", {})
        buys_h1 = txns.get("h1", {}).get("buys", 0)
        sells_h1 = txns.get("h1", {}).get("sells", 0)
        vol_h1 = pair.get("volume", {}).get("h1", 0)
        vol_h6 = pair.get("volume", {}).get("h6", 0)
        return f"Son 1s: {buys_h1} alim / {sells_h1} satim | Hacim 1s: ${vol_h1:,.0f} | Hacim 6s: ${vol_h6:,.0f}"
    except:
        return ""

def analyze_website(website_url):
    if not website_url:
        return "Web sitesi yok"
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(website_url, timeout=10, headers=headers)
        text = r.text[:3000]
        prompt = f"""Bu kripto projesinin web sitesi icerigini analiz et. Sadece JSON don:
{{"team":"ekip bilgisi veya Bilinmiyor","investors":"yatirimcilar veya Bilinmiyor","summary":"Turkce 1 cumle proje ozeti"}}
Web sitesi icerigi:
{text}"""
        result = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
            json={"model": "openai/gpt-4o-mini", "max_tokens": 200, "messages": [{"role": "user", "content": prompt}]},
            timeout=20
        ).json()
        if "choices" not in result:
            return "Web analizi yapilamadi"
        raw = result["choices"][0]["message"]["content"].strip()
        data = json.loads(raw[raw.find("{"):raw.rfind("}")+1])
        team = data.get("team","Bilinmiyor")
        investors = data.get("investors","Bilinmiyor")
        summary = data.get("summary","")
        return f"Ekip: {team} | Yatirimcilar: {investors} | {summary}"
    except:
        return "Web analizi yapilamadi"

def get_deployer_tokens(token_address, chain_id):
    try:
        api_map = {
            "ethereum": "https://api.etherscan.io/api",
            "bsc": "https://api.etherscan.io/v2/api?chainid=56&",
            "base": "https://api.basescan.org/api",
            "arbitrum": "https://api.arbiscan.io/api",
        }
        if chain_id not in api_map:
            return "Solana/desteklenmeyen zincir"
        api_url = api_map[chain_id]
        url = f"{api_url}?module=contract&action=getcontractcreation&contractaddresses={token_address}&apikey={ETHERSCAN_API_KEY}"
        r = requests.get(url, timeout=10)
        data = r.json()
        result = data.get("result",[])
        if not result:
            return "Deployer bilgisi yok"
        deployer = result[0].get("contractCreator","")
        if not deployer:
            return "Deployer bilgisi yok"
        url2 = f"{api_url}?module=account&action=txlist&address={deployer}&sort=desc&page=1&offset=20&apikey={ETHERSCAN_API_KEY}"
        r2 = requests.get(url2, timeout=10)
        txs = r2.json().get("result",[])
        contracts = []
        for tx in txs:
            if tx.get("to","") == "" and tx.get("contractAddress",""):
                contracts.append(tx["contractAddress"][:10]+"...")
        if not contracts:
            return f"Deployer: {deployer[:10]}... | Baska kontrat yok"
        return f"Deployer: {deployer[:10]}... | Onceki kontratlar: {', '.join(contracts[:3])}"
    except:
        return "Deployer analizi yapilamadi"

def check_token_security(token_address, chain_id):
    chain_map = {"ethereum":"1","bsc":"56","base":"8453","arbitrum":"42161","solana":"900"}
    chain = chain_map.get(chain_id, "1")
    try:
        url = f"https://api.gopluslabs.io/api/v1/token_security/{chain}?contract_addresses={token_address}"
        r = requests.get(url, timeout=10)
        data = r.json()
        result = data.get("result", {})
        if not result:
            return "Bilgi yok", "Bilgi yok"
        token_data = list(result.values())[0]
        if str(token_data.get("is_honeypot","0")) == "1":
            return "HONEYPOT - Satis yapilamaz!", "Bilgi yok"
        liq_status = "Likidite kilitli" if str(token_data.get("lp_locked","0")) == "1" else "Likidite KILITLI DEGIL"
        holders = token_data.get("holders", [])
        if holders:
            top10 = sum(float(h.get("percent","0")) for h in holders[:10]) * 100
            if top10 >= 80:
                holder_status = f"Top 10 holder: %{top10:.1f} - RUG PULL RISKI!"
            elif top10 >= 50:
                holder_status = f"Top 10 holder: %{top10:.1f} - Dikkatli ol"
            else:
                holder_status = f"Top 10 holder: %{top10:.1f} - Dagilim iyi"
        else:
            holder_status = "Holder bilgisi yok"
        return liq_status, holder_status
    except:
        return "Kontrol yapilamadi", "Bilgi yok"

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
            return {"project_type":"Bilinmiyor","risk_score":5,"wash_trading":False,"summary":"Analiz yapilamadi."}
        raw = result["choices"][0]["message"]["content"].strip()
        return json.loads(raw[raw.find("{"):raw.rfind("}")+1])
    except Exception as e:
        print(f"AI hata: {e}")
        return {"project_type":"Bilinmiyor","risk_score":5,"wash_trading":False,"summary":"Analiz yapilamadi."}

def send_tg(msg):
    for chat_id in [TELEGRAM_CHAT_ID, TELEGRAM_CHANNEL_ID]:
        try:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": msg}, timeout=10)
        except Exception as e:
            print(f"Telegram hata: {e}")

def check_whale_alert():
    try:
        query = """{
  EVM(network: eth) {
    Transfers(
      where: {Transfer: {AmountInUSD: {gt: "1000000"}}}
      limit: {count: 5}
      orderBy: {descending: Block_Time}
    ) {
      Transfer {
        Amount
        AmountInUSD
        Currency { Name Symbol SmartContract }
        Sender
        Receiver
      }
    }
  }
}"""
        r = requests.post(
            "https://streaming.bitquery.io/graphql",
            headers={"Authorization": f"Bearer {BITQUERY_TOKEN}", "Content-Type": "application/json"},
            json={"query": query},
            timeout=15
        )
        data = r.json()
        transfers = data.get("data",{}).get("EVM",{}).get("Transfers",[])
        for tx in transfers:
            t = tx.get("Transfer",{})
            amount_usd = float(t.get("AmountInUSD",0))
            symbol = t.get("Currency",{}).get("Symbol","?")
            name = t.get("Currency",{}).get("Name","?")
            contract = t.get("Currency",{}).get("SmartContract","")
            amount = float(t.get("Amount",0))
            sender = t.get("Sender","")[:10]
            receiver = t.get("Receiver","")[:10]
            if symbol.upper() in STABLE_AND_MAJOR:
                continue
            key = f"whale_{sender}_{receiver}_{symbol}_{int(amount_usd)}"
            if is_coingecko_notified(key):
                continue
            msg = f"""🐋 BALINA HAREKETI!
💎 {name} ({symbol})
💰 Miktar: {amount:,.0f} {symbol} (${amount_usd:,.0f})
📤 Gonderen: {sender}...
📥 Alan: {receiver}...
🔎 https://etherscan.io/token/{contract}"""
            send_tg(msg)
            mark_coingecko_notified(key)
            print(f"  Whale: {symbol} ${amount_usd:,.0f}")
            time.sleep(0.5)
    except Exception as e:
        print(f"Whale alert hata: {e}")

def check_coingecko_trending():
    try:
        r = requests.get("https://api.coingecko.com/api/v3/search/trending", timeout=15)
        data = r.json()
        coins = data.get("coins", [])
        for item in coins[:5]:
            coin = item.get("item", {})
            coin_id = coin.get("id","")
            name = coin.get("name","")
            symbol = coin.get("symbol","")
            price_change = coin.get("data",{}).get("price_change_percentage_24h",{}).get("usd",0)
            market_cap = coin.get("data",{}).get("market_cap","")
            if not coin_id or is_coingecko_notified(coin_id):
                continue
            if symbol.upper() in STABLE_AND_MAJOR:
                continue
            msg = f"""🔥 CoinGecko Trend!
💎 {name} ({symbol})
📈 24s Degisim: %{price_change:.1f}
💰 Piyasa Degeri: {market_cap}
🔎 https://coingecko.com/en/coins/{coin_id}"""
            send_tg(msg)
            mark_coingecko_notified(coin_id)
            print(f"  CoinGecko trend: {symbol}")
            time.sleep(0.5)
    except Exception as e:
        print(f"CoinGecko trend hata: {e}")

def check_coingecko_new():
    try:
        r = requests.get("https://api.coingecko.com/api/v3/coins/list/new", timeout=15)
        data = r.json()
        if not isinstance(data, list):
            return
        for coin in data[:3]:
            coin_id = coin.get("id","")
            name = coin.get("name","")
            symbol = coin.get("symbol","")
            activated_at = coin.get("activated_at",0)
            if not coin_id or is_coingecko_notified(f"new_{coin_id}"):
                continue
            tarih = datetime.fromtimestamp(activated_at).strftime('%d.%m.%Y %H:%M') if activated_at else 'Bilinmiyor'
            msg = f"""🆕 CoinGecko Yeni Listing!
💎 {name} ({symbol.upper()})
🕐 Listelenme: {tarih}
🔎 https://coingecko.com/en/coins/{coin_id}"""
            send_tg(msg)
            mark_coingecko_notified(f"new_{coin_id}")
            print(f"  CoinGecko yeni: {symbol}")
            time.sleep(0.5)
    except Exception as e:
        print(f"CoinGecko yeni listing hata: {e}")

def send_morning_bulletin():
    now = datetime.now()
    if now.hour != 9 or now.minute > 5:
        return
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT * FROM tokens
            WHERE notified=1
            AND discovered_at > datetime('now', '-24 hours')
            ORDER BY risk_score ASC, volume_24h DESC
            LIMIT 5
        """).fetchall()
        conn.close()
        if not rows:
            return
        msg = "🌅 Sabah Bulteni - En Iyi Tokenlar\n\n"
        for i, row in enumerate(rows, 1):
            row = dict(row)
            emoji = "🟢" if row["risk_score"] <= 3 else "🟡" if row["risk_score"] <= 6 else "🔴"
            msg += f"{i}. {row['base_name']} ({row['base_symbol']})\n"
            msg += f"   {emoji} Risk: {row['risk_score']}/10 | Hacim: ${row['volume_24h']:,.0f}\n"
            msg += f"   https://dexscreener.com/{row['chain_id']}/{row['pair_address']}\n\n"
        send_tg(msg)
        print("Sabah bulteni gonderildi.")
    except Exception as e:
        print(f"Sabah bulteni hata: {e}")

def check_price_changes():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM tokens WHERE notified=1").fetchall()
        conn.close()
        for row in rows:
            row = dict(row)
            addr = row["pair_address"]
            chain = row["chain_id"]
            old_price = float(row["price_usd"] or 0)
            if old_price == 0:
                continue
            try:
                r = requests.get(f"https://api.dexscreener.com/latest/dex/pairs/{chain}/{addr}", timeout=10)
                data = r.json()
                pairs = data.get("pairs") or []
                if not pairs:
                    continue
                new_price = float(pairs[0].get("priceUsd") or 0)
                if new_price == 0:
                    continue
                change = ((new_price - old_price) / old_price) * 100
                if change >= 50:
                    send_tg(f"🚀 PUMP! {row['base_name']} ({row['base_symbol']})\n+{change:.1f}% yukseldi!\nEski: ${old_price:.6f} Yeni: ${new_price:.6f}\nhttps://dexscreener.com/{chain}/{addr}")
                    conn2 = sqlite3.connect(DB_PATH)
                    conn2.execute("UPDATE tokens SET price_usd=? WHERE pair_address=?", (str(new_price), addr))
                    conn2.commit()
                    conn2.close()
                elif change <= -30:
                    send_tg(f"📉 DUMP! {row['base_name']} ({row['base_symbol']})\n{change:.1f}% dustu!\nEski: ${old_price:.6f} Yeni: ${new_price:.6f}\nhttps://dexscreener.com/{chain}/{addr}")
                    conn2 = sqlite3.connect(DB_PATH)
                    conn2.execute("UPDATE tokens SET price_usd=? WHERE pair_address=?", (str(new_price), addr))
                    conn2.commit()
                    conn2.close()
            except:
                pass
    except Exception as e:
        print(f"Fiyat takip hata: {e}")

def scan():
    keyword = random.choice(KEYWORDS)
    print(f"\nTarama: {datetime.now().strftime('%H:%M:%S')} | Kelime: {keyword}")
    found = 0
    seen_symbols = set()
    pairs = fetch_pairs(keyword)
    print(f"  {len(pairs)} cift bulundu")
    for pair in pairs:
        if not is_new(pair) or not ok_filter(pair):
            continue
        addr = pair.get("pairAddress","")
        if not addr or is_notified(addr):
            continue
        base_symbol = (pair.get("baseToken") or {}).get("symbol","")
        if base_symbol in seen_symbols:
            continue
        seen_symbols.add(base_symbol)
        web, tw, tg = get_socials(pair)
        token_addr = (pair.get("baseToken") or {}).get("address","")
        chain_id = pair.get("chainId","")
        liq_status, holder_status = check_token_security(token_addr, chain_id)
        age_str = get_pair_age(pair.get("pairCreatedAt"))
        txn_info = get_top_transactions(chain_id, addr)
        web_summary = analyze_website(web) if web else "Web sitesi yok"
        deployer_info = get_deployer_tokens(token_addr, chain_id)
        print(f"  Yeni: {base_symbol} ({chain_id})")
        ai = analyze(pair, web, tw, tg)
        time.sleep(1)
        base = pair.get("baseToken",{})
        liq  = pair.get("liquidity",{})
        vol  = pair.get("volume",{})
        txns = pair.get("txns",{}).get("h24",{})
        r = ai.get("risk_score",5)
        emoji = "🟢" if r<=3 else "🟡" if r<=6 else "🔴"
        wash = "⚠️ WASH TRADING TESPIT EDILDI!\n" if ai.get("wash_trading") else ""
        liq_emoji = "✅" if "kilitli" in liq_status.lower() and "degil" not in liq_status.lower() else "⚠️" if "honeypot" in liq_status.lower() else "❌"
        holder_emoji = "⚠️" if "rug" in holder_status.lower() else "🟡" if "dikkat" in holder_status.lower() else "✅"
        msg = f"""🚨 Yeni Token: {base.get("name","")} ({base_symbol})
🔗 {chain_id} | {pair.get("dexId","")}
🕐 {age_str}
💧 Likidite: ${liq.get("usd",0):,.0f} | Hacim: ${vol.get("h24",0):,.0f}
📈 Alım: {txns.get("buys",0)} | Satım: {txns.get("sells",0)}
📊 {txn_info}
🏷️ Tip: {ai.get("project_type","Bilinmiyor")} | Risk: {emoji} {r}/10
{liq_emoji} {liq_status}
{holder_emoji} {holder_status}
👤 {deployer_info}
🌐 {web_summary}
{wash}📝 {ai.get("summary","")}
🔎 https://dexscreener.com/{chain_id}/{addr}"""
        send_tg(msg)
        d = {
            "pair_address": addr, "chain_id": chain_id,
            "base_symbol": base_symbol, "base_name": base.get("name",""),
            "quote_symbol": (pair.get("quoteToken") or {}).get("symbol",""),
            "dex_id": pair.get("dexId",""), "pair_created": pair.get("pairCreatedAt",0),
            "liquidity_usd": liq.get("usd",0), "fdv_usd": pair.get("fdv",0),
            "volume_24h": vol.get("h24",0), "price_usd": str(pair.get("priceUsd","0")),
            "buys_24h": txns.get("buys",0), "sells_24h": txns.get("sells",0),
            "website": web, "twitter": tw, "telegram": tg,
            "ai_summary": ai.get("summary",""), "risk_score": r,
            "project_type": ai.get("project_type","Bilinmiyor"),
            "liq_status": liq_status, "holder_status": holder_status,
            "web_summary": web_summary, "notified": 1,
            "discovered_at": datetime.now(timezone.utc).isoformat()
        }
        save_token(d)
        print(f"  Bildirim: {base_symbol}")
        found += 1
    print(f"Bitti. {found} yeni token.")
    check_price_changes()
    check_coingecko_trending()
    check_coingecko_new()
    check_whale_alert()
    send_morning_bulletin()

init_db()
print(f"API Key uzunlugu: {len(OPENROUTER_API_KEY)}")
while True:
    scan()
    print(f"{SCAN_INTERVAL_MIN} dakika bekleniyor...")
    time.sleep(SCAN_INTERVAL_MIN * 60)