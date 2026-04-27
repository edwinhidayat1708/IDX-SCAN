"""
BEI Auto Scanner — Entry Point untuk GitHub Actions
====================================================
Flow:
  1. Login TradingView via session cookie (dari GitHub Secrets)
  2. Fetch OHLCV data untuk semua saham di watchlist
  3. Pre-filter likuiditas + universe classification
  4. Scan 10 pola teknikal + deteksi Combo A-E
  5. Kirim notifikasi Telegram (per sinyal kuat + ringkasan harian)

Dipanggil oleh: .github/workflows/scan.yml
Environment variables yang dibutuhkan (set di GitHub Secrets):
  TV_USERNAME      — username TradingView
  TV_PASSWORD      — password TradingView
  TELEGRAM_TOKEN   — bot token dari @BotFather
  TELEGRAM_CHAT_ID — chat ID kamu (dari @userinfobot)
"""

import os
import sys
import time
import logging
from datetime import datetime, timezone, timedelta

# ── Setup logging ──────────────────────────────────────────────────
logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s [%(levelname)s] %(message)s",
    datefmt = "%H:%M:%S"
)
log = logging.getLogger(__name__)

# ── Tambahkan parent dir ke path agar bisa import bei_pattern_scanner
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bei_pattern_scanner import (
    pre_filter, scan_dataframe, format_result, format_summary,
    WATCHLIST_T1, WATCHLIST_T2, WATCHLIST_T3, WATCHLIST_ALL,
    CONFIG,
)


# ═══════════════════════════════════════════════════════════════════
#  KONFIGURASI SCAN
# ═══════════════════════════════════════════════════════════════════

WIB = timezone(timedelta(hours=7))

SCAN_CONFIG = {
    # Watchlist yang digunakan
    # Opsi: WATCHLIST_T1, WATCHLIST_T2, WATCHLIST_ALL, atau custom list
    "watchlist":        WATCHLIST_ALL,

    # Filter sinyal yang dikirim ke Telegram
    "notify_strong":    True,   # kirim STRONG BUY
    "notify_buy":       False,   # kirim BUY
    "notify_watchlist": False,  # jangan kirim WATCHLIST (terlalu banyak)
    "notify_combo_t1":  False,   # selalu kirim jika ada Combo Tier 1

    # Filter universe (None = semua)
    # Opsi: "A_TRENDING", "B_OVERSOLD", "BOTH", None
    "universe_filter":  None,

    # Batas maksimum notifikasi individual (hindari spam)
    "max_individual_notify": 15,

    # Selalu kirim ringkasan harian meskipun tidak ada sinyal
    "always_send_summary": True,

    # Delay antar request tvdatafeed (detik)
    "tv_delay":         1.2,
    "tv_n_bars":        200,
}


# ═══════════════════════════════════════════════════════════════════
#  TELEGRAM HELPER
# ═══════════════════════════════════════════════════════════════════

def send_telegram(text: str, token: str, chat_id: str,
                  parse_mode: str = "HTML") -> bool:
    """Kirim pesan ke Telegram. Return True jika berhasil."""
    import urllib.request
    import urllib.parse
    import json

    url  = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id":    chat_id,
        "text":       text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": "true",
    }).encode()

    try:
        req  = urllib.request.Request(url, data=data, method="POST")
        resp = urllib.request.urlopen(req, timeout=15)
        result = json.loads(resp.read())
        return result.get("ok", False)
    except Exception as e:
        log.error(f"Telegram error: {e}")
        return False


def format_telegram_result(r) -> str:
    """Format ScanResult ke pesan Telegram yang rapi (HTML)."""
    tier_emoji = {1: "🔵", 2: "🟢", 3: "🟡"}.get(r.tier, "⚪")
    univ_map   = {
        "A_TRENDING": "📈 Trending",
        "B_OVERSOLD": "📉 Oversold",
        "BOTH":       "🔄 Both",
        "NEUTRAL":    "➡️ Neutral",
    }
    univ_label = univ_map.get(r.universe, r.universe)

    sig_emoji = "🟢" if "STRONG" in r.signal else "🟡" if "BUY" in r.signal else "⚪"

    # Pola aktif
    pola_lines = ""
    for pr in r.patterns:
        pola_lines += f"  ✅ <code>{pr.name}</code>\n"

    # Combo
    combo_lines = ""
    for c in r.combos:
        star = "⭐" if c['tier'] == 1 else "  "
        combo_lines += f"  {star} <b>{c['name']}</b> [{c['prob']}]\n"

    msg = (
        f"{sig_emoji} <b>{r.ticker}</b> | {r.date}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{tier_emoji} Tier {r.tier} | {univ_label}\n"
        f"💰 Close: <b>Rp {r.close:,.0f}</b>\n"
        f"📊 Volume: {r.volume:,.0f} lot ({r.vol_ratio:.1f}x avg)\n"
        f"💵 Likuiditas: {r.vol_idr_b:.1f}B IDR/hari\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🧭 Regime: <b>{r.regime}</b> | ADX: {r.adx:.1f}\n"
        f"📈 RSI: {r.rsi:.1f} | ATR: {r.atr:.2f}\n"
        f"📍 VWAP: {'di atas ✅' if r.above_vwap else 'di bawah ❌'}\n"
        f"🎯 Score: <b>{r.total_score}/~20</b> | Prob: <b>{r.prob_est}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 <b>Pola Aktif:</b>\n{pola_lines}"
    )
    if combo_lines:
        msg += f"\n🔥 <b>Kombinasi:</b>\n{combo_lines}"

    msg += f"\n⚠️ <i>Bukan rekomendasi investasi. Gunakan stop-loss.</i>"
    return msg


def format_telegram_summary(results: list, scan_meta: dict) -> str:
    """Format ringkasan harian untuk Telegram."""
    wib_now  = datetime.now(WIB).strftime("%d %b %Y %H:%M WIB")
    strong   = [r for r in results if "STRONG" in r.signal]
    buy      = [r for r in results if r.signal.startswith("🟡")]
    combo1   = [r for r in results if any(c['tier'] == 1 for c in r.combos)]
    univ_a   = [r for r in results if r.universe in ("A_TRENDING", "BOTH")]
    univ_b   = [r for r in results if r.universe in ("B_OVERSOLD", "BOTH")]

    msg = (
        f"📊 <b>SCAN BEI SELESAI</b>\n"
        f"🕐 {wib_now}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔍 Scan     : {scan_meta['total_scanned']} saham\n"
        f"✅ Lolos filter: {scan_meta['total_passed']} saham\n"
        f"⏱ Durasi   : {scan_meta['duration_sec']:.0f} detik\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 STRONG BUY  : {len(strong)} saham\n"
        f"🟡 BUY         : {len(buy)} saham\n"
        f"⭐ Combo Tier1 : {len(combo1)} saham\n"
        f"📈 Universe A  : {len(univ_a)} sinyal\n"
        f"📉 Universe B  : {len(univ_b)} sinyal\n"
    )

    if results:
        top = combo1[:8] if combo1 else strong[:8] if strong else results[:8]
        msg += f"\n━━━━━━━━━━━━━━━━━━━━━━\n🏆 <b>Top Picks:</b>\n"
        for r in top:
            sig_e  = "🟢" if "STRONG" in r.signal else "🟡"
            combo_p = r.combos[0]['prob'] if r.combos else ""
            t_e    = {1:"🔵",2:"🟢",3:"🟡"}.get(r.tier,"⚪")
            msg += (
                f"{sig_e} <b>{r.ticker}</b> {t_e}T{r.tier} "
                f"| Score:{r.total_score} | {r.prob_est} {combo_p}\n"
            )
    else:
        msg += f"\n━━━━━━━━━━━━━━━━━━━━━━\n⚪ Tidak ada sinyal hari ini.\n"

    msg += f"\n⚠️ <i>Bukan rekomendasi investasi.</i>"
    return msg


# ═══════════════════════════════════════════════════════════════════
#  TRADINGVIEW LOGIN
# ═══════════════════════════════════════════════════════════════════

def init_tvdatafeed():
    """Inisialisasi koneksi TradingView dari environment variables."""
    try:
        from tvDatafeed import TvDatafeed, Interval
        username = os.environ.get("TV_USERNAME", "")
        password = os.environ.get("TV_PASSWORD", "")

        if not username or not password:
            log.error("TV_USERNAME atau TV_PASSWORD tidak ditemukan di environment!")
            log.error("Pastikan GitHub Secrets sudah diset.")
            sys.exit(1)

        log.info(f"Login TradingView sebagai: {username}")
        tv = TvDatafeed(username=username, password=password)
        log.info("✅ Login TradingView berhasil")
        return tv, Interval

    except ImportError:
        log.error("tvDatafeed tidak terinstall!")
        log.error("Tambahkan 'tvdatafeed' ke requirements.txt")
        sys.exit(1)
    except Exception as e:
        log.error(f"Gagal login TradingView: {e}")
        sys.exit(1)


# ═══════════════════════════════════════════════════════════════════
#  MAIN SCANNER
# ═══════════════════════════════════════════════════════════════════

def main():
    start_time = time.time()
    wib_now    = datetime.now(WIB)

    log.info("=" * 60)
    log.info("BEI CONFLUENCE PATTERN SCANNER — Auto Run")
    log.info(f"Waktu WIB: {wib_now.strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    # ── Ambil env variables ─────────────────────────────────────────
    TG_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
    TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not TG_TOKEN or not TG_CHAT_ID:
        log.error("TELEGRAM_TOKEN atau TELEGRAM_CHAT_ID tidak ditemukan!")
        sys.exit(1)

    def tg(text):
        ok = send_telegram(text, TG_TOKEN, TG_CHAT_ID)
        if not ok:
            log.warning("Gagal kirim ke Telegram")
        return ok

    # ── Notifikasi mulai ────────────────────────────────────────────
    tg(
        f"🔍 <b>Scanner BEI mulai...</b>\n"
        f"🕐 {wib_now.strftime('%H:%M WIB')}\n"
        f"📋 Watchlist: {len(SCAN_CONFIG['watchlist'])} saham"
    )

    # ── Init TradingView ────────────────────────────────────────────
    tv, Interval = init_tvdatafeed()

    # ── Scan loop ───────────────────────────────────────────────────
    watchlist    = SCAN_CONFIG["watchlist"]
    total        = len(watchlist)
    results      = []
    skipped      = 0
    notified     = 0

    log.info(f"Mulai scan {total} saham...")

    for idx, ticker in enumerate(watchlist, 1):
        log.info(f"[{idx:3d}/{total}] {ticker:<10}", )

        # 1. Fetch data dari TradingView
        try:
            df = tv.get_hist(
                symbol   = ticker,
                exchange = CONFIG["tv_exchange"],
                interval = Interval.in_daily,
                n_bars   = SCAN_CONFIG["tv_n_bars"],
            )
            time.sleep(SCAN_CONFIG["tv_delay"])
        except Exception as e:
            log.warning(f"  ⚠ Fetch error {ticker}: {e}")
            skipped += 1
            continue

        if df is None or len(df) < 60:
            skipped += 1
            continue

        # 2. Pre-filter likuiditas + universe
        fr = pre_filter(df, ticker)
        if not fr.passed:
            log.info(f"  ⏭ {ticker}: {fr.reason}")
            skipped += 1
            continue

        log.info(f"  ✅ Lolos filter | Tier {fr.tier} | {fr.universe} | {fr.vol_idr/1e9:.1f}B IDR")

        # 3. Scan 10 pola
        r = scan_dataframe(ticker, df, filter_result=fr)
        if r is None:
            continue

        # 4. Filter universe jika ada setting
        if SCAN_CONFIG["universe_filter"]:
            if r.universe not in (SCAN_CONFIG["universe_filter"], "BOTH"):
                continue

        # 5. Tentukan apakah perlu notifikasi
        has_combo_t1  = any(c['tier'] == 1 for c in r.combos)
        is_strong     = "STRONG" in r.signal
        is_buy        = r.signal.startswith("🟡")
        is_watchlist  = r.signal.startswith("⚪")
        is_skip       = "SKIP" in r.signal or "NO SIGNAL" in r.signal

        if is_skip:
            continue

        results.append(r)
        log.info(f"  🎯 {ticker}: {r.signal} | Score: {r.total_score} | {r.prob_est}")

        # 6. Kirim notifikasi individual (dengan batas max)
        should_notify = (
            (is_strong   and SCAN_CONFIG["notify_strong"]) or
            (is_buy      and SCAN_CONFIG["notify_buy"]) or
            (is_watchlist and SCAN_CONFIG["notify_watchlist"]) or
            (has_combo_t1 and SCAN_CONFIG["notify_combo_t1"])
        )

        if should_notify and notified < SCAN_CONFIG["max_individual_notify"]:
            msg = format_telegram_result(r)
            if tg(msg):
                notified += 1
                log.info(f"  📨 Notifikasi terkirim ({notified})")
            time.sleep(0.5)  # rate limit Telegram

    # ── Selesai scan ────────────────────────────────────────────────
    duration = time.time() - start_time
    total_passed = total - skipped

    log.info("=" * 60)
    log.info(f"Scan selesai: {len(results)} sinyal dari {total_passed} saham valid")
    log.info(f"Durasi: {duration:.1f} detik")
    log.info("=" * 60)

    # ── Sort hasil ──────────────────────────────────────────────────
    results.sort(key=lambda r: (
        r.tier,
        -sum(1 for c in r.combos if c['tier'] == 1),
        -r.total_score
    ))

    # ── Kirim ringkasan harian ──────────────────────────────────────
    scan_meta = {
        "total_scanned": total,
        "total_passed":  total_passed,
        "duration_sec":  duration,
    }

    if results or SCAN_CONFIG["always_send_summary"]:
        summary = format_telegram_summary(results, scan_meta)
        tg(summary)
        log.info("📊 Ringkasan harian terkirim ke Telegram")

    # ── Print ke log (untuk GitHub Actions artifacts) ───────────────
    print(format_summary(results))

    # Return code: 0 = sukses
    return 0


if __name__ == "__main__":
    sys.exit(main())
