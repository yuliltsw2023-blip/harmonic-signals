# harmonic-signals

Scanner harmonic pattern (Bat, Gartley, Crab, Deep Crab, Butterfly, Cypher)
untuk 28 pair forex di H4 + D1. Deteksi mekanis di Python, grading oleh Claude
memakai rubric skill `harmonic-pattern-trading`, kirim ke Telegram, dedup di
Upstash Redis, jalan di GitHub Actions cron. Total biaya ≈ Claude API saja.

Sesuai `harmonic-signals-system-spec-addendum-freeteir.md` (free tier:
Twelve Data + GitHub Actions + Upstash).

> ⚠️ Output adalah analisis edukatif + grade, bukan sinyal buy/sell dan tidak
> ada auto-entry. Keputusan trading sepenuhnya tanggung jawab user.

## Arsitektur

```
Twelve Data (OHLC, 200 bar)
   └─ lib/pivots.py      fractal 3/3 + zigzag (filter leg < 1×ATR)
   └─ lib/harmonics.py   XABCD terakhir → match katalog (toleransi 5%)
   └─ lib/prz.py         PRZ = Fib level yang converge dalam band 0.5%
   └─ lib/grading.py     SL (beyond X +5% XA), TP 0.382/0.618/1.0 AD, R:R,
                         pre-grade (filter murah), HTF alignment, rule grade
   └─ lib/state.py       dedup Upstash (fallback in-memory)
   └─ lib/claude_grader.py  Claude → JSON {grade, reasoning, entry_model,...}
   └─ lib/chart_img.py   chart TradingView asli via chart-img.com: layout user (indikator
                         Pine Harmonic XABCD) kalau CHART_IMG_LAYOUT_ID ada, else drawings
   └─ lib/chart.py       fallback PNG matplotlib: candlestick + XABCD + PRZ + SL/TP
   └─ lib/telegram.py    sendPhoto (chart + caption) lalu sendMessage detail MDB-style
lib/scanner.py = orchestrator; scripts/scan_h4.py & scan_d1.py = entry point.
```

Alur per pair: fetch → pivot → struktur XABC(D) terbaru → match → PRZ →
level → **pre-grade** → **dedup** → HTF fetch (lazy) → **Claude grade** →
kirim kalau Grade A/B.

## Setup lokal

```bash
pip install -r requirements.txt pytest
cp .env.example .env      # isi key
python -m pytest -q       # 21 test, tanpa network
```

Test manual (butuh key di `.env`):

```bash
python scripts/manual/test_twelvedata.py EUR/USD 4h   # Fase 1: fetch + rate limit
python scripts/manual/test_telegram.py                # ping Telegram
python scripts/manual/test_claude.py                  # grade setup sintetis
python scripts/manual/scan_pair.py EUR/USD H4 --grade # debug 1 pair
python scripts/manual/scan_pair.py EUR/USD H4 --grade --png out.png  # simpan chart
python scripts/manual/scan_pair.py EUR/USD H4 --csv data/eurusd.csv  # offline
```

Dry run full scan tanpa Claude (rule grade saja):

```bash
DRY_RUN=true GRADER=rule python scripts/scan_h4.py
```

## Deploy (GitHub Actions)

1. Push repo ini ke GitHub (private).
2. Settings → Secrets and variables → Actions → **Secrets**:
   `TWELVEDATA_API_KEY`, `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`,
   `TELEGRAM_CHAT_ID`, `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`,
   opsional `CHART_IMG_API_KEY` (chart-img.com, chart TradingView asli).
   Tab Variables: `CHART_IMG_LAYOUT_ID` = ID layout TradingView yang di-share
   (URL tradingview.com/chart/<ID>/), layout harus berisi indikator Harmonic XABCD.
3. Tab **Variables**: `DRY_RUN=true` (1 minggu pertama), opsional
   `CLAUDE_MODEL` (default `claude-sonnet-5`).
4. Tab Actions → enable workflow → jalankan manual via *Run workflow* untuk
   cek log.
5. Setelah seminggu bersih, ubah `DRY_RUN=false`.

Cron: H4 tiap `00:05, 04:05, …, 20:05 UTC`; D1 `00:10 UTC`. Scan otomatis
skip Sabtu, Minggu <22:00 UTC, dan Jumat ≥22:00 UTC.

## Budget Twelve Data (free 800/hari)

| Scan | Request/hari |
|------|--------------|
| H4 × 6 × 28 pair | 168 |
| D1 × 1 × 28 pair | 28 |
| HTF (lazy, hanya pair yang lolos pre-grade) | biasanya 0–10 |
| **Total** | **≈ 200–210** |

## Tuning

Semua knob di `config/settings.py`: pivot left/right, `MIN_LEG_ATR`,
`PRZ_APPROACH_PCT` (seberapa dekat harga ke PRZ sebelum dianggap actionable),
`MAX_D_AGE_BARS`, `PRZ_BAND_PCT`, `SL_BUFFER_XA`, threshold R:R & confluence
per grade. Katalog rasio di `config/patterns.py`.

## Keputusan desain yang menyimpang dari spec (sengaja)

- **Dedup key projected D pakai tanggal C**, bukan candle terakhir. Kalau
  pakai candle terakhir, setup yang sama dikirim ulang tiap 4 jam selama
  harga masih di PRZ.
- **HTF alignment** di-fetch lazy (D1 untuk scan H4, W1 untuk scan D1),
  hanya untuk kandidat yang lolos pre-grade, supaya tetap di bawah budget.
- **Model default `claude-sonnet-5`** (lebih murah & baru dari
  `claude-sonnet-4-6` di spec). Override lewat env `CLAUDE_MODEL`.
- **Claude tidak boleh menaikkan grade** di atas rule grade (guardrail),
  hanya konfirmasi atau menurunkan. Kalau Claude error → fallback rule grade
  dengan warning di pesan.
- **Shark/Stingray tidak di-scan**: struktur 0XABC beda, rubric menaruhnya
  di Grade C sehingga tidak pernah terkirim.
- `scan_h4.py`/`scan_d1.py` tipis, logika bersama di `lib/scanner.py`
  (spec menulis ulang logika di dua file).

## Known limitations

- Free tier Twelve Data delay ~4 jam → sinyal H4 efektif "next-bar".
- Cron GitHub free tier bisa telat 5–15 menit.
- Deteksi hanya melihat struktur XABCD **terbaru** (4–5 pivot terakhir);
  pattern yang sudah lewat tidak dilaporkan.
- Belum ada news filter (NFP/FOMC) — cek manual sebelum entry.
- Grade rubric butuh kalibrasi 20–30 setup real (lihat skill).
