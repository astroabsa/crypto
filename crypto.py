import streamlit as st
import requests
import pandas as pd
import time

# ==========================================
# CONFIGURATION
# ==========================================
st.set_page_config(page_title="Crypto Blast Dashboard", layout="wide", page_icon="🚀")

BASE_URL = "https://api.delta.exchange" 
# Note: If you are in India and get connection errors, switch to: 
# BASE_URL = "https://api.india.delta.exchange"

# Fixed Settings
TIMEFRAME = '1h'
TOP_N_COINS = 25
REFRESH_SECONDS = 300  # 5 Minutes

s = requests.Session()

# ==========================================
# 1. DATA FETCHING
# ==========================================

def get_top_liquid_pairs(limit=25):
    """Fetches Top N USDT Perpetual coins by volume."""
    try:
        prods = s.get(f"{BASE_URL}/v2/products").json()['result']
        perp_products = [
            p for p in prods 
            if p['contract_type'] == 'perpetual_futures' 
            and p['state'] == 'live' 
            and p['quoting_asset']['symbol'] == 'USDT'
        ]
        
        tickers = s.get(f"{BASE_URL}/v2/tickers").json()['result']
        vol_map = {t['symbol']: float(t['volume']) for t in tickers if 'volume' in t}
        
        # Sort by volume desc
        perp_products.sort(key=lambda x: vol_map.get(x['symbol'], 0), reverse=True)
        return perp_products[:limit]
    except Exception as e:
        return []

def get_historical_data(symbol, resolution='1h', limit=50):
    """Fetches OHLC data."""
    end_time = int(time.time())
    start_time = end_time - (limit * 3600 * 2) # buffer for 1h
    
    params = {'symbol': symbol, 'resolution': resolution, 'start': start_time, 'end': end_time}
    
    try:
        resp = s.get(f"{BASE_URL}/v2/history/candles", params=params)
        data = resp.json()
        if 'result' in data and data['result']:
            df = pd.DataFrame(data['result'])
            df = df.sort_values('time')
            return df
        return pd.DataFrame()
    except:
        return pd.DataFrame()

# ==========================================
# 2. TECHNICAL ANALYSIS
# ==========================================

def analyze_coin(df):
    if df.empty or len(df) < 21:
        return None

    # Cast to float
    close = df['close'].astype(float)
    high = df['high'].astype(float)
    low = df['low'].astype(float)
    volume = df['volume'].astype(float)

    # --- BB (20, 2) ---
    sma20 = close.rolling(window=20).mean()
    stddev = close.rolling(window=20).std()
    bb_upper = sma20 + (2.0 * stddev)
    bb_lower = sma20 - (2.0 * stddev)

    # --- KC (20, 1.5) ---
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=20).mean()
    
    kc_upper = sma20 + (1.5 * atr)
    kc_lower = sma20 - (1.5 * atr)

    # Current Candle Values
    curr_close = close.iloc[-1]
    curr_sma = sma20.iloc[-1]
    curr_bb_up = bb_upper.iloc[-1]
    curr_bb_low = bb_lower.iloc[-1]
    curr_kc_up = kc_upper.iloc[-1]
    curr_kc_low = kc_lower.iloc[-1]
    
    # Squeeze Condition: BB inside KC
    squeeze_on = (curr_bb_up < curr_kc_up) and (curr_bb_low > curr_kc_low)
    
    # Volume Condition (Rising?)
    vol_sma = volume.rolling(window=20).mean().iloc[-1]
    high_vol = volume.iloc[-1] > vol_sma

    # Direction Prediction (Simple Trend Filter)
    # If Price > Basis (SMA20) -> Bullish, else Bearish
    direction = "🟢 BULL" if curr_close > curr_sma else "🔴 BEAR"

    return {
        "price": curr_close,
        "squeeze": squeeze_on,
        "high_vol": high_vol,
        "direction": direction,
        "bb_width": curr_bb_up - curr_bb_low
    }

# ==========================================
# 3. MAIN APP LOOP
# ==========================================

st.title("🚀 Crypto Momentum Dashboard")
st.markdown(f"**Status:** Scanning Top {TOP_N_COINS} coins (1H Timeframe). Auto-refreshing every 5 mins.")

# Placeholder for the main content to allow refreshing without duplicating
main_placeholder = st.empty()

def run_dashboard():
    with main_placeholder.container():
        # 1. Fetch
        products = get_top_liquid_pairs(limit=TOP_N_COINS)
        
        if not products:
            st.error("Failed to fetch data. Check API connection.")
            return

        results = []
        
        # Progress bar for feedback
        progress_text = st.empty()
        my_bar = st.progress(0)

        for i, p in enumerate(products):
            symbol = p['symbol']
            # progress_text.text(f"Scanning {symbol}...") # Optional: clean UI by hiding text
            
            df = get_historical_data(symbol, resolution=TIMEFRAME)
            metrics = analyze_coin(df)
            
            if metrics:
                # Construct TradingView URL (Using Binance for generic USDT chart mapping)
                # Cleaning symbol just in case
                clean_symbol = symbol.replace("-", "") 
                tv_url = f"https://www.tradingview.com/chart/?symbol=BINANCE:{clean_symbol}"

                # Status Label
                if metrics['squeeze']:
                    status = "🔥 SQUEEZE"
                elif metrics['high_vol']:
                    status = "⚠️ VOL SPIKE"
                else:
                    status = "—"

                results.append({
                    "Symbol": symbol,
                    "Chart": tv_url, # The raw URL for the link column
                    "Price": metrics['price'],
                    "Trend": metrics['direction'],
                    "Status": status,
                    "Squeeze": metrics['squeeze'], # Hidden column for sorting/filtering if needed
                })
            
            my_bar.progress((i + 1) / len(products))
            time.sleep(0.05) # Tiny delay to be nice to API

        my_bar.empty() # Clear progress bar
        
        # 2. Display Results
        if results:
            df_res = pd.DataFrame(results)
            
            # Sort: Put 'SQUEEZE' at the top
            df_res['sort_val'] = df_res['Status'].apply(lambda x: 0 if 'SQUEEZE' in x else (1 if 'SPIKE' in x else 2))
            df_res = df_res.sort_values('sort_val').drop(columns=['sort_val'])

            # Dataframe Configuration
            st.data_editor(
                df_res,
                column_config={
                    "Chart": st.column_config.LinkColumn(
                        "Chart Link",
                        help="Click to open TradingView",
                        display_text="Open Chart ↗️"
                    ),
                    "Price": st.column_config.NumberColumn(format="$%.4f"),
                },
                hide_index=True,
                use_container_width=True,
                disabled=["Symbol", "Price", "Trend", "Status"]
            )
            
            st.caption(f"Last Updated: {time.strftime('%H:%M:%S')}")
        else:
            st.warning("No data found.")

# Run the logic immediately
run_dashboard()

# Wait and Rerun
time.sleep(REFRESH_SECONDS)
st.rerun()
