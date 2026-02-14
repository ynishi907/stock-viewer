import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
from datetime import datetime, timedelta
import json
import os

# ==========================================
# 1. ページ基本設定
# ==========================================
st.set_page_config(
    page_title="Stock View Pro",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==========================================
# 2. データ取得・加工ロジック (関数群)
# ==========================================

@st.cache_data(ttl=3600)  # 1時間キャッシュを保持
def get_stock_info(symbol):
    """銘柄の基本情報を取得"""
    try:
        ticker_obj = yf.Ticker(symbol)
        info = ticker_obj.info
        return {
            "name": info.get('shortName', symbol),
            "currency": info.get('currency', 'JPY'),
        }
    except:
        return {"name": symbol, "currency": "???"}

@st.cache_data
def load_and_process_data(symbol, period_str):
    """
    指定期間より多めにデータを取得して移動平均を計算し、
    表示期間分だけを切り出す
    """
    # 期間計算
    end_date = datetime.today()
    period_map = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730, "5y": 1825}
    days = period_map.get(period_str, 365)
    display_start = end_date - timedelta(days=days)
    
    # 計算用に120日前から取得 (MA75を確保するため)
    fetch_start = display_start - timedelta(days=120)
    
    # データ取得
    df = yf.download(symbol, start=fetch_start, end=end_date, interval="1d", multi_level_index=False)
    
    if df.empty:
        return pd.DataFrame()

    # 移動平均線の計算
    df['MA5'] = df['Close'].rolling(window=5).mean()
    df['MA25'] = df['Close'].rolling(window=25).mean()
    df['MA75'] = df['Close'].rolling(window=75).mean()
    df['Volume_MA20'] = df['Volume'].rolling(window=20).mean()
    
    # 表示期間に絞り込み
    df_display = df[df.index >= pd.to_datetime(display_start)].copy()
    return df_display

# ==========================================
# 3. サイドバー (UI設定)
# ==========================================
st.sidebar.header("📈 Chart Settings")

# お気に入りファイル設定
FAVORITES_FILE = "favorites.json"

def load_favorites():
    if os.path.exists(FAVORITES_FILE):
        with open(FAVORITES_FILE, "r") as f:
            return json.load(f)
    return []

def save_favorites(favorites):
    with open(FAVORITES_FILE, "w") as f:
        json.dump(favorites, f)

# お気に入り機能の初期化
if 'favorites' not in st.session_state:
    st.session_state['favorites'] = load_favorites()

# 証券コード入力
if 'ticker_input' not in st.session_state:
    st.session_state.ticker_input = '7203'

# タブ切り替え
tab1, tab2 = st.sidebar.tabs(["🔍 Search", "⭐ Favorites"])

with tab1:
    ticker_input = st.text_input('Stock Code', key='ticker_input')
    if st.button("Add to Favorites"):
        if ticker_input and ticker_input not in st.session_state['favorites']:
            st.session_state['favorites'].append(ticker_input)
            save_favorites(st.session_state['favorites'])
            st.success(f"Added {ticker_input}!")

with tab2:
    def apply_favorite():
        if st.session_state.favorite_selector:
            st.session_state.ticker_input = st.session_state.favorite_selector

    if st.session_state['favorites']:
        st.selectbox("Select from Favorites", options=st.session_state['favorites'], index=None, placeholder="Choose a stock...", key="favorite_selector", on_change=apply_favorite)
    else:
        st.info("No favorites saved.")

# 日本株（数字4桁）なら自動で .T を付与
if ticker_input.isdigit() and len(ticker_input) == 4:
    ticker = f"{ticker_input}.T"
else:
    ticker = ticker_input

# 表示期間の選択
period_choice = st.sidebar.selectbox(
    "Display Period",
    options=["1mo", "3mo", "6mo", "1y", "2y", "5y"],
    index=3 # デフォルト1年
)

# 線の太さ設定
line_width = 1.0

# 移動平均線の表示切り替え
show_ma5 = st.sidebar.checkbox("MA5", value=True)
show_ma25 = st.sidebar.checkbox("MA25", value=True)
show_ma75 = st.sidebar.checkbox("MA75", value=True)

# ==========================================
# 4. メインコンテンツ
# ==========================================

# データと情報の取得
with st.spinner('Fetching data...'):
    info = get_stock_info(ticker)
    df = load_and_process_data(ticker, period_choice)

if df.empty:
    st.error(f"Error: Could not retrieve data for '{ticker}'. Please check the code.")
else:
    # タイトル表示
    st.title(f"{info['name']} ({ticker})")
    
    # 2段構成のグラフを作成
    fig = make_subplots(
        rows=2, cols=1, 
        shared_xaxes=True, 
        vertical_spacing=0.08,
        row_heights=[0.7, 0.3]
    )

    # --- 上段: ローソク足 & 移動平均線 ---
    # ローソク足
    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
        name='Price'
    ), row=1, col=1)

    # 移動平均線
    ma_specs = [('MA5', show_ma5, '#00ff00'), ('MA25', show_ma25, '#ff9900'), ('MA75', show_ma75, '#00bfff')]
    for ma_name, show_flag, color in ma_specs:
        if show_flag:
            fig.add_trace(go.Scatter(
                x=df.index, y=df[ma_name], name=ma_name,
                line=dict(color=color, width=line_width)
            ), row=1, col=1)

    # --- 下段: 出来高 (棒グラフ) ---
    fig.add_trace(go.Bar(
        x=df.index, y=df['Volume'], name='Volume',
        marker_color='#1f77b4', opacity=0.8, marker_line_width=0,
        legend="legend2"
    ), row=2, col=1)

    # 出来高移動平均線 (20日)
    fig.add_trace(go.Scatter(
        x=df.index, y=df['Volume_MA20'], name='Volume MA20',
        line=dict(color='#ff9900', width=1.5),
        legend="legend2"
    ), row=2, col=1)

    # --- レイアウト調整 ---
    fig.update_layout(
        xaxis_rangeslider_visible=False,
        template="plotly_dark",
        height=700,
        margin=dict(l=50, r=50, b=50, t=50),
        hovermode="x unified",
        legend=dict(orientation="h", x=1, y=1.01, xanchor='right', yanchor='bottom'),
        legend2=dict(orientation="h", x=1, y=0.31, xanchor='right', yanchor='bottom')
    )
    
    fig.update_yaxes(title_text=f"Price ({info['currency']})", row=1, col=1)
    fig.update_yaxes(title_text="Volume", row=2, col=1)

    # グラフ表示
    st.plotly_chart(fig, use_container_width=True)

    # --- 下部情報表示 ---
    st.subheader("Latest Prices")
    st.write(df[['Open', 'High', 'Low', 'Close', 'Volume']].tail())

# ==========================================
# 5. フッター
# ==========================================
st.markdown("---")
st.caption(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")