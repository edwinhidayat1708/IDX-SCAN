import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from tvDatafeed import TvDatafeed, Interval
import logging

# --- CONFIGURATION ---
SCRAPER_CREDENTIALS = {'username': '', 'password': ''} # Isi jika punya akun pro
MIN_VALUE_PER_DAY = 2_000_000_000  # Minimal transaksi 2 Miliar/hari
MIN_FREQ = 500                    # Minimal 500 kali transaksi (opsional jika data tersedia)
EXCLUDE_PRICE_BELOW = 60           # Hindari saham gocap/hampir gocap
MAX_STALE_DAYS = 2                 # Data maksimal basi 2 hari bursa

# --- LOGGING SETUP ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("BEI_Scanner")

class BEIScanner:
    def __init__(self):
        self.tv = TvDatafeed()
        # Anda bisa mengganti list ini dengan hasil scraping LQ45/Kompas100
        # Untuk demo, kita asumsikan list emiten yang Anda miliki
        self.raw_tickers = ["ASII", "BBCA", "BBRI", "TLKM", "ADRO", "TRIO", "ADHI", "PTPP"] 

    def get_data(self, ticker):
        try:
            # Tarik data 100 bar terakhir (Daily)
            df = self.tv.get_hist(symbol=ticker, exchange='IDX', interval=Interval.in_daily, n_bars=100)
            if df is None or df.empty:
                return None
            return df
        except Exception as e:
            logger.error(f"Error fetching {ticker}: {e}")
            return None

    def validate_quality(self, df):
        """Fungsi utama untuk membuang saham seperti TRIO atau saham tidur"""
        last_bar = df.iloc[-1]
        
        # 1. Cek Kesegaran Data (Anti-Suspend)
        # Jika hari ini Senin, data terakhir harus Jumat/Senin.
        last_date = df.index[-1].date()
        if (datetime.now().date() - last_date).days > MAX_STALE_DAYS:
            return False, "Data Basi (Suspend)"

        # 2. Cek Likuiditas Real-Time
        # Volume * Close harus di atas ambang batas (contoh 2 Miliar)
        daily_value = last_bar['close'] * last_bar['volume']
        if daily_value < MIN_VALUE_PER_DAY:
            return False, "Tidak Likuid"

        # 3. Cek Harga Nominal
        if last_bar['close'] < EXCLUDE_PRICE_BELOW:
            return False, "Saham Gocap"

        # 4. Cek Pergerakan (Anti-Saham Tidur)
        # Jika dalam 5 hari harga tidak bergerak sama sekali
        if df['close'].tail(5).std() < 0.01:
            return False, "Saham Tidur"

        return True, "Valid"

    def calculate_indicators(self, df):
        """Technical Analysis Engine"""
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))

        # EMA
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()

        # Volume MA
        df['vol_ma20'] = df['volume'].rolling(window=20).mean()
        
        return df

    def scan(self):
        results = []
        logger.info(f"Memulai scan pada {len(self.raw_tickers)} emiten...")

        for ticker in self.raw_tickers:
            df = self.get_data(ticker)
            if df is None: continue

            # STEP 1: VALIDASI KUALITAS (The Firewall)
            is_valid, reason = self.validate_quality(df)
            if not is_valid:
                # logger.info(f"Skipping {ticker}: {reason}")
                continue

            # STEP 2: CALCULATE
            df = self.calculate_indicators(df)
            last = df.iloc[-1]
            prev = df.iloc[-2]

            # STEP 3: LOGIC SCORE (Contoh Sederhana)
            score = 0
            signals = []

            # Pola 1: Golden Cross EMA
            if prev['ema20'] < prev['ema50'] and last['ema20'] > last['ema50']:
                score += 5
                signals.append("GoldenCross")

            # Pola 2: Volume Spike
            if last['volume'] > (last['vol_ma20'] * 2):
                score += 4
                signals.append("VolSpike")

            # Pola 3: RSI Reversal
            if prev['rsi'] < 30 and last['rsi'] > 30:
                score += 5
                signals.append("RSI_Oversold_Rev")

            if score >= 5:
                results.append({
                    'ticker': ticker,
                    'score': score,
                    'price': last['close'],
                    'signals': ", ".join(signals)
                })

        return results

# --- EXECUTION & TELEGRAM FORMATTING ---
scanner = BEIScanner()
found_stocks = scanner.scan()

# Urutkan berdasarkan skor tertinggi
found_stocks = sorted(found_stocks, key=lambda x: x['score'], reverse=True)

msg = f"📊 **SCAN BEI SELESAI**\n"
msg += f"📅 {datetime.now().strftime('%d %b %Y %H:%M')}\n"
msg += "━━━━━━━━━━━━━━━━━━━━━━\n"
if not found_stocks:
    msg += "Tidak ada saham memenuhi kriteria hari ini."
else:
    for s in found_stocks[:10]: # Ambil Top 10
        emoji = "🟢" if s['score'] >= 10 else "🟡"
        msg += f"{emoji} **{s['ticker']}** | Score: {s['score']} | Rp{int(s['price'])}\n"
        msg += f"└ Signals: {s['signals']}\n\n"

msg += "⚠️ *Filter Likuiditas > 2M/hari diterapkan.*"
print(msg)
# Di sini Anda panggil fungsi bot.send_message(chat_id, msg) Anda
