import pandas as pd
import numpy as np
from datetime import datetime
from tvDatafeed import TvDatafeed, Interval
import logging
import os
import requests

# --- CONFIGURATION ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# Tambahkan daftar emiten yang ingin dipantau di sini
WATCHLIST = [
    "ASII", "BBCA", "BBRI", "TLKM", "ADRO", "ADHI", "PTPP", "AMMN", 
    "BBNI", "BMRI", "UNTR", "PTBA", "MDKA", "GOTO", "BRPT", "MEDC"
]

MIN_VALUE_PER_DAY = 2_000_000_000  # Minimal transaksi 2 Miliar/hari
MAX_STALE_DAYS = 2                 # Data maksimal basi 2 hari bursa

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("BEI_Scanner")

class BEIScanner:
    def __init__(self):
        self.tv = TvDatafeed()

    def send_telegram(self, message):
        """Fungsi pengirim pesan ke Telegram menggunakan mode HTML"""
        if not TELEGRAM_TOKEN or not CHAT_ID:
            logger.error("❌ DEBUG: TELEGRAM_TOKEN atau CHAT_ID kosong!")
            return
        
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        try:
            response = requests.post(url, json=payload, timeout=15)
            if response.status_code == 200:
                logger.info("✅ DEBUG: Pesan berhasil dikirim ke Telegram.")
            else:
                logger.error(f"❌ DEBUG: Telegram API Error {response.status_code}: {response.text}")
        except Exception as e:
            logger.error(f"❌ DEBUG: Error koneksi Telegram: {e}")

    def get_data(self, ticker):
        try:
            # Mengambil 100 bar terakhir data harian
            df = self.tv.get_hist(symbol=ticker, exchange='IDX', interval=Interval.in_daily, n_bars=100)
            return df
        except Exception as e:
            logger.warning(f"⚠️ Gagal tarik data {ticker}: {e}")
            return None

    def validate_quality(self, df):
        """Filter untuk membuang saham tersuspensi atau tidak likuid"""
        if df is None or df.empty or len(df) < 30:
            return False, "Data Kosong/Kurang"
        
        # 1. Cek Kesegaran Data (Anti-Stale)
        last_date = df.index[-1].date()
        if (datetime.now().date() - last_date).days > MAX_STALE_DAYS:
            return False, "Data Basi (Suspend)"

        # 2. Cek Likuiditas (Value = Price * Vol)
        last_bar = df.iloc[-1]
        daily_value = last_bar['close'] * last_bar['volume']
        if daily_value < MIN_VALUE_PER_DAY:
            return False, "Tidak Likuid"

        # 3. Cek Saham Tidur (Harga tidak bergerak)
        if df['close'].tail(5).std() < 0.0001:
            return False, "Saham Tidur"

        return True, "Valid"

    def calculate_logic(self, df):
        """Logika Sinyal Teknikal Sederhana tapi Akurat"""
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
        
        # RSI 14
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss + 1e-9)
        df['rsi'] = 100 - (100 / (1 + rs))

        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        score = 0
        signals = []

        # Sinyal 1: Bullish Trend (EMA 20 > EMA 50)
        if last['close'] > last['ema20'] and last['ema20'] > last['ema50']:
            score += 5
            signals.append("Bullish Trend")
        
        # Sinyal 2: RSI Breakout 50 (Momentum)
        if last['rsi'] > 50 and prev['rsi'] <= 50:
            score += 4
            signals.append("RSI Break 50")
            
        # Sinyal 3: Volume Spike (1.5x rata-rata 20 hari)
        vol_avg = df['volume'].rolling(20).mean().iloc[-1]
        if last['volume'] > vol_avg * 1.5:
            score += 5
            signals.append("Volume Spike")

        return score, signals

    def run(self):
        found = []
        logger.info(f"🚀 Memulai scan {len(WATCHLIST)} emiten...")
        
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
        
        # Mengurutkan berdasarkan skor tertinggi
        results = sorted(found, key=lambda x: x['score'], reverse=True)

        # Formatting Pesan Mode HTML
        now_str = datetime.now().strftime('%d %b %Y %H:%M')
        msg = f"<b>📊 SCAN BEI SELESAI</b>\n"
        msg += f"📅 {now_str} WIB\n"
        msg += "━━━━━━━━━━━━━━━━━━━━━━\n"

        if not results:
            msg += "Tidak ada saham memenuhi kriteria kualitas & momentum hari ini.\n"
        else:
            for s in results[:10]:
                sig_text = ", ".join(s['signals'])
                msg += f"🟢 <b>{s['ticker']}</b> | Score: {s['score']}\n"
                msg += f"💰 Price: Rp{int(s['price'])}\n"
                msg += f"📝 {sig_text}\n\n"

        msg += "━━━━━━━━━━━━━━━━━━━━━━\n"
        msg += "<i>⚠️ Filter: Value > 2M & Anti-Stale Data.</i>"
        
        # Kirim ke Telegram
        self.send_telegram(msg)
        print(msg)

if __name__ == "__main__":
    scanner = BEIScanner()
    scanner.run()
