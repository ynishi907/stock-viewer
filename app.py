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
    
    # 計算用に200日前から取得 (MA75や一目均衡表を確保するため)
    fetch_start = display_start - timedelta(days=200)
    
    # データ取得
    df = yf.download(symbol, start=fetch_start, end=end_date, interval="1d", multi_level_index=False)
    
    if df.empty:
        return pd.DataFrame()

    # 移動平均線の計算
    df['MA5'] = df['Close'].rolling(window=5).mean()
    df['MA25'] = df['Close'].rolling(window=25).mean()
    df['MA75'] = df['Close'].rolling(window=75).mean()
    df['Volume_MA20'] = df['Volume'].rolling(window=20).mean()
    
    # Bollinger Bands (20, 2sigma)
    df['BB_MA20'] = df['Close'].rolling(window=20).mean()
    df['BB_Std'] = df['Close'].rolling(window=20).std()
    df['BB_Upper'] = df['BB_MA20'] + (2 * df['BB_Std'])
    df['BB_Lower'] = df['BB_MA20'] - (2 * df['BB_Std'])

    # Ichimoku Cloud
    # Tenkan-sen (Conversion Line): (9-period high + 9-period low) / 2
    high9 = df['High'].rolling(window=9).max()
    low9 = df['Low'].rolling(window=9).min()
    tenkan = (high9 + low9) / 2
    # Kijun-sen (Base Line): (26-period high + 26-period low) / 2
    high26 = df['High'].rolling(window=26).max()
    low26 = df['Low'].rolling(window=26).min()
    kijun = (high26 + low26) / 2
    # Senkou Span A (Leading Span A): (Conversion Line + Base Line) / 2, shifted 26
    df['SpanA'] = ((tenkan + kijun) / 2).shift(26)
    # Senkou Span B (Leading Span B): (52-period high + 52-period low) / 2, shifted 26
    high52 = df['High'].rolling(window=52).max()
    low52 = df['Low'].rolling(window=52).min()
    df['SpanB'] = ((high52 + low52) / 2).shift(26)

    # RSI (14) calculation
    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
    rs = avg_gain / avg_loss
    df['RSI'] = 100 - (100 / (1 + rs))

    # MACD (12, 26, 9) calculation
    exp12 = df['Close'].ewm(span=12, adjust=False).mean()
    exp26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp12 - exp26
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['MACD'] - df['Signal']

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
show_bb = st.sidebar.checkbox("Bollinger Bands", value=False)
show_ichimoku = st.sidebar.checkbox("Ichimoku Cloud", value=False)

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
    
    # 4段構成のグラフを作成
    fig = make_subplots(
        rows=4, cols=1, 
        shared_xaxes=True, 
        vertical_spacing=0.04,
        row_heights=[0.5, 0.15, 0.15, 0.2]
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

    # ボリンジャーバンド
    if show_bb:
        fig.add_trace(go.Scatter(
            x=df.index, y=df['BB_Upper'], name='BB Upper',
            line=dict(color='rgba(190, 160, 255, 0.5)', width=1),
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=df.index, y=df['BB_Lower'], name='BB Lower',
            line=dict(color='rgba(190, 160, 255, 0.5)', width=1),
            fill='tonexty', fillcolor='rgba(190, 160, 255, 0.1)',
        ), row=1, col=1)

    # 一目均衡表 (雲)
    if show_ichimoku:
        fig.add_trace(go.Scatter(
            x=df.index, y=df['SpanA'], name='Span A',
            line=dict(color='rgba(46, 204, 113, 0.5)', width=1, dash='dot'),
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=df.index, y=df['SpanB'], name='Span B',
            line=dict(color='rgba(231, 76, 60, 0.5)', width=1, dash='dot'),
            fill='tonexty', fillcolor='rgba(128, 128, 128, 0.2)',
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

    # --- 最下段: RSI ---
    fig.add_trace(go.Scatter(
        x=df.index, y=df['RSI'], name='RSI (14)',
        line=dict(color='#d62728', width=1.5),
        legend="legend3"
    ), row=3, col=1)

    # RSI 70/30 lines
    fig.add_hline(y=70, line_dash="dash", line_color="orange", line_width=1.0, row=3, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="cornflowerblue", line_width=1.0, row=3, col=1)

    # --- 最下段: MACD ---
    # Histogram
    colors = ['#2ca02c' if v >= 0 else '#d62728' for v in df['MACD_Hist']]
    fig.add_trace(go.Bar(
        x=df.index, y=df['MACD_Hist'], name='MACD Hist',
        marker_color=colors,
        marker_line_width=0,
        legend="legend4"
    ), row=4, col=1)
    
    # MACD Line
    fig.add_trace(go.Scatter(
        x=df.index, y=df['MACD'], name='MACD',
        line=dict(color='#1f77b4', width=1.5),
        legend="legend4"
    ), row=4, col=1)
    
    # Signal Line
    fig.add_trace(go.Scatter(
        x=df.index, y=df['Signal'], name='Signal',
        line=dict(color='#ff7f0e', width=1.5),
        legend="legend4"
    ), row=4, col=1)

    # --- レイアウト調整 ---
    fig.update_layout(
        xaxis_rangeslider_visible=False,
        template="plotly_dark",
        height=1000,
        margin=dict(l=50, r=50, b=50, t=50),
        hovermode="x unified",
        legend=dict(orientation="h", x=1, y=1.01, xanchor='right', yanchor='bottom'),
        legend2=dict(orientation="h", x=1, y=0.52, xanchor='right', yanchor='bottom'),
        legend3=dict(orientation="h", x=1, y=0.35, xanchor='right', yanchor='bottom'),
        legend4=dict(orientation="h", x=1, y=0.18, xanchor='right', yanchor='bottom'),
        font=dict(family="Arial, sans-serif", size=10)
    )
    
    fig.update_yaxes(title_text=f"Price ({info['currency']})", row=1, col=1)
    fig.update_yaxes(title_text="Volume", row=2, col=1)
    fig.update_yaxes(title_text="RSI", range=[0, 100], row=3, col=1)
    fig.update_yaxes(title_text="MACD", row=4, col=1)

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