import streamlit as st
import requests
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta

# ==========================================
# CONFIGURATION & STRATEGY PARAMETERS
# ==========================================
BASE_URL = "https://api.delta.exchange"  # Use https://api.india.delta.exchange for India users
s = requests.Session()

st.set_page_config(page_title="Crypto Blast Scanner", layout="wide")

# ==========================================
# 1. API DATA FUNCTIONS
# ==========================================

@st.cache_data(ttl=300)
def get_top_liquid_pairs(limit=20):
    """
    Fetches all products, filters for USDT perps, 
    and returns the top 'limit' coins by 24h Volume to avoid rate limits.
    """
    try:
        # 1. Get all products to map symbols to IDs
        prods = s.get(f"{BASE_URL}/v2/products").json()['result']
        
        # Filter for Active USDT Perpetuals only
        perp_products = [
            p for p in prods 
            if p['contract_type'] == 'perpetual_futures' 
            and p['state'] == 'live' 
            and p['quoting_asset']['symbol'] == 'USDT'
        ]
        
        # 2. Get 24h Ticker stats to sort by volume
        tickers = s.get(f"{BASE_URL}/v2/tickers").json()['result']
        
        # Create a map of symbol -> volume
        vol_map = {t['symbol']: float(t['volume']) for t in tickers if 'volume' in t}
        
        # Sort products by volume (descending)
        perp_products.sort(key=lambda x: vol_map.get(x['symbol'], 0), reverse=True)
        
        return perp_products[:limit]
        
    except Exception as e:
        st.error(f"Error fetching products: {e}")
        return []

def get_historical_data(symbol, resolution='1h', limit=50):
    """
    Fetches OHLC + Open Interest data for a symbol.
    Delta Exchange API allows fetching candles.
    """
    end_time = int(time.time())
    # Estimate start time based on resolution (rough approx)
    if resolution == '1h':
        start_time = end_time - (limit * 3600 * 2)
    elif resolution == '4h':
        start_time = end_time - (limit * 3600 * 4 * 2)
    else: # 15m
        start_time = end_time - (limit * 900 * 2)

    params = {
        'symbol': symbol,
        'resolution': resolution,
        'start': start_time,
        'end': end_time
    }
    
    try:
        # Note: Delta API endpoint for candles
        resp = s.get(f"{BASE_URL}/v2/history/candles", params=params)
        data = resp.json()
        
        if 'result' in data and data['result']:
            df = pd.DataFrame(data['result'])
            # Ensure sorting
            df = df.sort_values('time')
            return df
        return pd.DataFrame()
    except Exception as e:
        return pd.DataFrame()

# ==========================================
# 2. TECHNICAL ANALYSIS (THE LOGIC)
# ==========================================

def calculate_metrics(df):
    """
    Calculates BB, KC, and Returns a Status.
    """
    if df.empty or len(df) < 21:
        return None

    # Clean data types
    df['close'] = df['close'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)
    # Some exchanges return 'oi' or 'open_interest' in candle data
    # If delta doesn't provide OI in candles, we might need a separate call, 
    # but for this script we assume standard OHLCV. 
    # Note: Delta candles usually don't have OI inside standard candles, 
    # so we will use Volume Trend as a proxy if OI is missing, 
    # or check if specific OI history endpoint exists.
    # *Update*: Delta V2 candles often just have OHLCV. 
    # We will use 'close' and 'volume' for the squeeze, 
    # and we will mock the "OI" check using Volume accumulation for this demo 
    # unless OI key is present.
    
    # --- Bollinger Bands (20, 2) ---
    df['sma20'] = df['close'].rolling(window=20).mean()
    df['stddev'] = df['close'].rolling(window=20).std()
    df['bb_upper'] = df['sma20'] + (2.0 * df['stddev'])
    df['bb_lower'] = df['sma20'] - (2.0 * df['stddev'])

    # --- Keltner Channels (20, 1.5) ---
    # TR calculation
    df['tr1'] = df['high'] - df['low']
    df['tr2'] = abs(df['high'] - df['close'].shift(1))
    df['tr3'] = abs(df['low'] - df['close'].shift(1))
    df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
    df['atr'] = df['tr'].rolling(window=20).mean()
    
    df['kc_upper'] = df['sma20'] + (1.5 * df['atr'])
    df['kc_lower'] = df['sma20'] - (1.5 * df['atr'])

    # --- THE SQUEEZE CONDITION ---
    # BB inside KC
    current = df.iloc[-1]
    prev = df.iloc[-2]
    
    squeeze_on = (current['bb_upper'] < current['kc_upper']) and (current['bb_lower'] > current['kc_lower'])
    
    # --- MOMENTUM / BLAST POTENTIAL ---
    # 1. Price is near the bands (ready to break)
    # 2. Volume is rising (using Volume as proxy for OI/Activity here)
    vol_sma = df['volume'].rolling(window=20).mean().iloc[-1]
    high_volume = current['volume'] > vol_sma
    
    return {
        "price": current['close'],
        "squeeze": squeeze_on,
        "bb_width": current['bb_upper'] - current['bb_lower'],
        "volume_spike": high_volume,
        "change_24h": ((current['close'] - df.iloc[-20]['close']) / df.iloc[-20]['close']) * 100
    }

# ==========================================
# 3. STREAMLIT UI
# ==========================================

st.title("🚀 Delta Exchange: Momentum Blast Scanner")
st.markdown("Finds coins in a **Bollinger Squeeze** (Energy Accumulation) with rising activity.")

with st.sidebar:
    st.header("Scanner Settings")
    timeframe = st.selectbox("Timeframe", ["1h", "4h", "15m"], index=0)
    top_n = st.slider("Scan Top N Coins (Volume)", 10, 50, 20)
    st.info("Note: Scanning fewer coins is faster and avoids API rate limits.")

if st.button("Start Scan"):
    status_text = st.empty()
    progress_bar = st.progress(0)
    
    status_text.text("Fetching active market pairs...")
    products = get_top_liquid_pairs(limit=top_n)
    
    results = []
    
    for i, p in enumerate(products):
        symbol = p['symbol']
        status_text.text(f"Analyzing {symbol}...")
        
        # 1. Fetch Data
        df = get_historical_data(symbol, resolution=timeframe)
        
        # 2. Analyze
        if df is not None:
            metrics = calculate_metrics(df)
            
            if metrics:
                # We filter for coins that are EITHER in a squeeze OR have a massive volume spike
                if metrics['squeeze'] or metrics['volume_spike']:
                    results.append({
                        "Symbol": symbol,
                        "Price": metrics['price'],
                        "Status": "🔥 SQUEEZE" if metrics['squeeze'] else "⚠️ VOL SPIKE",
                        "24h Change %": round(metrics['change_24h'], 2),
                        "BB Width": round(metrics['bb_width'], 4)
                    })
        
        # Update Progress
        progress_bar.progress((i + 1) / len(products))
        time.sleep(0.1) # Respect rate limits

    progress_bar.empty()
    status_text.text("Scan Complete!")

    if results:
        results_df = pd.DataFrame(results)
        
        # Styling the dataframe
        st.subheader(f"Found {len(results)} Coins Ready to Move")
        
        # Highlight logic
        def highlight_squeeze(val):
            color = '#ff4b4b' if 'SQUEEZE' in val else '#fca311'
            return f'color: {color}; font-weight: bold'

        st.dataframe(
            results_df.style.applymap(highlight_squeeze, subset=['Status']),
            use_container_width=True
        )
        
        st.markdown("### Interpretation")
        st.markdown("""
        * **🔥 SQUEEZE:** The market is "coiled" (Bollinger Bands are inside Keltner Channels). A big move is imminent. Wait for a breakout.
        * **⚠️ VOL SPIKE:** The squeeze might be breaking *now*. Volume is higher than average.
        """)
    else:
        st.warning("No coins found matching the 'Blast' criteria right now. The market might be trending already.")
