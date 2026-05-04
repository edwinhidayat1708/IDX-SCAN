import pandas as pd
import numpy as np
from datetime import datetime
from tvDatafeed import TvDatafeed, Interval
import logging
import os

# --- CONFIGURATION ---
# Gunakan list emiten yang Anda inginkan di sini
WATCHLIST = ["ASII", "BBCA", "BBRI", "TLKM", "ADRO", "ADHI", "PTPP", "AMMN", "BBNI", "BMRI"]
MIN_VALUE_PER_DAY = 2_000_000_000  # Minimal transaksi 2 Miliar/hari
MAX_STALE_DAYS = 2                 # Maksimal data basi 2 hari

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("BEI_Scanner")

class BEIScanner:
    def __init__(self):
        # Nologin method
        self.tv = TvDatafeed()

    def get_data(self, ticker):
        try:
            # IDX: harus huruf besar
            df = self.tv.get_hist(symbol=ticker, exchange='IDX', interval=Interval.in_daily, n_bars=100)
            return df
        except:
            return None

    def validate_quality(self, df):
        if df is None or df.empty or len(df) < 50:
            return False, "Data Kosong/Kurang"
        
        # 1. Cek Kesegaran Data (Anti-Suspend/TRIO filter)
        last_date = df.index[-1].date()
        if (datetime.now().date() - last_date).days > MAX_STALE_DAYS:
            return False, "Data Basi (Suspend)"

        # 2. Cek Likuiditas (Harga x Volume)
        last_bar = df.iloc[-1]
        daily_value = last_bar['close'] * last_bar['volume']
        if daily_value < MIN_VALUE_PER_DAY:
            return False, "Tidak Likuid"

        # 3. Cek Saham Tidur (Std Deviasi 5 hari terakhir)
        if df['close'].tail(5).std() < 0.0001:
            return False, "Saham Tidur"

        return True, "Valid"

    def calculate_logic(self, df):
        # Sederhanakan indikator untuk akurasi
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
        
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))

        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        score = 0
        signals = []

        # Logic 1: Bullish Momentum (EMA Cross atau Price above EMA)
        if last['close'] > last['ema20'] and last['ema20'] > last['ema50']:
            score += 5
            signals.append("Bullish Trend")
        
        # Logic 2: RSI Recovery
        if last['rsi'] > 50 and prev['rsi'] <= 50:
            score += 3
            signals.append("RSI Break 50")
            
        # Logic 3: Volume Spike
        vol_avg = df['volume'].rolling(20).mean().iloc[-1]
        if last['volume'] > vol_avg * 1.5:
            score += 4
            signals.append("Vol Spike")

        return score, signals

    def run(self):
        found = []
        logger.info(f"Memulai scan pada {len(WATCHLIST)} emiten...")
        
        for ticker in WATCHLIST:
            df = self.get_data(ticker)
            is_valid, reason = self.validate_quality(df)
            
            if not is_valid:
                continue
                
            score, signals = self.calculate_logic(df)
            
            if score >= 5:
                found.append({
                    'ticker': ticker,
                    'score': score,
                    'price': df.iloc[-1]['close'],
                    'signals': signals
                })
        
        return found

# --- FORMATTING & EXECUTION ---
if __name__ == "__main__":
    scanner = BEIScanner()
    results = scanner.run()
    results = sorted(results, key=lambda x: x['score'], reverse=True)

    now_str = datetime.now().strftime('%d %b %Y %H:%M')
    msg = f"📊 **SCAN BEI SELESAI**\n📅 {now_str} WIB\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━\n"

    if not results:
        msg += "Tidak ada saham memenuhi kriteria kualitas & momentum hari ini.\n"
    else:
        for s in results[:10]:
            sig_text = ", ".join(s['signals'])
            msg += f"🟢 **{s['ticker']}** | Score: {s['score']}\n"
            msg += f"💰 Price: Rp{int(s['price'])}\n"
            msg += f"📝 {sig_text}\n\n"

    msg += "━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += "⚠️ *Auto-Filter: Likuiditas > 2M & Anti-Stale Data Active.*"
    
    print(msg)
