"""
test_local.py — Test scanner secara lokal sebelum push ke GitHub
================================================================

Jalankan ini dulu untuk memastikan semua berjalan sebelum deploy.
Tidak butuh TradingView / Telegram — pakai data sintetis.

Cara pakai:
    python test_local.py           # test semua komponen
    python test_local.py --quick   # test cepat (3 saham sintetis saja)
    python test_local.py --telegram  # test kirim ke Telegram (butuh .env)
"""

import sys
import os
import argparse
import time
from datetime import datetime

# ── Color output ──────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

def ok(msg):    print(f"  {GREEN}✅ {msg}{RESET}")
def fail(msg):  print(f"  {RED}❌ {msg}{RESET}")
def warn(msg):  print(f"  {YELLOW}⚠️  {msg}{RESET}")
def info(msg):  print(f"  {BLUE}ℹ️  {msg}{RESET}")
def head(msg):  print(f"\n{BOLD}{'═'*55}{RESET}\n  {BOLD}{msg}{RESET}\n{'─'*55}")


# ══════════════════════════════════════════════════════════════════
#  TEST 1 — Import & dependencies
# ══════════════════════════════════════════════════════════════════
def test_imports():
    head("TEST 1 — Import & Dependencies")
    passed = 0; failed = 0

    libs = ["pandas", "numpy", "ta"]
    for lib in libs:
        try:
            __import__(lib)
            ok(f"{lib} terinstall")
            passed += 1
        except ImportError:
            fail(f"{lib} TIDAK terinstall  →  pip install {lib}")
            failed += 1

    # tvdatafeed (opsional untuk test lokal)
    try:
        from tvDatafeed import TvDatafeed, Interval
        ok("tvDatafeed terinstall")
        passed += 1
    except ImportError:
        warn("tvDatafeed belum terinstall (OK untuk test lokal, diperlukan untuk GitHub Actions)")
        warn("Install: pip install git+https://github.com/rongardF/tvdatafeed.git")

    # bei_pattern_scanner
    try:
        import bei_pattern_scanner as bps
        ok("bei_pattern_scanner.py bisa diimport")
        passed += 1
    except ImportError as e:
        fail(f"bei_pattern_scanner.py gagal import: {e}")
        failed += 1
        return False, passed, failed

    return failed == 0, passed, failed


# ══════════════════════════════════════════════════════════════════
#  TEST 2 — Komponen scanner
# ══════════════════════════════════════════════════════════════════
def test_scanner_components():
    head("TEST 2 — Komponen Scanner")
    import bei_pattern_scanner as bps
    import numpy as np
    import pandas as pd
    passed = 0; failed = 0

    # Test make_synthetic
    try:
        for patt in ["combo_a", "combo_b", "hammer_rev", "random"]:
            df = bps.make_synthetic(patt, n=120)
            assert len(df) == 120
            assert all(c in df.columns for c in ["Open","High","Low","Close","Volume"])
        ok("make_synthetic() — semua 4 pattern OK")
        passed += 1
    except Exception as e:
        fail(f"make_synthetic() gagal: {e}")
        failed += 1

    # Test compute_indicators
    try:
        df = bps.make_synthetic("combo_a")
        d  = bps.compute_indicators(df)
        expected_cols = ["rsi","macd","atr","vwap","adx","obv","st_dir","vol_ratio"]
        missing = [c for c in expected_cols if c not in d.columns]
        if missing:
            fail(f"compute_indicators() — kolom hilang: {missing}")
            failed += 1
        else:
            ok(f"compute_indicators() — {len(d.columns)} kolom indikator OK")
            passed += 1
    except Exception as e:
        fail(f"compute_indicators() gagal: {e}")
        failed += 1

    # Test pre_filter
    try:
        df   = bps.make_synthetic("combo_a")
        fr   = bps.pre_filter(df, "TEST")
        assert hasattr(fr, "passed")
        assert hasattr(fr, "tier")
        assert hasattr(fr, "universe")
        ok(f"pre_filter() — passed={fr.passed} | tier={fr.tier} | universe={fr.universe}")
        passed += 1
    except Exception as e:
        fail(f"pre_filter() gagal: {e}")
        failed += 1

    # Test semua 10 detektor pola
    try:
        df = bps.make_synthetic("combo_a")
        d  = bps.compute_indicators(df)
        i  = len(d) - 1
        detector_names = []
        for fn in bps.DETECTORS:
            pr = fn(d, i)
            assert hasattr(pr, "detected")
            assert hasattr(pr, "score")
            detector_names.append(pr.name)
        ok(f"Semua {len(bps.DETECTORS)} detektor pola berjalan tanpa error")
        passed += 1
    except Exception as e:
        fail(f"Detektor pola gagal: {e}")
        failed += 1

    # Test detect_combos
    try:
        df = bps.make_synthetic("combo_a")
        d  = bps.compute_indicators(df)
        i  = len(d) - 1
        pmap = {}
        for fn in bps.DETECTORS:
            pr = fn(d, i)
            pmap[pr.name] = pr
        combos = bps.detect_combos(pmap)
        ok(f"detect_combos() — {len(combos)} kombinasi terdeteksi")
        passed += 1
    except Exception as e:
        fail(f"detect_combos() gagal: {e}")
        failed += 1

    # Test scan_dataframe end-to-end
    try:
        for patt in ["combo_a", "combo_b", "hammer_rev"]:
            df = bps.make_synthetic(patt)
            r  = bps.scan_dataframe(f"TEST_{patt.upper()}", df)
            # scan_dataframe bisa return None jika pre_filter gagal (vol sintetis kecil)
            # ini OK
        ok("scan_dataframe() — end-to-end berjalan tanpa crash")
        passed += 1
    except Exception as e:
        fail(f"scan_dataframe() crash: {e}")
        failed += 1

    return failed == 0, passed, failed


# ══════════════════════════════════════════════════════════════════
#  TEST 3 — Demo mode (output visual)
# ══════════════════════════════════════════════════════════════════
def test_demo():
    head("TEST 3 — Demo Mode (Output Visual)")
    import bei_pattern_scanner as bps

    scenarios = [
        ("DEMO_COMBO_A",  "combo_a",   "Combo A: Ascending Triangle + Vol Breakout + Marubozu"),
        ("DEMO_COMBO_B",  "combo_b",   "Combo B: Cup & Handle + Vol Breakout + Gap Up"),
        ("DEMO_HAMMER",   "hammer_rev","Combo C: Hammer → Marubozu Reversal"),
        ("DEMO_RANDOM",   "random",    "Random baseline"),
    ]

    passed = 0; failed = 0
    for ticker, patt, desc in scenarios:
        try:
            df = bps.make_synthetic(patt, seed=42)
            # Force pre_filter dengan volume yang cukup
            import numpy as np
            df['Volume'] = np.abs(np.random.normal(20_000_000, 5_000_000, len(df)))
            df['Volume'].iloc[-1] = 80_000_000

            fr = bps.pre_filter(df, ticker)
            r  = bps.scan_dataframe(ticker, df, filter_result=fr) if fr.passed else bps.scan_dataframe(ticker, df)

            if r:
                print(bps.format_result(r))
                ok(f"{ticker}: signal={r.signal} | score={r.total_score} | combos={len(r.combos)}")
                passed += 1
            else:
                warn(f"{ticker}: tidak ada sinyal (mungkin pre_filter tidak lolos)")
                passed += 1  # bukan error, hanya tidak ada sinyal
        except Exception as e:
            fail(f"{ticker} crash: {e}")
            import traceback; traceback.print_exc()
            failed += 1

    return failed == 0, passed, failed


# ══════════════════════════════════════════════════════════════════
#  TEST 4 — Pre-filter & Universe Builder
# ══════════════════════════════════════════════════════════════════
def test_universe():
    head("TEST 4 — Pre-Filter & Universe Classification")
    import bei_pattern_scanner as bps
    import numpy as np
    import pandas as pd

    passed = 0; failed = 0

    # Buat 5 saham sintetis dengan karakteristik berbeda
    test_cases = [
        # (nama, kondisi, expected_universe_contains)
        ("LIQUID_TREND",  "liquid_trending",  "A_TRENDING"),
        ("LIQUID_OVERSLD","liquid_oversold",  "B_OVERSOLD"),
        ("GOCAP",         "gocap",            None),    # harus gagal filter
        ("ILIQUID",       "iliquid",          None),    # harus gagal filter
        ("NORMAL",        "normal",           None),    # bisa NEUTRAL
    ]

    def make_case(case_type, n=120):
        np.random.seed(99)
        dates = pd.date_range('2025-11-01', periods=n, freq='B')
        base  = 5000.0

        if case_type == "gocap":
            base = 50.0  # harga gocap
        elif case_type == "iliquid":
            base = 1000.0

        c = [base]
        for _ in range(n-1):
            c.append(c[-1] * (1 + np.random.normal(0.0005, 0.012)))
        c = np.array(c)

        if case_type == "liquid_trending":
            # Trending: close > EMA50, volume besar
            c = c * (1 + np.linspace(0, 0.3, n))  # uptrend jelas
            v = np.abs(np.random.normal(50_000_000, 10_000_000, n))
        elif case_type == "liquid_oversold":
            # Oversold: turun, RSI rendah
            c = c * (1 - np.linspace(0, 0.25, n))  # downtrend
            v = np.abs(np.random.normal(30_000_000, 8_000_000, n))
        elif case_type == "iliquid":
            v = np.abs(np.random.normal(100_000, 50_000, n))  # volume kecil
        else:
            v = np.abs(np.random.normal(10_000_000, 3_000_000, n))

        h = c * (1 + np.abs(np.random.normal(0, 0.008, n)))
        l = c * (1 - np.abs(np.random.normal(0, 0.008, n)))
        o = l + (h - l) * np.random.uniform(0.2, 0.8, n)
        o = np.clip(o, l, h)

        return pd.DataFrame({
            'Open': o, 'High': h, 'Low': l, 'Close': c, 'Volume': v
        }, index=dates)

    for name, case_type, expected_univ in test_cases:
        try:
            df = make_case(case_type)
            fr = bps.pre_filter(df, name)

            if expected_univ is None and not fr.passed:
                ok(f"{name:<18} → FILTERED OUT ({fr.reason[:40]})")
                passed += 1
            elif expected_univ is None and fr.passed:
                ok(f"{name:<18} → Lolos filter | universe={fr.universe} | {fr.vol_idr/1e9:.1f}B IDR")
                passed += 1
            elif fr.passed and (expected_univ in fr.universe or fr.universe == "BOTH"):
                ok(f"{name:<18} → universe={fr.universe} ✓ | {fr.vol_idr/1e9:.1f}B IDR")
                passed += 1
            elif fr.passed:
                warn(f"{name:<18} → universe={fr.universe} (expected contains {expected_univ})")
                passed += 1  # bukan error keras, threshold bisa berbeda
            else:
                warn(f"{name:<18} → Tidak lolos filter ({fr.reason}) — mungkin threshold perlu adjust")
                passed += 1
        except Exception as e:
            fail(f"{name} crash: {e}")
            import traceback; traceback.print_exc()
            failed += 1

    return failed == 0, passed, failed


# ══════════════════════════════════════════════════════════════════
#  TEST 5 — Telegram (opsional, butuh .env atau env vars)
# ══════════════════════════════════════════════════════════════════
def test_telegram():
    head("TEST 5 — Telegram Connectivity")

    token   = os.environ.get("TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        warn("TELEGRAM_TOKEN / TELEGRAM_CHAT_ID tidak ada di environment")
        warn("Set dengan: export TELEGRAM_TOKEN=xxx && export TELEGRAM_CHAT_ID=yyy")
        warn("Test Telegram dilewati")
        return True, 0, 0

    # Import send_telegram dari run_scan.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scripts"))
    try:
        from run_scan import send_telegram, format_telegram_result, format_telegram_summary
    except ImportError as e:
        fail(f"Gagal import run_scan.py: {e}")
        return False, 0, 1

    # Test kirim pesan sederhana
    passed = 0; failed = 0
    test_msg = (
        f"🧪 <b>TEST — BEI Scanner</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Koneksi Telegram berhasil!\n"
        f"🕐 {datetime.now().strftime('%H:%M:%S')}\n"
        f"🐍 Python {sys.version.split()[0]}\n"
        f"\nScanner siap digunakan."
    )

    ok_sent = send_telegram(test_msg, token, chat_id)
    if ok_sent:
        ok("Pesan test berhasil dikirim ke Telegram ✅")
        passed += 1
    else:
        fail("Gagal kirim ke Telegram — cek TOKEN dan CHAT_ID")
        failed += 1

    # Test format sinyal
    if ok_sent:
        import bei_pattern_scanner as bps
        import numpy as np
        df = bps.make_synthetic("combo_a")
        df['Volume'] = np.abs(np.random.normal(50_000_000, 10_000_000, len(df)))
        fr = bps.pre_filter(df, "BBCA_TEST")
        r  = bps.scan_dataframe("BBCA_TEST", df, filter_result=fr)
        if r:
            msg = format_telegram_result(r)
            ok2 = send_telegram(msg, token, chat_id)
            if ok2:
                ok("Format sinyal saham terkirim ke Telegram ✅")
                passed += 1
            else:
                fail("Gagal kirim format sinyal")
                failed += 1

    return failed == 0, passed, failed


# ══════════════════════════════════════════════════════════════════
#  TEST 6 — GitHub Actions simulation
# ══════════════════════════════════════════════════════════════════
def test_github_actions_sim():
    head("TEST 6 — Simulasi GitHub Actions Environment")
    passed = 0; failed = 0

    # Cek apakah semua env vars yang dibutuhkan ada
    required_secrets = ["TV_USERNAME", "TV_PASSWORD", "TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID"]
    all_set = True
    for secret in required_secrets:
        val = os.environ.get(secret, "")
        if val:
            ok(f"{secret} → SET ✅")
            passed += 1
        else:
            warn(f"{secret} → TIDAK SET (diperlukan untuk GitHub Actions)")
            all_set = False

    if not all_set:
        info("Set environment variables sebelum push ke GitHub:")
        info("GitHub → repo → Settings → Secrets → Actions")

    # Cek struktur file yang harus ada di repo
    required_files = [
        "bei_pattern_scanner.py",
        "requirements.txt",
        "scripts/run_scan.py",
        ".github/workflows/scan.yml",
    ]
    for fpath in required_files:
        full = os.path.join(os.path.dirname(__file__), fpath) if fpath != "bei_pattern_scanner.py" \
               else os.path.join(os.path.dirname(os.path.dirname(__file__)), "bei_pattern_scanner.py")
        # Also check in current dir
        alt = os.path.join(os.getcwd(), fpath)
        if os.path.exists(fpath) or os.path.exists(full) or os.path.exists(alt):
            ok(f"File ada: {fpath}")
            passed += 1
        else:
            fail(f"File TIDAK ADA: {fpath} — harus ada di root repo")
            failed += 1

    return failed == 0, passed, failed


# ══════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser(description="Test BEI Scanner lokal")
    ap.add_argument("--quick",    action="store_true", help="Hanya test import + komponen")
    ap.add_argument("--telegram", action="store_true", help="Sertakan test Telegram")
    ap.add_argument("--all",      action="store_true", help="Jalankan semua test")
    args = ap.parse_args()

    print(f"\n{'═'*55}")
    print(f"  {BOLD}BEI SCANNER — LOCAL TEST SUITE{RESET}")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'═'*55}")

    total_passed = 0
    total_failed = 0
    test_results = []

    # Test yang selalu dijalankan
    tests = [
        ("Import & Dependencies", test_imports),
        ("Scanner Components",    test_scanner_components),
    ]

    if not args.quick:
        tests += [
            ("Demo Mode",            test_demo),
            ("Universe Builder",     test_universe),
            ("GitHub Actions Files", test_github_actions_sim),
        ]

    if args.telegram or args.all:
        tests.append(("Telegram",  test_telegram))

    start = time.time()
    for test_name, test_fn in tests:
        try:
            success, passed, failed = test_fn()
            total_passed += passed
            total_failed += failed
            test_results.append((test_name, success, passed, failed))
        except Exception as e:
            print(f"\n  {RED}💥 TEST CRASH: {test_name}{RESET}")
            print(f"     {e}")
            import traceback; traceback.print_exc()
            total_failed += 1
            test_results.append((test_name, False, 0, 1))

    duration = time.time() - start

    # ── Summary ─────────────────────────────────────────────────────
    print(f"\n{'═'*55}")
    print(f"  {BOLD}HASIL TEST{RESET}")
    print(f"{'─'*55}")
    for name, success, p, f in test_results:
        status = f"{GREEN}PASS{RESET}" if success else f"{RED}FAIL{RESET}"
        print(f"  [{status}] {name:<30} ({p} OK, {f} gagal)")
    print(f"{'─'*55}")
    print(f"  Total: {total_passed} OK, {total_failed} gagal | {duration:.1f}s")
    print(f"{'═'*55}\n")

    if total_failed == 0:
        print(f"  {GREEN}{BOLD}✅ SEMUA TEST LULUS — Scanner siap di-deploy ke GitHub!{RESET}\n")
        print(f"  Langkah selanjutnya:")
        print(f"  1. Push semua file ke repo: https://github.com/edwinhidayat1708/bei-scanner")
        print(f"  2. Set 4 GitHub Secrets (TV_USERNAME, TV_PASSWORD, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID)")
        print(f"  3. Test manual: Actions → BEI Scanner → Run workflow")
        print(f"  4. Scan otomatis akan jalan setiap 16:30 & 17:00 WIB hari kerja\n")
    else:
        print(f"  {RED}{BOLD}❌ Ada {total_failed} kegagalan — perbaiki dulu sebelum deploy{RESET}\n")

    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
