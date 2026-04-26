"""
╔══════════════════════════════════════════════════════════════════════════════╗
║          BEI CONFLUENCE PATTERN SCANNER — Daily Candle Edition v3.0        ║
║                                                                              ║
║  Data source : AGNOSTIK — CSV, DataFrame, tvdatafeed, bei_scanner.py       ║
║  10 Pola + Combo A-E + ADX Regime + Pre-Filter + Universe Builder          ║
╚══════════════════════════════════════════════════════════════════════════════╝

CARA PAKAI:
-----------
1. Demo (data sintetis):
   python bei_pattern_scanner.py --demo

2. Scan satu CSV:
   python bei_pattern_scanner.py --csv ./data/BBCA.csv --ticker BBCA

3. Scan folder CSV (dengan pre-filter otomatis):
   python bei_pattern_scanner.py --csv-dir ./data/ --out hasil.csv

4. Integrasi tvdatafeed + universe builder otomatis:
   python bei_pattern_scanner.py --auto --delay 1.5

5. Hanya build & tampilkan universe (tanpa scan pola):
   python bei_pattern_scanner.py --build-universe

6. Import sebagai modul:
   from bei_pattern_scanner import scan_dataframe, pre_filter, UniverseBuilder

FORMAT CSV: kolom Open,High,Low,Close,Volume; index Date

UNIVERSE SELECTION (Corong 3 Lapis):
   Lapis 1 — Papan     : Papan Utama + Pengembangan (bukan Akselerasi)
   Lapis 2 — Likuiditas: Volume IDR avg > threshold, Harga > Rp100, Frek > min
   Lapis 3 — Regime    : Universe A (Trending) vs Universe B (Oversold/Reversal)

   Universe A → Pola #1,2,3,5,6,7,8,10 & Combo A,B,D,E (TRENDING)
   Universe B → Pola #4, #9 & Combo C                   (OVERSOLD/REVERSAL)

POLA vs KONDISI EMITEN:
   Pola #1,#3,#6,#7,#8 → TRENDING BULLISH  (ADX>25, harga>EMA50, vol naik)
   Pola #4, #9          → OVERSOLD/SELLOFF  (RSI<35, turun>15% dari puncak)
   Pola #2, #5, #10     → SEMUA KONDISI     (asal momentum + volume konfirmasi)
   Combo A/B/E          → Paling powerful di TRENDING regime
   Combo C              → Paling powerful di OVERSOLD / post-selloff
"""

import warnings, os, sys, argparse
warnings.filterwarnings('ignore')

import pandas as pd
import numpy as np
import ta
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, Dict, List


# ═══════════════════════════════════════════════════════════════════
#  KONFIGURASI
# ═══════════════════════════════════════════════════════════════════
CONFIG = {
    "vol_ma_period":       20,
    "vol_spike_mult":      1.5,
    "vol_strong_mult":     2.5,
    "atr_period":          14,
    "atr_expansion_mult":  1.5,
    "consolidation_days":  10,
    "consolidation_range": 0.08,
    "triangle_lookback":   20,
    "higher_lows_min":     2,
    "flag_pole_min_pct":   0.05,
    "flag_days":           7,
    "cup_lookback":        60,
    "cup_min_days":        10,
    "cup_max_depth":       0.35,
    "handle_max_retrace":  0.40,
    "marubozu_body_ratio": 0.80,
    "marubozu_shadow_max": 0.10,
    "hammer_lower_shadow": 2.0,
    "hammer_upper_shadow": 0.30,
    "gap_min_pct":         0.015,
    "gap_strong_pct":      0.04,
    "rsi_period":          14,
    "rsi_oversold":        35,
    "rsi_overbought":      72,
    "rsi_momentum_lo":     45,
    "rsi_momentum_hi":     70,
    "macd_fast":           12,
    "macd_slow":           26,
    "macd_signal":         9,
    "supertrend_period":   10,
    "supertrend_mult":     3.0,
    "adx_period":          14,
    "adx_trending":        25,
    "adx_sideways":        15,
    "vwap_period":         20,
    "score_strong":        8,
    "score_entry":         5,
    "score_watch":         3,

    # ── Universe Builder & Pre-Filter ─────────────────────
    "min_price":           100,           # harga min Rp100 (bukan gocap)
    "min_vol_idr":         500_000_000,   # likuiditas min 500 juta IDR/hari
    "min_vol_idr_t1":    5_000_000_000,   # Tier1 blue chip  > 5 miliar/hari
    "min_vol_idr_t2":    1_000_000_000,   # Tier2 mid-cap    > 1 miliar/hari
    "min_vol_idr_t3":      500_000_000,   # Tier3 small-cap  > 500 juta/hari
    "vol_lookback":        20,            # periode rata-rata volume
    "max_zero_vol_days":   4,             # max hari tanpa transaksi (dari 20 hari)
    "universe_a_adx":      20,            # Universe A: min ADX trending
    "universe_a_ema":      50,            # Universe A: harga > EMA-N ini
    "universe_b_rsi":      42,            # Universe B: RSI max oversold
    "universe_b_drop":     0.12,          # Universe B: turun min 12% dari high 20hr
    "tv_n_bars":           200,           # bar historis per saham
    "tv_delay_sec":        1.2,           # jeda antar request (hindari rate limit)
    "tv_exchange":         "IDX",         # exchange BEI
}


# ═══════════════════════════════════════════════════════════════════
#  WATCHLIST BEI — 3 TIER
#  Tier 1 : Blue chip & LQ45          (~45 saham)  — selalu di-scan
#  Tier 2 : Mid-cap likuid            (~180 saham) — di-scan dengan filter IDR
#  Tier 3 : Small-cap aktif           (~120 saham) — di-scan hanya jika vol spike
# ═══════════════════════════════════════════════════════════════════

WATCHLIST_T1 = [
    # ── Perbankan ──────────────────────────────────────
    "BBCA","BBRI","BMRI","BBNI","BRIS","BTPS","BJBR","BJTM","NISP","PNBN",
    # ── Telekomunikasi ─────────────────────────────────
    "TLKM","EXCL","ISAT","FREN",
    # ── Energi & Tambang ───────────────────────────────
    "ADRO","PTBA","INCO","ANTM","MDKA","ITMG","BUMI","HRUM","MBAP","ELSA",
    # ── Consumer ───────────────────────────────────────
    "ICBP","INDF","UNVR","MYOR","SIDO","CLEO","ULTJ","TSPC","KLBF","MIKA",
    # ── Properti & Infrastruktur ───────────────────────
    "BSDE","CTRA","SMRA","PWON","JSMR","WIKA","WSKT","ADHI","PTPP",
    # ── Industri & Lain ────────────────────────────────
    "ASII","AALI","LSIP","SMAR","GGRM","HMSP","SMGR","INTP","WTON","JPFA",
]

WATCHLIST_T2 = [
    # ── Perbankan menengah ─────────────────────────────
    "BNGA","BBKP","MAYA","BMAS","BCIC","AGRO","DNAR","NOBU","ARTO","BANK",
    # ── Multifinance & Asuransi ────────────────────────
    "BFIN","ADMF","MFIN","VRNA","LPGI","MREI","LIFE","PANS",
    # ── Consumer & Retail ──────────────────────────────
    "ACES","MAPI","ERAA","RALS","MIDI","AMRT","HERO","CSAP","LPPF","KINO",
    "UNVR","CPIN","MAIN","SIPD","PJAA","SRTG","SCMA","MNCN","EMTK","KPIG",
    # ── Teknologi & Digital ────────────────────────────
    "GOTO","BUKA","FILM","WIFI","MORA","EDGE","MTDL","DMMX","MLPT","INPC",
    # ── Kesehatan & Farmasi ────────────────────────────
    "KAEF","DVLA","PYFA","SCPI","HEAL","PRDA","MIKA","SILO","BMHS","RSGK",
    # ── Properti mid-cap ──────────────────────────────
    "DILD","PPRO","APLN","KIJA","MDLN","LPKR","MKPI","NIRO","GPRA","TARA",
    # ── Logistik & Transportasi ────────────────────────
    "BIRD","BLTA","SAFE","ASSA","TAXI","MIRA","IPCM","NELY","TMAS","GIAA",
    # ── Agrikultur ─────────────────────────────────────
    "SGRO","TBLA","SSMS","DSFI","CPRO","IIKP","BWPT","GZCO","JAWA","ANJT",
    # ── Kimia & Material ───────────────────────────────
    "TPIA","BRPT","SRSN","INCI","DPNS","EKAD","UNIC","BUDI","SOBI","ETWA",
    # ── Industri Dasar ────────────────────────────────
    "SMCB","ARNA","TOTO","KRAS","ALMI","BTON","LION","LMSH","PICO","GDST",
    # ── Media & Hiburan ───────────────────────────────
    "VIVA","MTMH","ABBA","BMTR","KBLV","FORU","LPLI","SKYB","MARI","GEMA",
    # ── Energi terbarukan & Utilitas ──────────────────
    "POWR","PGAS","MEDC","RUIS","SOCI","AKRA","TOWR","TBIG","MTEL","CENT",
]

WATCHLIST_T3 = [
    # Small-cap yang sering muncul di radar momentum BEI
    "NICL","NCKL","CUAN","MAPA","SONA","BOGA","BAUT","GULA","KEJU","WMUU",
    "BHAT","MEJA","HALO","BOSS","ZONE","RUNS","NAYZ","FUJI","ATLA","CBUT",
    "SMKL","BSML","TEBE","KPAL","LABA","BPTR","PURE","EAST","LABA","MOLI",
    "ISAP","TGRA","KEEN","BTEK","MAPI","GTSI","TRIO","AMOR","MABA","PLIN",
    "CMPP","OMED","BINO","SAGE","BOBA","NINE","BREN","CGAS","RAFI","GTBO",
    "NUSA","JGLE","KBAG","BRIS","YULE","DWGL","KOCI","BHAT","GTRA","BPTR",
    "TRON","DIVA","POLU","HILL","ALTO","MTSM","BPII","IPPE","AMAN","KOIN",
    "SHIP","NUSA","DEAL","MGLV","PPGL","BGTG","PTIS","ATPK","WIFI","DYAN",
    "MKTR","AMAN","CLEO","STAA","LAJU","PTMP","MSIE","BMHS","HEAL","PCAR",
    "SMDR","HITS","TRIL","RGAS","JSKY","GRIA","NAIK","MSJA","INDX","COAL",
    "PTBA","AISA","BWON","BKSL","DAJK","GTBO","BMSR","PSAB","BELI","TOSK",
    "ASRI","BIPP","FMII","DART","BKDP","PURI","LCGP","EMDE","MABA","RBMS",
]

# Gabungan semua tier
WATCHLIST_ALL = list(dict.fromkeys(WATCHLIST_T1 + WATCHLIST_T2 + WATCHLIST_T3))


# ═══════════════════════════════════════════════════════════════════
#  PRE-FILTER — Corong Lapis 2 (Likuiditas)
# ═══════════════════════════════════════════════════════════════════

@dataclass
class FilterResult:
    passed:    bool
    reason:    str          = ""
    tier:      int          = 0   # 1/2/3
    vol_idr:   float        = 0.0
    universe:  str          = ""  # "A_TRENDING" / "B_OVERSOLD" / "BOTH"


def pre_filter(df: pd.DataFrame, ticker: str = "") -> FilterResult:
    """
    Lapis 2 — Filter likuiditas sebelum scan 10 pola.

    Mengembalikan FilterResult:
      passed=True  → lanjut ke scan pola
      passed=False → skip, hemat waktu & resource

    Juga menentukan universe:
      universe="A_TRENDING" → emiten sedang trending, cocok Pola #1,3,6,7,8
      universe="B_OVERSOLD" → emiten oversold, cocok Pola #4,9 (Combo C)
      universe="BOTH"       → cocok semua pola

    Contoh:
        ok = pre_filter(df, "BBCA")
        if ok.passed:
            result = scan_dataframe("BBCA", df)
    """
    try:
        if df is None or len(df) < 30:
            return FilterResult(False, "data < 30 bar")

        df.columns = [c.capitalize() for c in df.columns]
        n   = min(CONFIG['vol_lookback'], len(df))
        i   = len(df) - 1

        close   = float(df['Close'].iloc[i])
        vol_avg = float(df['Volume'].iloc[-n:].mean())
        vol_idr = vol_avg * close   # konversi ke IDR

        # ── Lapis 2a: Harga minimum ────────────────────
        if close < CONFIG['min_price']:
            return FilterResult(False, f"harga Rp{close:.0f} < min Rp{CONFIG['min_price']}", vol_idr=vol_idr)

        # ── Lapis 2b: Likuiditas minimum ───────────────
        if vol_idr < CONFIG['min_vol_idr']:
            return FilterResult(False,
                f"likuiditas Rp{vol_idr/1e9:.2f}B < min Rp{CONFIG['min_vol_idr']/1e9:.1f}B",
                vol_idr=vol_idr)

        # ── Lapis 2c: Hari tanpa transaksi ─────────────
        zero_days = int((df['Volume'].iloc[-n:] == 0).sum())
        if zero_days > CONFIG['max_zero_vol_days']:
            return FilterResult(False, f"terlalu banyak hari no-volume ({zero_days} hari)", vol_idr=vol_idr)

        # ── Tentukan Tier ──────────────────────────────
        if   vol_idr >= CONFIG['min_vol_idr_t1']: tier = 1
        elif vol_idr >= CONFIG['min_vol_idr_t2']: tier = 2
        else:                                      tier = 3

        # ── Lapis 3: Universe A vs B ───────────────────
        # Cek Universe A (Trending)
        ema_n    = CONFIG['universe_a_ema']
        ema_val  = df['Close'].ewm(span=ema_n, adjust=False).mean().iloc[i]
        above_ema = close > ema_val

        # ADX sederhana — cukup untuk filter kasar
        adx_ok   = False
        if len(df) >= 28:
            try:
                adx_s = ta.trend.ADXIndicator(
                    df['High'], df['Low'], df['Close'],
                    window=CONFIG['adx_period'])
                adx_v = float(adx_s.adx().iloc[i] or 0)
                adx_ok = adx_v >= CONFIG['universe_a_adx']
            except Exception:
                adx_ok = above_ema  # fallback ke EMA saja

        is_trending = above_ema and adx_ok

        # Cek Universe B (Oversold)
        rsi_ok   = False
        drop_ok  = False
        if len(df) >= 20:
            try:
                rsi_v = float(ta.momentum.rsi(df['Close'], window=14).iloc[i] or 50)
                rsi_ok = rsi_v <= CONFIG['universe_b_rsi']
            except Exception:
                rsi_ok = False

            high20   = float(df['High'].iloc[-20:].max())
            drop_pct = (high20 - close) / high20 if high20 > 0 else 0
            drop_ok  = drop_pct >= CONFIG['universe_b_drop']

        is_oversold = rsi_ok and drop_ok

        # Tentukan universe label
        if   is_trending and is_oversold: universe = "BOTH"
        elif is_trending:                 universe = "A_TRENDING"
        elif is_oversold:                 universe = "B_OVERSOLD"
        else:                             universe = "NEUTRAL"   # bisa scan tapi dengan ekspektasi lebih rendah

        return FilterResult(
            passed   = True,
            reason   = "OK",
            tier     = tier,
            vol_idr  = vol_idr,
            universe = universe,
        )

    except Exception as e:
        return FilterResult(False, f"error: {e}")


# ═══════════════════════════════════════════════════════════════════
#  UNIVERSE BUILDER — Corong Lengkap 3 Lapis
# ═══════════════════════════════════════════════════════════════════

class UniverseBuilder:
    """
    Membangun universe saham BEI yang layak di-scan.

    Alur kerja:
    1. Mulai dari WATCHLIST_ALL (~345 saham di 3 tier)
    2. Pre-filter likuiditas per saham (perlu data OHLCV)
    3. Kelompokkan ke Universe A (Trending) dan B (Oversold)
    4. Return daftar ticker yang siap di-scan 10 pola

    Tanpa tvdatafeed (pakai CSV):
        ub = UniverseBuilder()
        ub.load_from_csv_dir("./data/")
        universe = ub.build()

    Dengan tvdatafeed:
        ub = UniverseBuilder(tv=tv_instance)
        universe = ub.build(tickers=WATCHLIST_ALL)

    Output universe adalah dict:
        {
          "A_TRENDING": ["BBCA", "BMRI", ...],
          "B_OVERSOLD": ["TLKM", "ADRO", ...],
          "BOTH":       ["EXCL", ...],
          "NEUTRAL":    ["BSDE", ...],
          "SKIPPED":    {"GOCAP": "harga < 100", ...}
        }
    """

    def __init__(self, tv=None, verbose: bool = True):
        self.tv      = tv       # tvdatafeed instance (opsional)
        self.verbose = verbose
        self._cache: Dict[str, pd.DataFrame] = {}

    # ── Load dari CSV folder ─────────────────────────────
    def load_from_csv_dir(self, dirpath: str):
        import os
        files = [f for f in os.listdir(dirpath) if f.endswith('.csv')]
        for f in files:
            ticker = os.path.splitext(f)[0].upper()
            try:
                df = pd.read_csv(os.path.join(dirpath, f),
                                 index_col=0, parse_dates=True)
                self._cache[ticker] = df
            except Exception:
                pass
        if self.verbose:
            print(f"  [UniverseBuilder] Loaded {len(self._cache)} CSV files")

    # ── Fetch satu ticker via tvdatafeed ─────────────────
    def _fetch_tv(self, ticker: str) -> Optional[pd.DataFrame]:
        if self.tv is None:
            return None
        try:
            import time
            from tvDatafeed import Interval
            df = self.tv.get_hist(
                symbol   = ticker,
                exchange = CONFIG['tv_exchange'],
                interval = Interval.in_daily,
                n_bars   = CONFIG['tv_n_bars'],
            )
            time.sleep(CONFIG['tv_delay_sec'])
            return df
        except Exception as e:
            if self.verbose:
                print(f"  ⚠  {ticker}: fetch error — {e}")
            return None

    # ── Build universe ────────────────────────────────────
    def build(self, tickers: Optional[List[str]] = None) -> dict:
        """
        Build universe. Return dict per kategori.
        Jika tickers=None, pakai WATCHLIST_ALL.
        """
        if tickers is None:
            tickers = WATCHLIST_ALL

        universe = {
            "A_TRENDING": [],
            "B_OVERSOLD": [],
            "BOTH":       [],
            "NEUTRAL":    [],
            "SKIPPED":    {},
        }

        total = len(tickers)
        passed = 0

        for idx, ticker in enumerate(tickers, 1):
            if self.verbose:
                print(f"  [{idx:3d}/{total}] Pre-filtering {ticker:<12}", end="\r")

            # Ambil DataFrame — dari cache atau tvdatafeed
            df = self._cache.get(ticker)
            if df is None and self.tv is not None:
                df = self._fetch_tv(ticker)

            if df is None:
                universe["SKIPPED"][ticker] = "no data"
                continue

            # Jalankan pre-filter
            fr = pre_filter(df, ticker)

            if not fr.passed:
                universe["SKIPPED"][ticker] = fr.reason
                continue

            passed += 1
            universe[fr.universe].append({
                "ticker":    ticker,
                "tier":      fr.tier,
                "vol_idr_b": round(fr.vol_idr / 1e9, 2),  # dalam miliar IDR
                "universe":  fr.universe,
                "df":        df,   # simpan df agar tidak perlu fetch ulang saat scan
            })

        if self.verbose:
            print(" " * 60, end="\r")
            self._print_universe_summary(universe, total, passed)

        return universe

    # ── Summary ──────────────────────────────────────────
    def _print_universe_summary(self, u: dict, total: int, passed: int):
        sep = "─" * 58
        print(f"\n  {sep}")
        print(f"  UNIVERSE BUILDER RESULT")
        print(f"  {sep}")
        print(f"  Total watchlist        : {total:>4} saham")
        print(f"  Lolos pre-filter       : {passed:>4} saham")
        print(f"  Dilewati (iliquid/err) : {total-passed:>4} saham")
        print(f"  {sep}")
        print(f"  🟢 Universe A (Trending)  : {len(u['A_TRENDING']):>4} saham")
        print(f"     → Pola #1,3,6,7,8 & Combo A,B,D,E paling efektif")
        print(f"  🔴 Universe B (Oversold)  : {len(u['B_OVERSOLD']):>4} saham")
        print(f"     → Pola #4,9 & Combo C paling efektif")
        print(f"  🟡 Universe BOTH          : {len(u['BOTH']):>4} saham")
        print(f"     → Transisi — semua pola relevan")
        print(f"  ⚪ Universe NEUTRAL       : {len(u['NEUTRAL']):>4} saham")
        print(f"     → Scan tetap jalan, ekspektasi lebih rendah")
        print(f"  {sep}\n")

    # ── Flatten ke list ticker saja ───────────────────────
    def flat_list(self, universe: dict,
                  include: List[str] = None) -> List[dict]:
        """
        Flatten universe ke list dikt untuk iterasi scan.
        include: subset universe yang ingin di-scan,
                 default semua kecuali SKIPPED.
        Contoh: flat_list(u, include=["A_TRENDING","BOTH"])
        """
        if include is None:
            include = ["A_TRENDING","B_OVERSOLD","BOTH","NEUTRAL"]
        result = []
        for key in include:
            result.extend(universe.get(key, []))
        # Sort: Tier 1 dulu, lalu volume IDR terbesar
        result.sort(key=lambda x: (x['tier'], -x['vol_idr_b']))
        return result


# ═══════════════════════════════════════════════════════════════════
#  DATA CLASSES
# ═══════════════════════════════════════════════════════════════════
@dataclass
class PatternResult:
    name:     str
    detected: bool
    score:    int = 0
    detail:   str = ""

@dataclass
class ScanResult:
    ticker:      str
    date:        str
    close:       float
    volume:      float
    regime:      str
    adx:         float
    rsi:         float
    atr:         float
    vol_ratio:   float
    above_vwap:  bool
    tier:        int  = 0          # 1/2/3 dari pre-filter
    universe:    str  = ""         # A_TRENDING / B_OVERSOLD / BOTH / NEUTRAL
    vol_idr_b:   float = 0.0       # volume dalam miliar IDR
    patterns:    List[PatternResult] = field(default_factory=list)
    combos:      List[dict]          = field(default_factory=list)
    total_score: int                 = 0
    signal:      str                 = ""
    prob_est:    str                 = ""
    notes:       str                 = ""


# ═══════════════════════════════════════════════════════════════════
#  INDIKATOR
# ═══════════════════════════════════════════════════════════════════
def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d.columns = [c.capitalize() for c in d.columns]

    # Candle anatomy
    d['body']        = (d['Close'] - d['Open']).abs()
    d['total_range'] = d['High'] - d['Low']
    d['upper_shadow']= d['High'] - d[['Open','Close']].max(axis=1)
    d['lower_shadow']= d[['Open','Close']].min(axis=1) - d['Low']
    d['is_bullish']  = d['Close'] > d['Open']
    d['pct_change']  = d['Close'].pct_change()
    d['gap_pct']     = (d['Open'] - d['Close'].shift(1)) / d['Close'].shift(1)

    # Volume
    d['vol_ma']      = d['Volume'].rolling(CONFIG['vol_ma_period']).mean()
    d['vol_ratio']   = d['Volume'] / d['vol_ma']

    # ATR
    d['atr']         = ta.volatility.average_true_range(
                           d['High'], d['Low'], d['Close'], window=CONFIG['atr_period'])
    d['atr_ma10']    = d['atr'].rolling(10).mean()
    d['atr_ratio']   = d['atr'] / d['atr_ma10']

    # RSI
    d['rsi']         = ta.momentum.rsi(d['Close'], window=CONFIG['rsi_period'])

    # MACD
    _m               = ta.trend.MACD(d['Close'],
                           window_fast=CONFIG['macd_fast'],
                           window_slow=CONFIG['macd_slow'],
                           window_sign=CONFIG['macd_signal'])
    d['macd']        = _m.macd()
    d['macd_sig']    = _m.macd_signal()
    d['macd_hist']   = _m.macd_diff()
    d['macd_cross']  = (d['macd'] > d['macd_sig']) & (d['macd'].shift(1) <= d['macd_sig'].shift(1))

    # OBV
    d['obv']         = ta.volume.on_balance_volume(d['Close'], d['Volume'])
    d['obv_rising']  = d['obv'] > d['obv'].rolling(10).mean()

    # EMA
    d['ema20']       = ta.trend.ema_indicator(d['Close'], window=20)
    d['ema50']       = ta.trend.ema_indicator(d['Close'], window=50)
    d['above_ema20'] = d['Close'] > d['ema20']
    d['above_ema50'] = d['Close'] > d['ema50']

    # VWAP rolling
    tp               = (d['High'] + d['Low'] + d['Close']) / 3
    d['vwap']        = (tp * d['Volume']).rolling(CONFIG['vwap_period']).sum() / \
                       d['Volume'].rolling(CONFIG['vwap_period']).sum()
    d['above_vwap']  = d['Close'] > d['vwap']

    # ADX
    _adx             = ta.trend.ADXIndicator(
                           d['High'], d['Low'], d['Close'], window=CONFIG['adx_period'])
    d['adx']         = _adx.adx()
    d['di_plus']     = _adx.adx_pos()
    d['di_minus']    = _adx.adx_neg()

    # Supertrend manual
    hl2              = (d['High'] + d['Low']) / 2
    atr_st           = ta.volatility.average_true_range(
                           d['High'], d['Low'], d['Close'],
                           window=CONFIG['supertrend_period'])
    m                = CONFIG['supertrend_mult']
    ub_raw           = hl2 + m * atr_st
    lb_raw           = hl2 - m * atr_st
    st_dir           = pd.Series(1,      index=d.index, dtype=int)
    st_val           = pd.Series(np.nan, index=d.index, dtype=float)

    for j in range(1, len(d)):
        lb = lb_raw.iloc[j]
        ub = ub_raw.iloc[j]
        prev_dir = st_dir.iloc[j-1]
        prev_lb  = lb_raw.iloc[j-1]
        prev_ub  = ub_raw.iloc[j-1]
        if pd.isna(st_val.iloc[j-1]):
            st_dir.iloc[j] = 1; st_val.iloc[j] = lb; continue
        if prev_dir == 1:
            lb = max(lb, prev_lb) if not pd.isna(prev_lb) else lb
            if d['Close'].iloc[j] < lb:
                st_dir.iloc[j] = -1; st_val.iloc[j] = ub
            else:
                st_dir.iloc[j] =  1; st_val.iloc[j] = lb
        else:
            ub = min(ub, prev_ub) if not pd.isna(prev_ub) else ub
            if d['Close'].iloc[j] > ub:
                st_dir.iloc[j] =  1; st_val.iloc[j] = lb
            else:
                st_dir.iloc[j] = -1; st_val.iloc[j] = ub

    d['st_dir']       = st_dir
    d['st_flip_bull'] = (d['st_dir'] == 1) & (d['st_dir'].shift(1) == -1)
    return d


# ═══════════════════════════════════════════════════════════════════
#  MARKET REGIME
# ═══════════════════════════════════════════════════════════════════
def get_regime(d, i):
    adx = d['adx'].iloc[i]
    if pd.isna(adx): return "UNKNOWN"
    if adx >= CONFIG['adx_trending'] and d['di_plus'].iloc[i] > d['di_minus'].iloc[i]:
        return "TRENDING"
    elif adx >= CONFIG['adx_sideways']:
        return "SIDEWAYS"
    return "CHOPPY"

REGIME_NOTES = {
    "TRENDING": "ADX≥25, +DI>-DI → uptrend kuat. Semua pola breakout valid. "
                "Combo A/B/E paling efektif di sini.",
    "SIDEWAYS": "ADX 15-25 → konsolidasi. Hanya reversal (#4 Hammer, #9 Divergence) yang valid.",
    "CHOPPY":   "ADX<15 → no trend. False signal tinggi, sebaiknya skip semua pola.",
    "UNKNOWN":  "Data ADX tidak mencukupi.",
}


# ═══════════════════════════════════════════════════════════════════
#  10 DETEKTOR POLA
# ═══════════════════════════════════════════════════════════════════
def p1_volume_breakout(d, i):
    name = "#1 Vol Breakout Konsolidasi"
    n    = CONFIG['consolidation_days']
    if i < n+3: return PatternResult(name, False)
    w_hi = d['High'].iloc[i-n:i].max()
    w_lo = d['Low'].iloc[i-n:i].min()
    rng  = (w_hi-w_lo)/w_lo if w_lo>0 else 1.0
    vr   = d['vol_ratio'].iloc[i]
    if rng  > CONFIG['consolidation_range']: return PatternResult(name, False, detail=f"range={rng:.1%}")
    if vr   < CONFIG['vol_spike_mult']:      return PatternResult(name, False, detail=f"vol={vr:.1f}x")
    if d['Close'].iloc[i] <= w_hi*0.995:    return PatternResult(name, False, detail="belum breakout")
    obv_ok = d['obv'].iloc[i] > d['obv'].iloc[i-n]
    sc = 2
    if vr    >= CONFIG['vol_strong_mult']:  sc += 1
    if d['obv_rising'].iloc[i]:             sc += 1
    if d['above_vwap'].iloc[i]:             sc += 1
    if obv_ok:                              sc += 1
    return PatternResult(name, True, sc, f"range={rng:.1%}|vol={vr:.1f}x|OBV↑={obv_ok}")

def p2_bull_flag(d, i):
    name = "#2 Bull Flag / Pennant"
    fd   = CONFIG['flag_days']
    if i < fd+8: return PatternResult(name, False)
    ps, pe   = i-fd-5, i-fd
    pole_hi  = d['High'].iloc[ps:pe].max()
    pole_lo  = d['Low'].iloc[ps:pe].min()
    pole_pct = (pole_hi-pole_lo)/pole_lo if pole_lo>0 else 0
    if pole_pct < CONFIG['flag_pole_min_pct']:
        return PatternResult(name, False, detail=f"tiang={pole_pct:.1%}")
    flag_hi   = d['High'].iloc[i-fd:i].max()
    flag_rng  = (flag_hi - d['Low'].iloc[i-fd:i].min())/flag_hi if flag_hi>0 else 1.0
    vol_surut = d['Volume'].iloc[i-fd:i].mean() < d['Volume'].iloc[ps:pe].mean()
    breakout  = d['Close'].iloc[i] > flag_hi*0.995
    if not (vol_surut and breakout):
        return PatternResult(name, False, detail=f"vol_surut={vol_surut}|breakout={breakout}")
    vr = d['vol_ratio'].iloc[i]
    sc = 2
    if vr  >= CONFIG['vol_spike_mult']: sc += 1
    if d['obv_rising'].iloc[i]:         sc += 1
    if d['above_vwap'].iloc[i]:         sc += 1
    if flag_rng < 0.04:                 sc += 1
    return PatternResult(name, True, sc, f"tiang={pole_pct:.1%}|flag_rng={flag_rng:.1%}|vol={vr:.1f}x")

def p3_ascending_triangle(d, i):
    name = "#3 Ascending Triangle"
    lb   = CONFIG['triangle_lookback']
    if i < lb: return PatternResult(name, False)
    w     = d.iloc[i-lb:i+1]
    top5  = w['High'].nlargest(5)
    flat  = (top5.max()-top5.min())/top5.max() < 0.03
    if not flat: return PatternResult(name, False, detail="resistance tidak flat")
    lows  = w['Low'].values
    ll    = [lows[j] for j in range(1, len(lows)-1)
             if lows[j]<lows[j-1] and lows[j]<lows[j+1]]
    if len(ll) < CONFIG['higher_lows_min']:
        return PatternResult(name, False, detail=f"only {len(ll)} local lows")
    hl_ok = all(ll[k]>ll[k-1] for k in range(1, len(ll)))
    if not hl_ok: return PatternResult(name, False, detail="lows tidak higher")
    resist   = top5.max()
    breakout = d['Close'].iloc[i] > resist*0.998
    vr   = d['vol_ratio'].iloc[i]
    rsi  = d['rsi'].iloc[i]
    sc   = 2 if breakout else 1
    if vr  >= CONFIG['vol_spike_mult']:                                sc += 1
    if d['above_vwap'].iloc[i]:                                        sc += 1
    if CONFIG['rsi_momentum_lo']<rsi<CONFIG['rsi_momentum_hi']:        sc += 1
    if d['macd_cross'].iloc[i]:                                        sc += 1
    return PatternResult(name, True, sc,
        f"resist={resist:.0f}|HL={len(ll)}|breakout={breakout}|vol={vr:.1f}x")

def p4_hammer(d, i):
    name = "#4 Hammer Reversal"
    if i < 6: return PatternResult(name, False)
    body  = d['body'].iloc[i]
    lo_sh = d['lower_shadow'].iloc[i]
    up_sh = d['upper_shadow'].iloc[i]
    rsi   = d['rsi'].iloc[i]
    if body <= 0: return PatternResult(name, False)
    is_h  = (lo_sh >= CONFIG['hammer_lower_shadow']*body and
             up_sh <= CONFIG['hammer_upper_shadow']*body)
    if not is_h:
        return PatternResult(name, False, detail=f"lo_sh/body={lo_sh/body:.1f}x")
    if rsi > CONFIG['rsi_oversold']:
        return PatternResult(name, False, detail=f"RSI={rsi:.0f} belum oversold")
    downtrend = d['Close'].iloc[i-5] > d['Close'].iloc[i]*1.02
    vr = d['vol_ratio'].iloc[i]
    sc = 2
    if vr  >= CONFIG['vol_spike_mult']:                           sc += 1
    if rsi < 30:                                                  sc += 1
    if d['macd_hist'].iloc[i] > d['macd_hist'].iloc[i-1]:        sc += 1
    if downtrend:                                                 sc += 1
    if d['above_vwap'].iloc[i]:                                   sc += 1
    return PatternResult(name, True, sc,
        f"RSI={rsi:.0f}|lo_sh={lo_sh/body:.1f}x|vol={vr:.1f}x|dntrend={downtrend}")

def p5_marubozu(d, i):
    name = "#5 Bullish Marubozu"
    if i < 2: return PatternResult(name, False)
    body  = d['body'].iloc[i]
    tr    = d['total_range'].iloc[i]
    up_sh = d['upper_shadow'].iloc[i]
    lo_sh = d['lower_shadow'].iloc[i]
    if tr<=0 or not d['is_bullish'].iloc[i]: return PatternResult(name, False)
    br  = body/tr
    shd = (up_sh<=CONFIG['marubozu_shadow_max']*body and
           lo_sh<=CONFIG['marubozu_shadow_max']*body)
    if br<CONFIG['marubozu_body_ratio'] or not shd:
        return PatternResult(name, False, detail=f"body_ratio={br:.0%}")
    vr  = d['vol_ratio'].iloc[i]
    pct = d['pct_change'].iloc[i]
    rsi = d['rsi'].iloc[i]
    sc  = 2
    if vr  >= CONFIG['vol_strong_mult']:   sc += 1
    if d['above_vwap'].iloc[i]:            sc += 1
    if pct > 0.03:                         sc += 1
    if rsi < CONFIG['rsi_overbought']:     sc += 1
    return PatternResult(name, True, sc, f"body={br:.0%}|+{pct:.1%}|vol={vr:.1f}x|RSI={rsi:.0f}")

def p6_gap_go(d, i):
    name = "#6 Gap & Go"
    if i < 3: return PatternResult(name, False)
    gap = d['gap_pct'].iloc[i]
    vr  = d['vol_ratio'].iloc[i]
    if gap < CONFIG['gap_min_pct']:
        return PatternResult(name, False, detail=f"gap={gap:.1%}")
    if not d['is_bullish'].iloc[i]:
        return PatternResult(name, False, detail="candle bearish")
    gap_holds = d['Close'].iloc[i] > d['Open'].iloc[i]*0.995
    sc = 2
    if vr  >= CONFIG['vol_strong_mult']:  sc += 1
    if gap >= CONFIG['gap_strong_pct']:   sc += 1
    if d['above_vwap'].iloc[i]:           sc += 1
    if gap_holds:                         sc += 1
    return PatternResult(name, True, sc, f"gap={gap:.1%}|vol={vr:.1f}x|holds={gap_holds}")

def p7_cup_handle(d, i):
    name = "#7 Cup & Handle"
    lb   = min(i, CONFIG['cup_lookback'])
    if i < CONFIG['cup_min_days']+5: return PatternResult(name, False)
    w       = d.iloc[i-lb:i+1]
    rim_idx = w['High'].idxmax()
    rim_pos = w.index.get_loc(rim_idx)
    if rim_pos<5 or rim_pos>len(w)-5: return PatternResult(name, False)
    rim_price  = w['High'].max()
    cup_bottom = w['Low'].iloc[rim_pos:].min()
    depth      = (rim_price-cup_bottom)/rim_price
    if depth > CONFIG['cup_max_depth']:
        return PatternResult(name, False, detail=f"cup terlalu dalam ({depth:.0%})")
    near_rim = d['Close'].iloc[i] >= rim_price*0.93
    if not near_rim:
        return PatternResult(name, False, detail="belum recovery ke rim")
    h_w   = d['Close'].iloc[i-5:i]
    h_rng = (h_w.max()-h_w.min())/h_w.max() if len(h_w)>0 else 1.0
    h_ok  = h_rng < CONFIG['handle_max_retrace']
    vr    = d['vol_ratio'].iloc[i]
    sc    = 2
    if h_ok:                           sc += 1
    if vr  >= CONFIG['vol_spike_mult']:sc += 1
    if d['above_vwap'].iloc[i]:        sc += 1
    if depth < 0.20:                   sc += 1
    return PatternResult(name, True, sc,
        f"depth={depth:.0%}|handle_rng={h_rng:.0%}|vol={vr:.1f}x")

def p8_orb(d, i):
    name = "#8 ORB Full Gap Momentum"
    if i < 2: return PatternResult(name, False)
    prev_hi = d['High'].iloc[i-1]
    t_open  = d['Open'].iloc[i]
    t_close = d['Close'].iloc[i]
    if t_open <= prev_hi:
        return PatternResult(name, False, detail="open tidak di atas high kemarin")
    momentum = t_close > t_open
    vr       = d['vol_ratio'].iloc[i]
    sc = 2
    if momentum:                        sc += 1
    if vr >= CONFIG['vol_spike_mult']:  sc += 1
    if d['above_vwap'].iloc[i]:         sc += 1
    return PatternResult(name, True, sc,
        f"open={t_open:.0f}>prev_hi={prev_hi:.0f}|momentum={momentum}|vol={vr:.1f}x")

def p9_triple_divergence(d, i):
    name = "#9 Triple Divergence"
    if i < 14: return PatternResult(name, False)
    prev       = d.iloc[i-12:i]
    prev_lo    = prev['Low'].idxmin()
    p          = d.index.get_loc(prev_lo)
    price_ll   = d['Low'].iloc[i]  < d['Low'].iloc[p]
    rsi_hl     = d['rsi'].iloc[i]  > d['rsi'].iloc[p]
    macd_hl    = d['macd_hist'].iloc[i] > d['macd_hist'].iloc[p]
    vol_ok     = d['vol_ratio'].iloc[i] > 1.0
    n_div      = sum([price_ll, rsi_hl, macd_hl])
    if n_div < 2:
        return PatternResult(name, False, detail=f"div={n_div}/3")
    rsi = d['rsi'].iloc[i]
    sc  = n_div
    if rsi < CONFIG['rsi_oversold']:    sc += 1
    if vol_ok:                          sc += 1
    if d['is_bullish'].iloc[i]:         sc += 1
    if d['macd_cross'].iloc[i]:         sc += 1
    return PatternResult(name, True, sc,
        f"div={n_div}/3|RSI_div={rsi_hl}|MACD_div={macd_hl}|RSI={rsi:.0f}")

def p10_supertrend_flip(d, i):
    name = "#10 Supertrend Flip"
    if i < CONFIG['supertrend_period']+5: return PatternResult(name, False)
    flip = d['st_flip_bull'].iloc[i]
    vr   = d['vol_ratio'].iloc[i]
    if not flip:  return PatternResult(name, False, detail="tidak ada flip")
    if vr < 1.0:  return PatternResult(name, False, detail=f"vol={vr:.1f}x")
    rsi = d['rsi'].iloc[i]
    sc  = 2
    if vr  >= CONFIG['vol_spike_mult']:       sc += 1
    if d['above_vwap'].iloc[i]:               sc += 1
    if rsi < CONFIG['rsi_overbought']:        sc += 1
    return PatternResult(name, True, sc, f"ST_flip=True|vol={vr:.1f}x|RSI={rsi:.0f}")

DETECTORS = [
    p1_volume_breakout, p2_bull_flag, p3_ascending_triangle,
    p4_hammer, p5_marubozu, p6_gap_go, p7_cup_handle,
    p8_orb, p9_triple_divergence, p10_supertrend_flip,
]


# ═══════════════════════════════════════════════════════════════════
#  COMBO DETECTOR
# ═══════════════════════════════════════════════════════════════════
def detect_combos(pmap: Dict[str, PatternResult]) -> List[dict]:
    def on(k): return any(pr.detected for n, pr in pmap.items() if k in n)
    combos = []
    if on("#3") and on("#1") and on("#5"):
        combos.append({"tier":1,"prob":"85-90%",
            "name":"COMBO A ⭐ Ascending Triangle + Vol Breakout + Marubozu"})
    if on("#7") and on("#1") and on("#6"):
        combos.append({"tier":1,"prob":"88-93%",
            "name":"COMBO B ⭐ Cup & Handle + Vol Breakout + Gap Up"})
    if on("#4") and on("#5") and on("#9"):
        combos.append({"tier":1,"prob":"78-83%",
            "name":"COMBO C ⭐ Hammer + Marubozu + Triple Divergence"})
    if on("#2") and on("#8"):
        combos.append({"tier":2,"prob":"75-80%",
            "name":"COMBO D  Bull Flag + ORB + VWAP Reclaim"})
    if on("#6") and on("#10") and on("#1"):
        combos.append({"tier":2,"prob":"74-79%",
            "name":"COMBO E  Gap & Go + Supertrend Flip + Vol Breakout"})
    active = [n for n,pr in pmap.items() if pr.detected]
    if len(active)>=2 and not combos:
        short = [n.split(" ",1)[1][:18] for n in active[:3]]
        combos.append({"tier":3,"prob":"68-75%",
            "name":f"MULTI-POLA ({' + '.join(short)})"})
    return combos


# ═══════════════════════════════════════════════════════════════════
#  CONFLUENCE SCORE & SIGNAL
# ═══════════════════════════════════════════════════════════════════
def confluence_score(d, i, pmap) -> int:
    sc = sum(pr.score for pr in pmap.values() if pr.detected)
    if d['above_vwap'].iloc[i]:                                            sc += 1
    if d['atr_ratio'].iloc[i] > CONFIG['atr_expansion_mult']:             sc += 1
    rsi = d['rsi'].iloc[i]
    if CONFIG['rsi_momentum_lo'] < rsi < CONFIG['rsi_momentum_hi']:        sc += 1
    if d['macd_cross'].iloc[i]:                                            sc += 1
    if d['obv_rising'].iloc[i]:                                            sc += 1
    if d['st_dir'].iloc[i] == 1:                                           sc += 1
    return sc

def score_to_signal(score, regime):
    if regime == "CHOPPY":   return "⛔ SKIP — Choppy", "N/A"
    if regime == "SIDEWAYS":
        if score >= CONFIG['score_entry']: return "🟡 BUY (reversal)", "55-65%"
        return "⚪ WATCHLIST", "45-55%"
    if score >= CONFIG['score_strong']:    return "🟢 STRONG BUY", ">80%"
    elif score >= CONFIG['score_entry']:   return "🟡 BUY", "65-79%"
    elif score >= CONFIG['score_watch']:   return "⚪ WATCHLIST", "50-64%"
    return "⛔ NO SIGNAL", "<50%"


# ═══════════════════════════════════════════════════════════════════
#  MAIN SCAN FUNCTION — public API
# ═══════════════════════════════════════════════════════════════════
def scan_dataframe(ticker: str, df_raw: pd.DataFrame,
                   min_rows: int = 60,
                   filter_result=None) -> Optional[ScanResult]:
    """
    Scan OHLCV DataFrame dan return ScanResult.

    Parameter
    ---------
    ticker        : nama saham, e.g. "BBCA"
    df_raw        : DataFrame OHLCV (Open/High/Low/Close/Volume)
    min_rows      : minimum bar data
    filter_result : hasil pre_filter() jika sudah dijalankan (opsional)

    Contoh integrasi bei_scanner.py:
    ---------------------------------
    from bei_pattern_scanner import scan_dataframe, pre_filter, format_result

    df = tv.get_hist(symbol="BBCA", exchange="IDX",
                     interval=Interval.in_daily, n_bars=200)
    fr = pre_filter(df, "BBCA")
    if fr.passed:
        result = scan_dataframe("BBCA", df, filter_result=fr)
        if result and result.signal.startswith("🟢"):
            send_telegram(format_result(result))
    """
    try:
        if df_raw is None or len(df_raw) < min_rows:
            return None

        # Jalankan pre_filter otomatis jika belum dijalankan
        if filter_result is None:
            filter_result = pre_filter(df_raw, ticker)
        if not filter_result.passed:
            return None

        d  = compute_indicators(df_raw)
        i  = len(d) - 1
        regime = get_regime(d, i)

        pmap: Dict[str, PatternResult] = {}
        for fn in DETECTORS:
            pr = fn(d, i)
            pmap[pr.name] = pr

        active = [pr for pr in pmap.values() if pr.detected]
        combos = detect_combos(pmap)
        sc     = confluence_score(d, i, pmap)
        signal, prob = score_to_signal(sc, regime)

        return ScanResult(
            ticker      = ticker,
            date        = str(d.index[-1].date()) if hasattr(d.index[-1],'date') else str(d.index[-1]),
            close       = round(float(d['Close'].iloc[i]), 2),
            volume      = float(d['Volume'].iloc[i]),
            regime      = regime,
            adx         = round(float(d['adx'].iloc[i] or 0), 1),
            rsi         = round(float(d['rsi'].iloc[i] or 0), 1),
            atr         = round(float(d['atr'].iloc[i] or 0), 2),
            vol_ratio   = round(float(d['vol_ratio'].iloc[i]), 2),
            above_vwap  = bool(d['above_vwap'].iloc[i]),
            tier        = filter_result.tier,
            universe    = filter_result.universe,
            vol_idr_b   = round(filter_result.vol_idr / 1e9, 2),
            patterns    = active,
            combos      = combos,
            total_score = sc,
            signal      = signal,
            prob_est    = prob,
            notes       = REGIME_NOTES.get(regime, ""),
        )
    except Exception as e:
        return None


def scan_csv(filepath: str, ticker: str = "") -> Optional[ScanResult]:
    if not ticker:
        ticker = os.path.splitext(os.path.basename(filepath))[0].upper()
    df = pd.read_csv(filepath, index_col=0, parse_dates=True)
    fr = pre_filter(df, ticker)
    if not fr.passed:
        return None
    return scan_dataframe(ticker, df, filter_result=fr)


def scan_csv_dir(dirpath: str, verbose: bool = True) -> List[ScanResult]:
    """Scan folder CSV dengan pre-filter otomatis di setiap saham."""
    files   = sorted(f for f in os.listdir(dirpath) if f.endswith('.csv'))
    results = []
    skipped = 0

    for idx, fname in enumerate(files, 1):
        ticker = os.path.splitext(fname)[0].upper()
        if verbose: print(f"  [{idx:3d}/{len(files)}] {ticker:<12}", end="\r")

        df = pd.read_csv(os.path.join(dirpath, fname), index_col=0, parse_dates=True)
        fr = pre_filter(df, ticker)

        if not fr.passed:
            skipped += 1
            continue

        r = scan_dataframe(ticker, df, filter_result=fr)
        if r and "NO SIGNAL" not in r.signal and "SKIP" not in r.signal:
            results.append(r)

    if verbose:
        print(" "*60, end="\r")
        print(f"  Pre-filter: {len(files)-skipped}/{len(files)} lolos | {skipped} dilewati")

    results.sort(key=lambda r: (
        r.tier,                                          # Tier 1 dulu
        -sum(1 for c in r.combos if c['tier']==1),      # Combo T1 dulu
        -r.total_score
    ))
    return results


# ═══════════════════════════════════════════════════════════════════
#  FULL AUTO SCAN — tvdatafeed + Universe Builder + Pattern Scanner
# ═══════════════════════════════════════════════════════════════════

def run_auto_scan(tv, tickers: List[str] = None, verbose: bool = True) -> List[ScanResult]:
    """
    Pipeline lengkap: tvdatafeed → Universe Builder → Pre-filter → 10 Pola.

    Cara pakai di bei_scanner.py:
    ------------------------------
    from tvDatafeed import TvDatafeed, Interval
    from bei_pattern_scanner import run_auto_scan, format_result, format_summary

    tv = TvDatafeed(username=TV_USER, password=TV_PASS)
    results = run_auto_scan(tv)

    for r in results:
        if "STRONG" in r.signal or any(c['tier']==1 for c in r.combos):
            send_telegram(format_result(r))

    send_telegram(format_summary(results))
    """
    import time

    if tickers is None:
        tickers = WATCHLIST_ALL

    results  = []
    skipped  = 0
    total    = len(tickers)

    if verbose:
        print(f"\n  🔍 Auto scan {total} saham dari tvdatafeed...")
        print(f"  Delay antar request: {CONFIG['tv_delay_sec']}s\n")

    for idx, ticker in enumerate(tickers, 1):
        if verbose:
            print(f"  [{idx:3d}/{total}] {ticker:<10}", end="\r")

        # Fetch data
        try:
            from tvDatafeed import Interval
            df = tv.get_hist(
                symbol   = ticker,
                exchange = CONFIG['tv_exchange'],
                interval = Interval.in_daily,
                n_bars   = CONFIG['tv_n_bars'],
            )
            time.sleep(CONFIG['tv_delay_sec'])
        except Exception as e:
            skipped += 1
            continue

        # Pre-filter
        fr = pre_filter(df, ticker)
        if not fr.passed:
            skipped += 1
            continue

        # Scan pola
        r = scan_dataframe(ticker, df, filter_result=fr)
        if r and "NO SIGNAL" not in r.signal and "SKIP" not in r.signal:
            results.append(r)

    if verbose:
        print(" "*60, end="\r")
        print(f"  ✅ Selesai: {len(results)} sinyal dari {total-skipped} saham valid")
        print(f"  ⏭  Dilewati: {skipped} (iliquid/no data/error)")

    results.sort(key=lambda r: (
        r.tier,
        -sum(1 for c in r.combos if c['tier']==1),
        -r.total_score
    ))
    return results


# ═══════════════════════════════════════════════════════════════════
#  OUTPUT FORMATTER — bisa digunakan untuk Telegram message
# ═══════════════════════════════════════════════════════════════════
LINE  = "─" * 66
DLINE = "═" * 66

def format_result(r: ScanResult) -> str:
    """Format ScanResult ke string. Bisa langsung kirim via Telegram."""
    tier_emoji = {1:"🔵", 2:"🟢", 3:"🟡"}.get(r.tier, "⚪")
    univ_label = {
        "A_TRENDING":"📈 Trending",
        "B_OVERSOLD":"📉 Oversold",
        "BOTH":      "🔄 Both",
        "NEUTRAL":   "➡️  Neutral",
    }.get(r.universe, r.universe)

    lines = [
        f"\n{DLINE}",
        f"  {r.ticker:<12} | {r.date} | Close: {r.close:>10,.2f}",
        f"  {tier_emoji} Tier {r.tier} | {univ_label:<16} | Vol IDR: {r.vol_idr_b:.1f}B/hari",
        f"  Vol: {r.volume:>14,.0f} ({r.vol_ratio:.1f}x) | VWAP↑: {r.above_vwap}",
        f"  Regime:{r.regime:<10}| ADX:{r.adx:>5.1f} | RSI:{r.rsi:>5.1f} | ATR:{r.atr:>8.2f}",
        f"  Score : {r.total_score}/~20 | Signal: {r.signal} | Prob: {r.prob_est}",
        LINE,
    ]
    if r.patterns:
        lines.append("  POLA AKTIF:")
        for pr in r.patterns:
            lines.append(f"    ✅ {pr.name:<36} [+{pr.score}]")
            if pr.detail:
                lines.append(f"       └ {pr.detail}")
    if r.combos:
        lines.append(f"\n  KOMBINASI:")
        for c in r.combos:
            t = "⭐TIER1" if c['tier']==1 else "  TIER2" if c['tier']==2 else "  MULTI"
            lines.append(f"    {t} {c['name']}  [{c['prob']}]")
    if r.notes:
        lines.append(f"\n  ℹ {r.notes[:80]}")
    lines.append(DLINE)
    return "\n".join(lines)


def format_summary(results: List[ScanResult]) -> str:
    strong = [r for r in results if "STRONG" in r.signal]
    buy    = [r for r in results if r.signal.startswith("🟡")]
    c1     = [r for r in results if any(c['tier']==1 for c in r.combos)]
    t1_r   = [r for r in results if r.tier == 1]
    univ_a = [r for r in results if r.universe in ("A_TRENDING","BOTH")]
    univ_b = [r for r in results if r.universe in ("B_OVERSOLD","BOTH")]

    lines  = [
        "\n\n" + DLINE,
        "              RINGKASAN SCAN BEI v3.0",
        DLINE,
        f"  Total sinyal  : {len(results)}  |  STRONG BUY: {len(strong)}  |  BUY: {len(buy)}  |  Combo T1: {len(c1)}",
        f"  Tier 1 (Blue) : {len(t1_r)}  |  Universe A (Trending): {len(univ_a)}  |  Universe B (Oversold): {len(univ_b)}",
        "",
        f"  {'TICKER':<10} {'T'} {'UNV':<11} {'SIGNAL':<16} {'SCR':>4} {'PROB':<8} COMBO",
        f"  {'─'*10} {'─'} {'─'*11} {'─'*16} {'─'*4} {'─'*8} {'─'*28}",
    ]
    for r in results[:25]:
        sig   = r.signal.replace("🟢 ","").replace("🟡 ","").replace("⚪ ","")
        cname = r.combos[0]['name'][:26] if r.combos else "—"
        unv   = r.universe[:10]
        lines.append(
            f"  {r.ticker:<10} {r.tier} {unv:<11} {sig:<16} {r.total_score:>4} {r.prob_est:<8} {cname}"
        )
    lines.append(DLINE)
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
#  DEMO — data sintetis
# ═══════════════════════════════════════════════════════════════════
def make_synthetic(pattern="combo_a", n=120, seed=42):
    np.random.seed(seed)
    dates = pd.date_range('2025-11-01', periods=n, freq='B')
    c = [1000.0]
    for _ in range(n-1): c.append(c[-1]*(1+np.random.normal(0.0008,0.015)))
    c = np.array(c)
    h = c*(1+np.abs(np.random.normal(0,0.010,n)))
    l = c*(1-np.abs(np.random.normal(0,0.010,n)))
    o = l+(h-l)*np.random.uniform(0.2,0.8,n)
    v = np.abs(np.random.normal(5_000_000,1_500_000,n))

    if pattern == "combo_a":
        for k in range(n-12,n-2):
            l[k] = l[n-13]*(1+0.004*(k-(n-13)))
        h[n-12:n-1] = h[n-13]*1.004
        c[-1]=h[-2]*1.058; h[-1]=c[-1]; l[-1]=o[-1]=h[-2]*1.001
        v[-1]=v[:-1].mean()*4.2
    elif pattern == "combo_b":
        mid=n//2; depth=0.18
        for k in range(mid-10,mid+10):
            dist=abs(k-mid); c[k]=c[mid-10]*(1-depth*(1-dist/10)**2)
        for k in range(mid+10,n-3): c[k]=c[mid-10]*(1+0.003*(k-(mid+10)))
        h[mid:]=c[mid:]*1.012; l[mid:]=c[mid:]*0.988
        c[-1]=c[-2]*1.062; o[-1]=c[-2]*1.025
        h[-1]=c[-1]*1.002; l[-1]=o[-1]*0.999; v[-1]=v[:-1].mean()*5.1
    elif pattern == "hammer_rev":
        for k in range(n-10,n-2): c[k]=c[k-1]*0.983
        bs=c[n-3]*0.008
        l[n-2]=c[n-3]*0.93; o[n-2]=l[n-2]+bs*0.3
        c[n-2]=o[n-2]+bs; h[n-2]=c[n-2]*1.002; v[n-2]=v[:-2].mean()*2.8
        o[-1]=c[n-2]; c[-1]=o[-1]*1.063
        h[-1]=c[-1]; l[-1]=o[-1]; v[-1]=v[:-1].mean()*3.8

    o=np.clip(o,l,h)
    return pd.DataFrame({'Open':o,'High':h,'Low':l,'Close':c,'Volume':v}, index=dates)


def run_demo():
    print(f"\n{'═'*66}")
    print("  BEI CONFLUENCE PATTERN SCANNER v2.0 — DEMO MODE")
    print(f"{'═'*66}\n")
    scenarios = [
        ("DEMO_A","combo_a",  "Combo A: Ascending Triangle + Vol Breakout + Marubozu"),
        ("DEMO_B","combo_b",  "Combo B: Cup & Handle + Vol Breakout + Gap Up"),
        ("DEMO_C","hammer_rev","Combo C area: Hammer → Marubozu Reversal"),
        ("DEMO_D","random",   "Random / baseline"),
    ]
    all_r = []
    for ticker, patt, desc in scenarios:
        print(f"  📊 {ticker} — {desc}")
        df = make_synthetic(patt)
        r  = scan_dataframe(ticker, df)
        if r:
            print(format_result(r))
            all_r.append(r)
        else:
            print("  → Tidak ada sinyal.\n")
    if all_r:
        print(format_summary(all_r))


# ═══════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser(
        description="BEI Confluence Pattern Scanner v3.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Contoh:
  python bei_pattern_scanner.py --demo
  python bei_pattern_scanner.py --csv ./data/BBCA.csv
  python bei_pattern_scanner.py --csv-dir ./data/ --out hasil.csv
  python bei_pattern_scanner.py --build-universe --csv-dir ./data/
  python bei_pattern_scanner.py --auto --delay 1.5
        """
    )
    ap.add_argument("--demo",            action="store_true", help="Demo dengan data sintetis")
    ap.add_argument("--csv",             metavar="FILE",      help="Scan satu file CSV")
    ap.add_argument("--ticker",          metavar="NAME",      default="")
    ap.add_argument("--csv-dir",         metavar="DIR",       help="Scan folder CSV")
    ap.add_argument("--out",             metavar="FILE",      default="", help="Export CSV hasil")
    ap.add_argument("--build-universe",  action="store_true", help="Tampilkan universe breakdown saja")
    ap.add_argument("--auto",            action="store_true", help="Full auto via tvdatafeed")
    ap.add_argument("--delay",           type=float, default=CONFIG['tv_delay_sec'],
                                         help=f"Delay antar request (default: {CONFIG['tv_delay_sec']}s)")
    ap.add_argument("--tier",            type=int, default=0,
                                         help="Filter tier: 1=blue chip, 2=mid-cap, 3=small, 0=semua")
    ap.add_argument("--universe",        choices=["A","B","ALL"], default="ALL",
                                         help="Filter universe: A=Trending, B=Oversold, ALL=semua")
    args = ap.parse_args()
    CONFIG['tv_delay_sec'] = args.delay

    print(f"\n{DLINE}")
    print("  BEI CONFLUENCE PATTERN SCANNER v3.0")
    print("  10 Pola | Pre-Filter | Universe Builder | Combo A-E")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S WIB')}")
    print(f"  Watchlist: {len(WATCHLIST_ALL)} saham ({len(WATCHLIST_T1)} T1 | {len(WATCHLIST_T2)} T2 | {len(WATCHLIST_T3)} T3)")
    print(DLINE)

    # ── Demo ───────────────────────────────────────────────
    if args.demo or (not args.csv and not getattr(args,'csv_dir',None)
                     and not args.auto and not args.build_universe):
        run_demo(); return

    # ── Build Universe saja ─────────────────────────────────
    if args.build_universe:
        csv_dir = getattr(args, 'csv_dir', None)
        if csv_dir:
            ub = UniverseBuilder(verbose=True)
            ub.load_from_csv_dir(csv_dir)
            u = ub.build()
            # Print top 10 per universe
            for key in ["A_TRENDING","B_OVERSOLD","BOTH","NEUTRAL"]:
                items = u.get(key, [])
                if items:
                    print(f"\n  {key} ({len(items)} saham) — top 10:")
                    for item in items[:10]:
                        print(f"    T{item['tier']} {item['ticker']:<10} Vol: {item['vol_idr_b']:.1f}B IDR/hr")
            print(f"\n  SKIPPED: {len(u['SKIPPED'])} saham iliquid/error")
        else:
            print("  Gunakan --build-universe dengan --csv-dir untuk load data")
        return

    # ── Satu CSV ────────────────────────────────────────────
    if args.csv:
        r = scan_csv(args.csv, args.ticker)
        print(format_result(r) if r else "  Tidak ada sinyal (atau tidak lolos pre-filter)."); return

    # ── Folder CSV ──────────────────────────────────────────
    csv_dir = getattr(args, 'csv_dir', None)
    if csv_dir:
        print(f"\n  Scanning: {csv_dir}\n")
        results = scan_csv_dir(csv_dir)

        # Filter tier/universe jika diminta
        if args.tier > 0:
            results = [r for r in results if r.tier == args.tier]
        if args.universe == "A":
            results = [r for r in results if r.universe in ("A_TRENDING","BOTH")]
        elif args.universe == "B":
            results = [r for r in results if r.universe in ("B_OVERSOLD","BOTH")]

        for r in results: print(format_result(r))
        print(format_summary(results))

        if args.out and results:
            rows=[{
                "Ticker":    r.ticker,  "Date":     r.date,
                "Close":     r.close,   "Volume":   r.volume,
                "Vol_IDR_B": r.vol_idr_b, "Tier":   r.tier,
                "Universe":  r.universe,"Regime":   r.regime,
                "ADX":       r.adx,     "RSI":      r.rsi,
                "Vol_Ratio": r.vol_ratio,"Score":   r.total_score,
                "Signal":    r.signal,  "Prob":     r.prob_est,
                "Pola":      "|".join(pr.name for pr in r.patterns),
                "Combo":     r.combos[0]['name'] if r.combos else "",
                "Combo_Prob":r.combos[0]['prob'] if r.combos else "",
            } for r in results]
            pd.DataFrame(rows).to_csv(args.out, index=False)
            print(f"\n  ✅ Disimpan ke: {args.out}")
        print(f"\n  ✅ Selesai. {len(results)} sinyal.")
        return

    # ── Full Auto via tvdatafeed ────────────────────────────
    if args.auto:
        try:
            from tvDatafeed import TvDatafeed
            import getpass
            print("\n  Masukkan kredensial TradingView:")
            user = input("  Username: ").strip()
            pw   = getpass.getpass("  Password: ")
            tv   = TvDatafeed(username=user, password=pw)

            tickers = WATCHLIST_ALL
            if args.tier > 0:
                tier_map = {1: WATCHLIST_T1, 2: WATCHLIST_T2, 3: WATCHLIST_T3}
                tickers  = tier_map.get(args.tier, WATCHLIST_ALL)

            results = run_auto_scan(tv, tickers=tickers)

            if args.universe == "A":
                results = [r for r in results if r.universe in ("A_TRENDING","BOTH")]
            elif args.universe == "B":
                results = [r for r in results if r.universe in ("B_OVERSOLD","BOTH")]

            for r in results: print(format_result(r))
            print(format_summary(results))

            if args.out and results:
                rows=[{
                    "Ticker":r.ticker, "Date":r.date, "Close":r.close,
                    "Vol_IDR_B":r.vol_idr_b, "Tier":r.tier, "Universe":r.universe,
                    "Regime":r.regime, "ADX":r.adx, "RSI":r.rsi,
                    "Score":r.total_score, "Signal":r.signal, "Prob":r.prob_est,
                    "Pola":"|".join(pr.name for pr in r.patterns),
                    "Combo":r.combos[0]['name'] if r.combos else "",
                } for r in results]
                pd.DataFrame(rows).to_csv(args.out, index=False)
                print(f"\n  ✅ Disimpan ke: {args.out}")

        except ImportError:
            print("  ❌ tvDatafeed tidak terinstall.")
            print("  Install: pip install --upgrade git+https://github.com/rongardF/tvdatafeed.git")
        return

    print("  Gunakan --help untuk melihat opsi.")

if __name__ == "__main__":
    main()
