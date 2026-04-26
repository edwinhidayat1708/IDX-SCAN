# 📊 BEI Confluence Pattern Scanner

Otomasi scan saham BEI — 10 pola teknikal, jalan di GitHub Actions, notifikasi Telegram.

## Fitur
- **10 pola teknikal** daily candle (Volume Breakout, Ascending Triangle, Cup & Handle, dll)
- **Kombinasi Combo A–E** dengan probabilitas 74–93%
- **Pre-filter likuiditas** — hanya saham yang layak (vol IDR, harga, frekuensi)
- **Universe classification** — A (Trending) vs B (Oversold)
- **Otomatis** via GitHub Actions, 2x sehari setelah market tutup
- **Notifikasi Telegram** — individual + ringkasan harian

## Setup
Lihat **[SETUP_GUIDE.md](SETUP_GUIDE.md)** untuk panduan lengkap step-by-step.

## Struktur
```
bei-scanner/
├── .github/workflows/scan.yml   # Jadwal GitHub Actions
├── scripts/run_scan.py          # Entry point otomasi
├── bei_pattern_scanner.py       # Engine: 10 pola + pre-filter + universe
├── requirements.txt             # Dependencies Python
└── SETUP_GUIDE.md               # Panduan setup lengkap
```

## Jadwal Otomatis
| Waktu WIB | Keterangan |
|---|---|
| 16:30 WIB | Scan pertama (pre-closing) |
| 17:00 WIB | Scan kedua (setelah market tutup) |

> ⚠️ Bukan rekomendasi investasi. Selalu gunakan stop-loss dan manajemen risiko.
