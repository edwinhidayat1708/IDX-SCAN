# 🤖 BEI Confluence Pattern Scanner — Setup Guide Lengkap

**Goal:** Scan otomatis 300+ saham BEI setiap hari, deteksi 10 pola teknikal,
kirim notifikasi Telegram. Semua gratis, jalan di cloud (GitHub Actions).

---

## 📁 Struktur File Proyek

```
bei-scanner/                      ← folder repo GitHub kamu
├── .github/
│   └── workflows/
│       └── scan.yml              ← jadwal otomatis GitHub Actions
├── scripts/
│   └── run_scan.py               ← script utama yang dijalankan
├── bei_pattern_scanner.py        ← engine scanner (10 pola + pre-filter)
├── requirements.txt              ← daftar library Python
└── README.md                     ← (opsional)
```

---

## STEP 1 — Buat Telegram Bot

### 1.1 Buat bot baru
1. Buka Telegram, cari `@BotFather`
2. Kirim `/newbot`
3. Masukkan nama bot, contoh: `BEI Scanner Bot`
4. Masukkan username bot (harus diakhiri `bot`), contoh: `bei_scanner_123_bot`
5. BotFather akan membalas dengan **token** seperti:
   ```
   7123456789:AAHdqTcvCH1vGWJxfSeofSs0K95iq4tQNnk
   ```
6. **Simpan token ini** — ini adalah `TELEGRAM_TOKEN`

### 1.2 Dapatkan Chat ID kamu
1. Cari `@userinfobot` di Telegram
2. Kirim `/start`
3. Bot akan membalas dengan info kamu, termasuk `Id: 123456789`
4. **Simpan angka ID ini** — ini adalah `TELEGRAM_CHAT_ID`

### 1.3 Aktifkan bot
1. Cari bot yang baru kamu buat di Telegram (username yang kamu pilih tadi)
2. Klik **START** atau kirim `/start`
3. Test: buka browser, kunjungi URL ini (ganti TOKEN dan CHAT_ID):
   ```
   https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<CHAT_ID>&text=Test+berhasil
   ```
4. Jika berhasil, kamu akan menerima pesan "Test berhasil" di Telegram

---

## STEP 2 — Buat Repository GitHub

### 2.1 Buat repo baru
1. Buka [github.com/new](https://github.com/new)
2. Repository name: `bei-scanner` (atau nama lain)
3. **Visibility: Public** ← PENTING untuk GitHub Actions gratis unlimited
   > Private repo hanya dapat 2.000 menit/bulan gratis.
   > Public repo GRATIS tanpa batas.
   > ⚠️ Jika repo Public, JANGAN taruh password/token langsung di kode!
   > Gunakan GitHub Secrets (akan disetup di Step 3).
4. Centang "Add a README file"
5. Klik **Create repository**

### 2.2 Upload file ke repo

**Cara A — Via GitHub web (lebih mudah):**

1. Di halaman repo, klik **Add file → Upload files**
2. Upload file-file ini satu per satu atau drag & drop:
   - `bei_pattern_scanner.py`
   - `requirements.txt`
3. Untuk file di dalam folder, klik **Add file → Create new file**,
   ketik path lengkap di kotak nama file: `.github/workflows/scan.yml`
   lalu paste isi filenya
4. Lakukan hal yang sama untuk `scripts/run_scan.py`

**Cara B — Via Git (lebih cepat jika sudah familiar):**

```bash
# Clone repo
git clone https://github.com/USERNAME_KAMU/bei-scanner.git
cd bei-scanner

# Copy semua file dari project ini ke dalam folder
# (salin bei_pattern_scanner.py, requirements.txt, .github/, scripts/)

# Push ke GitHub
git add .
git commit -m "Initial setup BEI Pattern Scanner"
git push origin main
```

---

## STEP 3 — Setup GitHub Secrets

> **Kenapa Secrets?** Secrets tersimpan terenkripsi di GitHub dan tidak
> pernah muncul di log atau kode. Aman meski repo Public.

1. Buka repo di GitHub
2. Klik tab **Settings**
3. Di sidebar kiri, klik **Secrets and variables → Actions**
4. Klik **New repository secret** untuk setiap secret berikut:

| Secret Name | Nilai | Contoh |
|---|---|---|
| `TV_USERNAME` | Username TradingView kamu | `edwinhidayat1708` |
| `TV_PASSWORD` | Password TradingView kamu | `passwordkamu123` |
| `TELEGRAM_TOKEN` | Token dari @BotFather | `7123456789:AAHd...` |
| `TELEGRAM_CHAT_ID` | ID dari @userinfobot | `123456789` |

> **Catatan:** Jika TradingView kamu pakai login Google/Facebook,
> buat password tersendiri di Settings → Security → Password di TradingView.

---

## STEP 4 — Verifikasi Workflow

### 4.1 Cek file scan.yml

Pastikan file `.github/workflows/scan.yml` sudah ada di repo.
Buka tab **Actions** di repo — jika tampil "BEI Scanner", berarti workflow sudah terbaca.

### 4.2 Test manual (Run Now)

1. Buka tab **Actions**
2. Klik **BEI Scanner** di sidebar kiri
3. Klik **Run workflow**
4. Pilih branch `main`, klik **Run workflow** (hijau)
5. Tunggu 1-2 menit, klik run yang muncul untuk lihat log real-time
6. Jika berhasil, kamu akan menerima notifikasi di Telegram

### 4.3 Troubleshooting jika gagal

**Error: `TV_USERNAME atau TV_PASSWORD tidak ditemukan`**
→ Secrets belum diset. Ulangi Step 3.

**Error: `tvDatafeed tidak terinstall`**
→ Cek `requirements.txt`, pastikan ada baris tvdatafeed.

**Error: `Login TradingView gagal`**
→ Username/password salah. Cek di TradingView web apakah bisa login.
→ Jika pakai 2FA, matikan dulu atau gunakan session cookie (lihat catatan).

**Telegram tidak menerima pesan**
→ Pastikan sudah klik START di bot Telegram kamu.
→ Cek TELEGRAM_TOKEN dan TELEGRAM_CHAT_ID sudah benar.

---

## STEP 5 — Jadwal Otomatis

File `scan.yml` sudah dikonfigurasi untuk jalan otomatis:

```
Senin - Jumat:
  16:30 WIB  → Scan pertama (setelah pre-closing)
  17:00 WIB  → Scan kedua (setelah market tutup resmi)
```

> **Catatan:** GitHub Actions scheduler bisa terlambat 5-15 menit
> di jam sibuk. Ini normal dan tidak bisa dikontrol.

Untuk mengubah jadwal, edit bagian `cron` di `scan.yml`:

```yaml
# Format: menit jam hari-bulan bulan hari-minggu
# Ingat: timezone GitHub adalah UTC, WIB = UTC+7

# 16:00 WIB = 09:00 UTC
- cron: '0 9 * * 1-5'

# 17:30 WIB = 10:30 UTC
- cron: '30 10 * * 1-5'
```

---

## STEP 6 — Kustomisasi Lanjutan

### 6.1 Ubah watchlist

Edit bagian `SCAN_CONFIG` di `scripts/run_scan.py`:

```python
SCAN_CONFIG = {
    # Pilihan watchlist:
    "watchlist": WATCHLIST_T1,    # Hanya blue chip (53 saham, lebih cepat)
    "watchlist": WATCHLIST_ALL,   # Semua 285 saham (lebih lengkap)

    # Atau buat custom watchlist:
    "watchlist": ["BBCA","BMRI","TLKM","ADRO","GOTO"],
}
```

### 6.2 Ubah filter notifikasi

```python
SCAN_CONFIG = {
    "notify_strong":    True,   # Kirim STRONG BUY
    "notify_buy":       True,   # Kirim BUY
    "notify_watchlist": False,  # Jangan kirim WATCHLIST (terlalu banyak)
    "notify_combo_t1":  True,   # Selalu kirim Combo Tier 1

    # Batas notifikasi individual per run (hindari spam)
    "max_individual_notify": 15,
}
```

### 6.3 Filter hanya Universe Trending atau Oversold

```python
SCAN_CONFIG = {
    # Hanya kirim sinyal dari emiten yang sedang uptrend
    "universe_filter": "A_TRENDING",

    # Hanya kirim sinyal dari emiten oversold (reversal play)
    "universe_filter": "B_OVERSOLD",

    # Semua universe (default)
    "universe_filter": None,
}
```

### 6.4 Ubah threshold likuiditas

Edit `CONFIG` di `bei_pattern_scanner.py`:

```python
CONFIG = {
    # Naikkan threshold jika terlalu banyak sinyal dari saham kecil
    "min_vol_idr":   1_000_000_000,  # Naik ke 1 miliar IDR/hari

    # Atau turunkan untuk tangkap lebih banyak saham
    "min_vol_idr":   300_000_000,    # Turun ke 300 juta IDR/hari
}
```

---

## 📊 Contoh Notifikasi Telegram

**Notifikasi individual (per saham):**
```
🟢 BBCA | 2026-04-26
━━━━━━━━━━━━━━━━━━━━━━
🔵 Tier 1 | 📈 Trending
💰 Close: Rp 9,450
📊 Volume: 45,320,000 lot (3.2x avg)
💵 Likuiditas: 428B IDR/hari
━━━━━━━━━━━━━━━━━━━━━━
🧭 Regime: TRENDING | ADX: 32.5
📈 RSI: 58.3 | ATR: 125.00
📍 VWAP: di atas ✅
🎯 Score: 14/~20 | Prob: >80%
━━━━━━━━━━━━━━━━━━━━━━
📌 Pola Aktif:
  ✅ #3 Ascending Triangle
  ✅ #1 Vol Breakout Konsolidasi
  ✅ #5 Bullish Marubozu

🔥 Kombinasi:
  ⭐ COMBO A Ascending Triangle + Vol Breakout + Marubozu [85-90%]

⚠️ Bukan rekomendasi investasi. Gunakan stop-loss.
```

**Ringkasan harian:**
```
📊 SCAN BEI SELESAI
🕐 26 Apr 2026 17:03 WIB
━━━━━━━━━━━━━━━━━━━━━━
🔍 Scan     : 285 saham
✅ Lolos filter: 198 saham
⏱ Durasi   : 487 detik
━━━━━━━━━━━━━━━━━━━━━━
🟢 STRONG BUY  : 3 saham
🟡 BUY         : 11 saham
⭐ Combo Tier1 : 2 saham
📈 Universe A  : 9 sinyal
📉 Universe B  : 5 sinyal

━━━━━━━━━━━━━━━━━━━━━━
🏆 Top Picks:
🟢 BBCA 🔵T1 | Score:14 | >80% [85-90%]
🟢 ADRO 🟢T2 | Score:12 | >80% [88-93%]
🟡 TLKM 🔵T1 | Score:8  | 65-79%
```

---

## ⚡ Estimasi Performa

| Watchlist | Saham | Durasi | GitHub Actions |
|---|---|---|---|
| WATCHLIST_T1 | 53 saham | ~2 menit | Aman |
| WATCHLIST_T2 tambah | ~180 saham | ~5 menit | Aman |
| WATCHLIST_ALL | 285 saham | ~8-10 menit | Aman |
| **Per bulan (2x/hari, 22 hari kerja)** | — | **~400 menit** | **Gratis** ✅ |

---

## 🔒 Catatan Keamanan

1. **Jangan pernah** taruh password/token langsung di kode
2. **Selalu** gunakan GitHub Secrets untuk credential
3. Repo Public = kode kelihatan, tapi Secrets tidak
4. TradingView ToS: tvdatafeed adalah tool third-party, gunakan dengan delay
   yang wajar (sudah dikonfigurasi 1.2 detik antar request)
5. Telegram Bot Token = akses penuh ke bot kamu, jaga jangan sampai bocor

---

## 🆘 Support & Debugging

**Lihat log scan:**
1. GitHub → repo → tab Actions
2. Klik run terakhir
3. Klik job "Scan Saham BEI"
4. Log akan tampil real-time

**Download artifact log:**
1. Di halaman run, scroll ke bawah
2. Klik "scan-log-XXX" untuk download

**Tes scanner lokal (tanpa GitHub):**
```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export TV_USERNAME="username_kamu"
export TV_PASSWORD="password_kamu"
export TELEGRAM_TOKEN="token_kamu"
export TELEGRAM_CHAT_ID="chat_id_kamu"

# Jalankan
python scripts/run_scan.py
```

---

*Dibuat untuk: edwinhidayat1708 | Repo: bei-scanner*
*⚠️ Bukan rekomendasi investasi. Selalu gunakan risk management.*
