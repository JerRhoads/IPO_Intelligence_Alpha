# app.py
# IPO Intelligence Alpha — Build v1.0.0
# Final upgraded Streamlit IPO tracker with:
# - Two-column S-1 extractor layout (hardcoded extractor endpoint)
# - Implied market cap, underwriter credibility, lockup parsing, VC detection
# - Red-flag detector, watchlist + CSV export
# - Valuation comps + peer medians (FMP)
# - TAM/CAGR hybrid mapping (curated + search fallback)
# - Footer: "Created by Jeremiah D. Rhoads"
#
# NOTE: This file intentionally hardcodes your provided API keys and the
# extractor endpoint as constants (so the sidebar won't expose them).
# Keys were supplied by you previously.
#
# Replace / drop this file into your project folder and run:
#   streamlit run app.py
#
# IMPORTANT: Restart Streamlit after replacing app.py (CTRL+C then re-run).
# Also consider moving keys to environment vars for production.

import streamlit as st
import requests
import pandas as pd
import re
from urllib.parse import quote
from datetime import date, timedelta

# -------------------------
# Build & Attribution Info
# -------------------------
BUILD_LABEL = "Build v1.0.0 (IPO Intelligence Alpha)"
CREATED_BY = "Created by Jeremiah D. Rhoads"

# -------------------------
# HARDCODED API KEYS & ENDPOINTS (internal constants)
# These are intentionally not exposed in the sidebar.
# -------------------------
# FinancialModelingPrep (FMP)
FMP_API_KEY = "tyD3S2Vhp8LNmAUxDGYSP8Nbgf06fbLC"

# Finnhub
FINNHUB_API_KEY = "d3erdqhr01qh40ffmj4gd3erdqhr01qh40ffmj50"

# SecAPI (your key) and the S-1 extractor endpoint you gave:
SECAPI_KEY = "a3a721cb9bb1463f6e449e65757b2c8ae0c91b69c400309743a413e34446fa20"
SECAPI_S1_EXTRACTOR_ENDPOINT = "https://api.sec-api.io/form-s1-424b4"

# -------------------------
# Streamlit Page Config
# -------------------------
st.set_page_config(page_title="IPO Intelligence Alpha", page_icon="📈", layout="wide")
# Top banner
st.markdown(f"<h3 style='margin:0'>{BUILD_LABEL}</h3>", unsafe_allow_html=True)

# -------------------------
# Sidebar - Visible Settings (keys not editable here)
# -------------------------
with st.sidebar:
    st.header("IPO Intelligence — Controls")
    today = date.today()
    default_start = date(today.year, today.month, 1)
    next_month = (default_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    default_end = next_month - timedelta(days=1)
    start = st.date_input("From", default_start)
    end = st.date_input("To", default_end)
    st.divider()
    st.subheader("Valuation display")
    val_view = st.selectbox("Valuation View", ["Bullets", "Table", "Peer-relative"], index=2)
    st.caption("Switch how valuation comps are shown under each company")
    st.divider()
    use_wiki = st.checkbox("Use Wikipedia summaries when available", True)
    show_debug = st.checkbox("Show debug logs (developer)", False)
    st.divider()
    st.subheader("Watchlist")
    enable_watchlist = st.checkbox("Enable watchlist", True)
    st.caption("Watchlist persists to session state and can be exported to CSV")
    st.divider()
    st.caption("App hardcoded: SEC S-1 extractor endpoint (hidden).")

# -------------------------
# Utility functions
# -------------------------
def format_price(price, min_p, max_p):
    if price:
        return f"${price}"
    if min_p and max_p:
        return f"${min_p} – ${max_p}"
    if min_p and not max_p:
        return f"${min_p}+"
    if max_p and not min_p:
        return f"Up to ${max_p}"
    return "—"

def moneyfmt(n):
    try:
        n = float(n)
    except Exception:
        return "—"
    if n >= 1e12:
        return f"${round(n/1e12,2)}T"
    if n >= 1e9:
        return f"${round(n/1e9,2)}B"
    if n >= 1e6:
        return f"${round(n/1e6,2)}M"
    return f"${round(n,2)}"

def clearbit_logo_url(website_or_domain):
    if not website_or_domain:
        return None
    d = website_or_domain.replace("http://","").replace("https://","").split("/")[0]
    return f"https://logo.clearbit.com/{d}"

# -------------------------
# FMP + Finnhub fetch helpers
# -------------------------
def fetch_fmp_ipo(start, end, apikey):
    try:
        url = f"https://financialmodelingprep.com/api/v3/ipo_calendar?from={start}&to={end}&apikey={apikey}"
        r = requests.get(url, timeout=20)
        if r.status_code == 200:
            data = r.json() or []
            rows = []
            for it in data:
                rows.append({
                    "source": "FMP",
                    "date": it.get("date"),
                    "company": it.get("company"),
                    "symbol": it.get("symbol"),
                    "exchange": it.get("exchange"),
                    "price": it.get("price"),
                    "price_min": it.get("priceRangeLow"),
                    "price_max": it.get("priceRangeHigh"),
                    "shares": it.get("shares"),
                    "status": it.get("status"),
                    "deal_type": it.get("dealType"),
                })
            return rows
    except Exception as e:
        if show_debug: st.sidebar.write("FMP IPO fetch error:", e)
    return []

def fetch_finnhub_ipo(start, end, token):
    if not token:
        return []
    try:
        url = f"https://finnhub.io/api/v1/calendar/ipo?from={start}&to={end}&token={token}"
        r = requests.get(url, timeout=20)
        if r.status_code == 200:
            js = r.json() or {}
            items = js.get("ipoCalendar", []) or js.get("data", []) or []
            rows = []
            for it in items:
                rows.append({
                    "source": "Finnhub",
                    "date": it.get("date"),
                    "company": it.get("name") or it.get("company"),
                    "symbol": it.get("symbol"),
                    "exchange": it.get("exchange"),
                    "price": it.get("price"),
                    "price_min": it.get("price_min") or it.get("priceRangeLow"),
                    "price_max": it.get("price_max") or it.get("priceRangeHigh"),
                    "shares": it.get("numberOfShares") or it.get("shares"),
                    "status": it.get("status"),
                    "deal_type": it.get("dealType"),
                })
            return rows
    except Exception as e:
        if show_debug: st.sidebar.write("Finnhub IPO fetch error:", e)
    return []

def fetch_company_profile(symbol, company_name, fmp_key, finnhub_key):
    profile = {"industry": None, "sector": None, "website": None, "description": None, "country": None, "exchange": None, "logo": None, "cik": None}
    # Try FMP
    if symbol and fmp_key:
        try:
            r = requests.get(f"https://financialmodelingprep.com/api/v3/profile/{symbol}?apikey={fmp_key}", timeout=12)
            if r.status_code == 200:
                j = r.json()
                if isinstance(j, list) and j:
                    p = j[0]
                    profile.update({
                        "industry": p.get("industry"),
                        "sector": p.get("sector"),
                        "website": p.get("website"),
                        "description": p.get("description"),
                        "country": p.get("country"),
                        "exchange": p.get("exchangeShortName") or p.get("exchange"),
                        "logo": p.get("image") or None,
                        "cik": p.get("cik")
                    })
                    return profile
        except Exception as e:
            if show_debug: st.sidebar.write("FMP profile error:", e)
    # Try Finnhub as fallback
    if symbol and finnhub_key:
        try:
            r = requests.get(f"https://finnhub.io/api/v1/stock/profile2?symbol={symbol}&token={finnhub_key}", timeout=12)
            if r.status_code == 200:
                p = r.json() or {}
                profile.update({
                    "industry": p.get("finnhubIndustry"),
                    "website": p.get("weburl"),
                    "country": p.get("country"),
                    "exchange": p.get("exchange"),
                    "logo": p.get("logo"),
                    "cik": p.get("cik")
                })
                return profile
        except Exception as e:
            if show_debug: st.sidebar.write("Finnhub profile error:", e)
    return profile

# -------------------------
# Valuation & sector median helpers
# -------------------------
def fetch_fmp_enterprise_value(symbol, fmp_key):
    if not symbol or not fmp_key:
        return None
    try:
        r = requests.get(f"https://financialmodelingprep.com/api/v3/enterprise-values/{symbol}?apikey={fmp_key}", timeout=12)
        if r.status_code == 200:
            data = r.json() or []
            if isinstance(data, list) and data:
                latest = data[0]
                ev = latest.get("enterpriseValue") or latest.get("enterpriseValueCalculated") or latest.get("marketCap")
                return ev
    except Exception as e:
        if show_debug: st.sidebar.write("FMP EV fetch error:", e)
    return None

def fetch_fmp_key_metrics(symbol, fmp_key):
    if not symbol or not fmp_key:
        return {}
    try:
        r = requests.get(f"https://financialmodelingprep.com/api/v3/key-metrics-ttm/{symbol}?apikey={fmp_key}", timeout=12)
        if r.status_code == 200:
            data = r.json() or []
            if isinstance(data, list) and data:
                return data[0]
    except Exception as e:
        if show_debug: st.sidebar.write("FMP key metrics error:", e)
    return {}

def compute_multiples(symbol, fmp_key):
    km = fetch_fmp_key_metrics(symbol, fmp_key)
    ev = fetch_fmp_enterprise_value(symbol, fmp_key)
    revenue = km.get("revenueTTM") or km.get("revenue")
    ebitda = km.get("ebitda") or km.get("ebitdaTTM")
    market_cap = km.get("marketCap") or km.get("marketCapitalization")
    def safe_div(a,b):
        try:
            if a is None or b is None or float(b)==0:
                return None
            return round(float(a)/float(b),2)
        except Exception:
            return None
    return {
        "EV/Revenue": safe_div(ev, revenue),
        "EV/EBITDA": safe_div(ev, ebitda),
        "Price/Sales": safe_div(market_cap, revenue),
        "MarketCap": market_cap,
        "RevenueTTM": revenue,
        "EBITDA": ebitda
    }

def fetch_sector_median(sector, fmp_key):
    if not sector or not fmp_key:
        return {}
    try:
        r = requests.get(f"https://financialmodelingprep.com/api/v3/key-metrics-ttm-bulk?apikey={fmp_key}", timeout=20)
        if r.status_code == 200:
            data = r.json() or []
            rows = [d for d in data if d.get("sector") and d.get("sector").lower()==sector.lower()]
            if not rows:
                return {}
            def median(vals):
                s = sorted([v for v in vals if v is not None])
                if not s:
                    return None
                n = len(s); mid = n//2
                return round(s[mid],2) if n%2 else round((s[mid-1]+s[mid])/2,2)
            ev_sales = median([r.get("evToRevenue") or r.get("evToRevenueMultiple") for r in rows])
            ev_ebitda = median([r.get("evToEbitda") or r.get("evToEbitdaMultiple") for r in rows])
            price_sales = median([r.get("priceToSales") or r.get("priceToSalesRatio") for r in rows])
            return {"EV/Revenue_median": ev_sales, "EV/EBITDA_median": ev_ebitda, "Price/Sales_median": price_sales}
    except Exception as e:
        if show_debug: st.sidebar.write("Sector median fetch error:", e)
    return {}

# -------------------------
# SEC S-1 Extractor integration (hardcoded endpoint)
# -------------------------
def fetch_s1_extracted(company_name=None, ticker=None):
    if not SECAPI_KEY or not SECAPI_S1_EXTRACTOR_ENDPOINT:
        return None
    q = company_name or ticker or ""
    if not q:
        return None
    payload = {
        "query": {"query_string": {"query": f"(companyName:\"{company_name}\" OR ticker:\"{ticker}\")"}},
        "size": 1
    }
    headers = {"Authorization": f"Bearer {SECAPI_KEY}", "Content-Type": "application/json"}
    try:
        r = requests.post(SECAPI_S1_EXTRACTOR_ENDPOINT, json=payload, headers=headers, timeout=25)
        if r.status_code in (200,201):
            return r.json() or None
        else:
            if show_debug:
                st.sidebar.write("S1 extractor status:", r.status_code, r.text)
    except Exception as e:
        if show_debug: st.sidebar.write("S1 extractor error:", e)
    return None

# -------------------------
# Extraction signal utilities (underwriters, VC detection, lockup, red flags)
# -------------------------
TOP_UNDERWRITERS = ["Goldman Sachs","Morgan Stanley","J.P. Morgan","JPMorgan","Bank of America","Barclays","Citigroup","Citi","Credit Suisse","UBS","Deutsche Bank"]
TOP_VCS = ["Sequoia","Andreessen Horowitz","a16z","Tiger Global","SoftBank","Khosla","Benchmark","Accel","Founders Fund","Lightspeed","Battery Ventures","NEA","Greylock"]

def underwriter_credibility_score(underwriters_list):
    if not underwriters_list:
        return {"score":"Unknown", "matches":[]}
    matches = [u for u in underwriters_list if any(t.lower() in u.lower() for t in TOP_UNDERWRITERS)]
    if len(matches) >= 2:
        return {"score":"High", "matches": matches}
    if len(matches) == 1:
        return {"score":"Medium", "matches": matches}
    return {"score":"Low", "matches": underwriters_list}

def detect_vc_backers(text):
    if not text:
        return []
    found = []
    for vc in TOP_VCS:
        if re.search(r'\b'+re.escape(vc)+r'\b', text, re.I):
            found.append(vc)
    return sorted(set(found))

def parse_lockup(text):
    if not text:
        return None
    m = re.search(r'lock[-\s]?up[^\d]{0,30}(\d{1,4})\s*(days|day|months|month|m)', text, re.I)
    if m:
        return f"{m.group(1)} {m.group(2)}"
    m2 = re.search(r'(\d{2,4})\s*days', text, re.I)
    if m2:
        return f"{m2.group(1)} days"
    return None

def red_flag_scan(text, multiples):
    flags = []
    if text:
        risk_phrases = ["going concern","material adverse","significant doubt","revenue recognition","related party","fraud","suspicious","substantial doubt"]
        tl = text.lower()
        for ph in risk_phrases:
            if ph in tl:
                flags.append(f"Phrase: '{ph}' found in extracted text")
    if multiples:
        ev_rev = multiples.get("EV/Revenue")
        price_sales = multiples.get("Price/Sales")
        if ev_rev and ev_rev > 20:
            flags.append(f"High EV/Revenue: {ev_rev}x")
        if price_sales and price_sales > 30:
            flags.append(f"High Price/Sales: {price_sales}x")
    return flags

# -------------------------
# TAM/CAGR hybrid map
# -------------------------
TAM_CAGR_MAP = {
    "cybersecurity": {"tam":"Global cybersecurity market ~200B (2024 est.)", "cagr":"~12% CAGR to 2030", "sources":[{"title":"Grand View Research","url":"https://www.grandviewresearch.com/industry-analysis/cyber-security-market"}]},
    "ai": {"tam":"AI software segments vary; generative AI segments show very fast growth", "cagr":"~30%+ CAGR for some generative AI subsegments", "sources":[{"title":"MarketsandMarkets","url":"https://www.marketsandmarkets.com/"}]},
    "biotechnology": {"tam":"Broad biotech market >$900B", "cagr":"~7-10% depending on subsegment", "sources":[{"title":"Fortune Business Insights","url":"https://www.fortunebusinessinsights.com/"}]},
    "renewable energy": {"tam":"Renewable energy market large and growing", "cagr":"~8-10% for many subsegments", "sources":[{"title":"IEA","url":"https://www.iea.org/"}]},
    "fintech": {"tam":"Fintech sizable; payments/lending subsegments large", "cagr":"~20% for some fintech segments", "sources":[{"title":"Statista","url":"https://www.statista.com/"}]},
}

def get_tam_cagr(sector_or_industry):
    key = (sector_or_industry or "").lower()
    for k in TAM_CAGR_MAP:
        if k in key:
            return TAM_CAGR_MAP[k]
    return {"tam":"No curated TAM available for this sector in the local mapping.", "cagr":"Unknown", "sources":[{"title":"Search results","url":f"https://www.google.com/search?q={quote('market size '+(sector_or_industry or ''))}"}]}

# -------------------------
# Fetch IPOs and enrich
# -------------------------
start_str = start.strftime("%Y-%m-%d")
end_str = end.strftime("%Y-%m-%d")

rows = []
rows += fetch_fmp_ipo(start_str, end_str, FMP_API_KEY)
rows += fetch_finnhub_ipo(start_str, end_str, FINNHUB_API_KEY)
df = pd.DataFrame(rows).drop_duplicates(subset=['date','company','symbol','source'], keep='first')

if df.empty:
    st.info("No IPOs found for the selected window. Try widening the date range.")
    st.stop()

# session state watchlist
if "watchlist" not in st.session_state:
    st.session_state["watchlist"] = []

enriched = []
for _, r in df.sort_values("date").iterrows():
    symbol = (r.get("symbol") or "")[:30]
    profile = fetch_company_profile(symbol, r.get("company"), FMP_API_KEY, FINNHUB_API_KEY)
    # optional wiki summary (lightweight)
    summary = None
    if use_wiki and r.get("company"):
        try:
            jq = requests.get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(r.get('company'))}", timeout=6)
            if jq.status_code == 200:
                summary = jq.json().get("extract")
        except Exception:
            summary = None
    logo = profile.get("logo") or clearbit_logo_url(profile.get("website"))
    price_str = format_price(r.get("price"), r.get("price_min"), r.get("price_max"))
    multiples = compute_multiples(symbol, FMP_API_KEY)
    sector_med = fetch_sector_median(profile.get("sector"), FMP_API_KEY) if profile.get("sector") else {}
    # S-1 extraction (hardcoded endpoint)
    s1_extracted = fetch_s1_extracted(r.get("company"), symbol)
    # parse signals robustly
    combined_text = ""
    underwriters = []
    lockup = None
    vc_backers = []
    s1_url = None
    if s1_extracted:
        # Attempt to extract text/sections and urls robustly (responses vary)
        def recursive_search(obj):
            txt = ""
            if isinstance(obj, dict):
                for k,v in obj.items():
                    if isinstance(v, (dict,list)):
                        txt += recursive_search(v)
                    elif isinstance(v, str):
                        # collect long textual fields
                        if len(v) > 40:
                            txt += " " + v
                # look for possible url keys
                for key in ("linkToFilingDetails","filingUrl","htmlUrl","link"):
                    if key in obj and isinstance(obj.get(key), str) and obj.get(key).startswith("http"):
                        return txt, obj.get(key)
            elif isinstance(obj, list):
                for it in obj:
                    subtxt, url = recursive_search(it)
                    txt += subtxt
                    if url:
                        return txt, url
            return txt, None

        try:
            raw_text, found_url = recursive_search(s1_extracted)
            combined_text = raw_text or ""
            s1_url = found_url
            # find underwriter strings by searching for "underwriter" word vicinity
            uw_matches = re.findall(r'([A-Z][\w\s,&\-\.]{2,80} (?:LLC|Co\.|Inc\.|Bank|Securities|Capital|Bancorp|Corporation|Corp\.|Group))', combined_text)
            # more conservative: search for known underwriter names
            uw_detected = [m for m in TOP_UNDERWRITERS if re.search(re.escape(m), combined_text, re.I)]
            if uw_detected:
                underwriters = uw_detected
            elif uw_matches:
                underwriters = list(dict.fromkeys(uw_matches))[:6]
            # lockup parsing
            lockup = parse_lockup(combined_text)
            # vc backers
            vc_backers = detect_vc_backers(combined_text)
        except Exception as e:
            if show_debug: st.sidebar.write("S-1 parse error:", e)

    # implied market cap if price & shares available
    implied_marketcap = None
    try:
        shares_raw = r.get("shares") or 0
        if isinstance(shares_raw, str):
            shares_raw = int(re.sub(r'[^\d]', '', shares_raw) or 0)
        price_val = None
        if r.get("price"):
            try:
                price_val = float(r.get("price"))
            except:
                price_val = None
        elif r.get("price_min") and r.get("price_max"):
            try:
                price_val = (float(r.get("price_min")) + float(r.get("price_max")))/2
            except:
                price_val = None
        if price_val and shares_raw:
            implied_marketcap = price_val * shares_raw
    except Exception:
        implied_marketcap = None

    # red flags
    flags = red_flag_scan(combined_text or (profile.get("description") or ""), multiples)

    enriched.append({
        "Date": r.get("date"),
        "Company": r.get("company"),
        "Symbol": symbol or "TBD",
        "Exchange": r.get("exchange"),
        "Projected Price": price_str,
        "Shares (approx)": r.get("shares"),
        "Industry": profile.get("industry"),
        "Sector": profile.get("sector"),
        "Country": profile.get("country"),
        "Website": profile.get("website"),
        "Summary": summary or profile.get("description"),
        "LogoURL": logo,
        "Source": r.get("source"),
        "Multiples": multiples,
        "SectorMedian": sector_med,
        "S1_extracted": s1_extracted,
        "S1_url": s1_url,
        "Underwriters": underwriters,
        "UnderwriterCred": underwriter_credibility_score(underwriters),
        "Lockup": lockup,
        "VC_backers": vc_backers,
        "ImpliedMarketCap": implied_marketcap,
        "RedFlags": flags,
        "TAM": get_tam_cagr(profile.get("sector") or profile.get("industry"))
    })

ed = pd.DataFrame(enriched)

# -------------------------
# Top summary UI
# -------------------------
left, right = st.columns([1,1])
with left:
    st.metric("IPOs in window", len(ed))
with right:
    exchanges = ed["Exchange"].fillna("—").value_counts().to_dict()
    st.write("**By Exchange**")
    st.write(", ".join([f"{k}: {v}" for k,v in exchanges.items()]))
st.markdown("---")

# -------------------------
# Company Cards (each with 2-column S-1 layout)
# -------------------------
for idx, row in ed.iterrows():
    with st.container():
        cols = st.columns([0.7, 0.3])
        leftcol, rightcol = cols[0], cols[1]
        with leftcol:
            st.subheader(f"{row['Company']}  ({row['Symbol']})")
            st.caption(f"Planned date: {row['Date']}  •  Exchange: {row['Exchange'] or '—'}  •  Source: {row['Source']}")
            st.write(f"**Industry:** {row['Industry'] or '—'}  |  **Sector:** {row['Sector'] or '—'}")
            st.write(f"**Projected IPO Price:** {row['Projected Price']}")
            st.write(f"**Shares (approx):** {row['Shares (approx)'] or '—'}")
            if row["Website"]:
                st.write(f"**Website:** {row['Website']}")
            # Company summary expander
            if row["Summary"]:
                with st.expander("Company Summary"):
                    st.write(row["Summary"])
            # Implied Market Cap
            if row.get("ImpliedMarketCap"):
                st.write(f"**Implied Market Cap (at IPO):** {moneyfmt(row.get('ImpliedMarketCap'))}")
            else:
                st.info("Implied Market Cap: N/A (price or shares missing)")

            # Valuation display
            mult = row.get("Multiples") or {}
            sector_med = row.get("SectorMedian") or {}
            if val_view == "Bullets":
                bullets = []
                if mult.get("EV/Revenue") is not None:
                    bullets.append(f"EV/Revenue: {mult.get('EV/Revenue')}x")
                if mult.get("EV/EBITDA") is not None:
                    bullets.append(f"EV/EBITDA: {mult.get('EV/EBITDA')}x")
                if mult.get("Price/Sales") is not None:
                    bullets.append(f"Price/Sales: {mult.get('Price/Sales')}x")
                if bullets:
                    st.write("**Valuation Multiples:** " + " • ".join(bullets))
                else:
                    st.write("**Valuation Multiples:** No company multiples available")
            elif val_view == "Table":
                tbl = {"Metric":["EV/Revenue","EV/EBITDA","Price/Sales"],
                       "Company":[mult.get("EV/Revenue"), mult.get("EV/EBITDA"), mult.get("Price/Sales")],
                       "Sector Median":[sector_med.get("EV/Revenue_median"), sector_med.get("EV/EBITDA_median"), sector_med.get("Price/Sales_median")]}
                st.table(pd.DataFrame(tbl))
            else:
                rel = []
                if mult.get("EV/Revenue") is not None and sector_med.get("EV/Revenue_median") is not None:
                    diff = mult.get("EV/Revenue") - sector_med.get("EV/Revenue_median")
                    rel.append(f"EV/Revenue: {mult.get('EV/Revenue')}x ({'+' if diff>0 else ''}{round(diff,2)} vs sector median)")
                if mult.get("EV/EBITDA") is not None and sector_med.get("EV/EBITDA_median") is not None:
                    diff = mult.get("EV/EBITDA") - sector_med.get("EV/EBITDA_median")
                    rel.append(f"EV/EBITDA: {mult.get('EV/EBITDA')}x ({'+' if diff>0 else ''}{round(diff,2)} vs sector median)")
                if rel:
                    st.write("**Peer-relative valuation:**")
                    for rline in rel:
                        st.write("- " + rline)
                else:
                    st.write("**Peer-relative valuation:** No complete data to compare")

            # Underwriters & Credibility
            uw = row.get("Underwriters") or []
            cred = row.get("UnderwriterCred") or {}
            if uw:
                st.write(f"**Lead Underwriters:** {', '.join(uw)}")
                st.write(f"**Underwriter Credibility:** {cred.get('score')} (matches: {', '.join(cred.get('matches') or [])})")
            else:
                st.write("**Lead Underwriters:** Not detected in extraction (placeholder shown)")

            # VC backers
            if row.get("VC_backers"):
                st.write(f"**VC / Sponsors detected:** {', '.join(row.get('VC_backers'))}")
            else:
                st.write("**VC / Sponsors detected:** None found (placeholder)")

            # Lockup parse
            if row.get("Lockup"):
                st.write(f"**Lockup period (parsed):** {row.get('Lockup')}")
            else:
                st.write("**Lockup period (parsed):** Not found (placeholder)")

            # Red flags (prominent)
            flags = row.get("RedFlags") or []
            if flags:
                st.warning("Red flags: " + " | ".join(flags))
            else:
                st.success("No automatic red flags detected (heuristic)")

            # TAM / CAGR expander (two-column display: left main, right compact)
            tam = row.get("TAM") or {}
            with st.expander("📊 Sector Outlook (expand for sources)"):
                st.write(f"**TAM:** {tam.get('tam')}")
                st.write(f"**CAGR:** {tam.get('cagr')}")
                if tam.get("sources"):
                    st.write("**Sources:**")
                    for s in tam.get("sources"):
                        st.markdown(f"- [{s.get('title')}]({s.get('url')})")

            # Watchlist
            if enable_watchlist:
                btn_key = f"watch_add_{idx}"
                if st.button("Add to Watchlist", key=btn_key):
                    st.session_state.watchlist.append({
                        "Company": row["Company"],
                        "Symbol": row["Symbol"],
                        "Date": row["Date"],
                        "ImpliedMarketCap": row.get("ImpliedMarketCap")
                    })
                    st.success("Added to watchlist")

        # Right column: Logo + Two-column S-1 extracted sections stacked vertically in right column
        with rightcol:
            if row.get("LogoURL"):
                st.image(row.get("LogoURL"), use_column_width=True)
            else:
                st.caption("Logo: Not available")
            st.markdown("### S-1 Extracted (Two-Column view below)")
            # Two-column S-1 display: left side = Business & Use of Proceeds; right side = Underwriters & Risk/RedFlags
            with st.expander("📄 S-1 Extracted Sections (two-column)"):
                # Create two columns inside expander
                c_left, c_right = st.columns(2)
                # Left: Business & Use of Proceeds
                with c_left:
                    st.write("**Business Overview (extracted)**")
                    btext = "No business overview extracted (placeholder)"
                    try:
                        # try to find business fields
                        if row.get("S1_extracted"):
                            # attempt lightweight search for "business" text
                            txt = str(row.get("S1_extracted"))
                            m = re.search(r'(?i)(business[^\n]{0,2000})', txt)
                            if m:
                                btext = m.group(0)[:5000]
                            else:
                                # fallback to any long extracted text snippet
                                s = re.findall(r'([A-Z][^\n]{200,800})', txt)
                                if s:
                                    btext = s[0][:5000]
                    except Exception:
                        btext = "Error extracting business text (debug mode for raw JSON)"
                    st.write(btext)
                    st.write("---")
                    st.write("**Use of Proceeds (extracted)**")
                    uptext = "No Use of Proceeds extracted (placeholder)"
                    try:
                        if row.get("S1_extracted"):
                            txt = str(row.get("S1_extracted"))
                            m2 = re.search(r'(?i)(use of proceeds[^\n]{0,2000})', txt)
                            if m2:
                                uptext = m2.group(0)[:4000]
                    except Exception:
                        uptext = "Error extracting use of proceeds (enable debug to see raw JSON)"
                    st.write(uptext)

                # Right: Underwriters & Risk Factors snippet
                with c_right:
                    st.write("**Underwriters (extracted)**")
                    uw_display = row.get("Underwriters") or ["No underwriter list extracted (placeholder)"]
                    st.write(", ".join(uw_display))
                    st.write("---")
                    st.write("**Risk Factors (snippet)**")
                    rtext = "No risk factors extracted (placeholder)"
                    try:
                        if row.get("S1_extracted"):
                            txt = str(row.get("S1_extracted"))
                            m3 = re.search(r'(?i)(risk factor[s]?[^\n]{0,2000})', txt)
                            if m3:
                                rtext = m3.group(0)[:4000]
                            else:
                                # search for common red-flag phrases as snippet
                                rf_phrases = ["going concern","material adverse","substantial doubt","revenue recognition"]
                                for ph in rf_phrases:
                                    if ph in txt.lower():
                                        idx = txt.lower().find(ph)
                                        rtext = txt[idx: idx+800]
                                        break
                    except Exception:
                        rtext = "Error extracting risk factors (enable debug for raw JSON)"
                    st.write(rtext)
                # show link to full filing if extractor returned it
                if row.get("S1_url"):
                    st.markdown(f"[🔗 View full filing]({row.get('S1_url')})")
                else:
                    st.write("Full filing link: Not detected (placeholder)")

    st.markdown("---")

# -------------------------
# Watchlist UI + Export
# -------------------------
if enable_watchlist:
    st.subheader("Watchlist")
    if st.session_state.get("watchlist"):
        wdf = pd.DataFrame(st.session_state.watchlist)
        st.dataframe(wdf, use_container_width=True)
        st.download_button("Download Watchlist CSV", data=wdf.to_csv(index=False).encode("utf-8"), file_name="ipo_watchlist.csv", mime="text/csv")
    else:
        st.info("Watchlist is empty — add items using 'Add to Watchlist'")

# -------------------------
# Footer with attribution centered
# -------------------------
st.markdown("<hr>", unsafe_allow_html=True)
st.markdown(f"<div style='text-align:center; font-size:12px; color:gray;'>{CREATED_BY}</div>", unsafe_allow_html=True)
st.caption("Disclaimer: This tool aggregates third-party APIs and provides heuristics for screening only. Not investment advice.")

# -------------------------
# Debug help: raw JSON dumps when show_debug is True
# -------------------------
if show_debug:
    st.markdown("---")
    st.subheader("DEBUG: Raw enriched dataframe")
    st.write(ed.to_dict(orient="records")[:5])