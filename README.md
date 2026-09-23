# harmonic-signals

Scanner harmonic pattern (Bat, Gartley, Crab, Deep Crab, Butterfly, Cypher)
untuk 28 pair forex + XAU, BTC, ETH (vs USD) di H4 + D1, plus H1 untuk 7 simbol paling likuid,
**ditambah screener strategi kedua "POC Pullback"** (skill `poc-pullback-entry`) yang jalan di
candle yang sama, dan scan saham D1 (US + IDX) lewat Yahoo Finance — lihat bagian
[POC Pullback screener](#poc-pullback-screener-strategi-kedua). XAG/USD sudah
dikonfigurasi tapi nonaktif: Twelve Data free tier tidak menyediakannya (butuh plan Grow). Deteksi mekanis di Python, grading oleh Claude
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

Cron (sejak 17 Sep 2026): **satu job per jam** `scan-hourly.yml` di menit `:01 UTC` menjalankan H1 (7 simbol, `H1_SYMBOLS`, tanpa crypto) setiap jam, H4 (31 simbol) di jam 0/4/8/12/16/20, dan D1 di jam 00 — setup GitHub dibayar sekali per jam dan H1 jalan 1 menit setelah candle close (dulu `:20` + delay cron ≈ 45 menit). `scan-h4.yml` / `scan-d1.yml` tinggal untuk Run workflow manual; `scan-m15.yml` cron nonaktif, lihat bagian "Mode entry". Scan otomatis
skip Sabtu, Minggu <22:00 UTC, dan Jumat ≥22:00 UTC.

## POC Pullback screener (strategi kedua)

Mengikuti skill `.claude/skills/poc-pullback-entry/SKILL.md` (video Bond Bard Trade):
bias dari 2 swing high + 2 swing low terakhir (HH+HL / LH+LL), Fixed Range profile di leg
impulsif terakhir → POC / VAH / VAL, lalu **kirim pesan teks (tanpa chart)** saat harga
mendekati / masuk / bereaksi dari Value Area. Grade rule-based (tanpa Claude) — murah.

```
lib/poc.py        analyze_poc(): pivot → bias → leg → profile → stage → SL/TP/R:R → pre-grade
                  rule_grade_poc(): weakest link (kedalaman, leg, HTF, R:R, reaksi, sumber profile)
lib/yahoo.py      candle saham (US & IDX) + volume dari Yahoo Finance, tanpa key
lib/telegram.py   format_poc_signal() — teks saja
scripts/scan_stocks.py + .github/workflows/scan-stocks-d1.yml — saham D1
scripts/manual/scan_poc.py SYMBOL [H1|H4|D1] [--send]   — debug satu simbol
```

Poin penting:

- **Sumber bobot profile.** Twelve Data free tidak kasih volume forex/crypto → profile pakai
  **TPO (time-at-price, 1 per bar)** ala Market Profile asli, dan grade maksimal **B**. Saham
  (Yahoo) pakai volume asli. Pesan selalu menyebut sumbernya.
- **Stage** (dedup per leg impulsif per stage, jadi maksimal 3 pesan per leg):
  `approaching` 👀 harga ≤ N% dari tepi VA · `in_va` 🎯 harga di dalam VA · `reacted` ✅
  candle terakhir menutup di atas/bawah VA setelah menyentuhnya. Stage lain (waiting,
  impulse, below_va, left_va, continued, broken) tidak dikirim.
- **Pre-grade skip**: struktur UNCLEAR, leg < 8 candle, kedalaman POC di luar 0.20–0.79,
  R:R efektif < 1.5 (R:R efektif = max(TP2 dgn SL swing, TP1 dgn SL Value Area)).
- **0 request tambahan** untuk universe forex/crypto: analisis dari candle yang sudah di-fetch
  untuk harmonic; HTF di-fetch lazy dan dibagi dengan harmonic.
- Universe saham di `config/pairs.py` (`STOCK_US_SYMBOLS`, `STOCK_IDX_SYMBOLS`, format Yahoo
  `BBCA.JK`); cron 09:15 UTC (setelah tutup IDX) dan 21:15 UTC (setelah tutup NYSE), Senin–Jumat.
  Saham juga di-scan harmonic (D1) dengan grade Claude seperti biasa.
- Matikan lewat Variables `POC_ENABLED=false`. Parameter di `config/settings.py` blok `POC_*`.
- Reaksi, news (NFP/earnings/ex-date), dan keputusan entry tetap manual — screener hanya
  memberi tahu "ini sudah di area yang bisa diincar".

Test manual:

```bash
python scripts/manual/scan_poc.py EUR/USD H4          # Twelve Data, TPO
python scripts/manual/scan_poc.py BBCA.JK D1          # Yahoo, volume asli
python scripts/manual/scan_poc.py AAPL D1 --send      # kirim ke Telegram
DRY_RUN=true GRADER=rule python scripts/scan_stocks.py idx
```

## Budget Twelve Data (free 800/hari)

| Scan | Request/hari |
|------|--------------|
| H1 × 24 × 7 simbol | 168 |
| H4 × 6 × 31 simbol | 186 |
| D1 × 1 × 31 simbol | 31 |
| Saham (Yahoo, bukan Twelve Data) | 0 |
| HTF (lazy, hanya pair yang lolos pre-grade) | biasanya 0–10 |
| **Total** | **≈ 390–405** |

Jatah menit GitHub Actions (repo private, 2000/bulan) adalah batas yang lebih ketat: tiap request Twelve Data ≈ 8 detik,
dan **GitHub membulatkan tiap job ke atas per menit** (job 70 detik = 2 menit). Dengan job hourly gabungan: 18 jam × 2 menit
(H1 saja) + 5 jam × 6 menit (H1+H4) + 1 jam × 10 menit (H1+H4+D1) ≈ 76 menit/hari kerja. Cron hanya Senin–Jumat
(weekend forex tutup, run cuma buang setup): 22 hari × 76 ≈ **1.700 menit/bulan**, di bawah jatah private dengan sisa
≈300 (sebelum digabung & masih jalan weekend ≈ 2.100). M15 tetap tidak muat di private (+≈2.300); butuh repo public.

## Mode entry, R:R minimum, scalping M15

- Sinyal harmonic **dua tahap per setup** (dedup per tahap, seperti POC), diatur `SIGNAL_STAGES` (default
  `approaching,in_prz,left`):
  - `approaching` 🕒 **SIAPKAN ORDER**: harga ≤ `approach` (forex 0.35%) dari tepi PRZ, belum masuk. Pesan berisi
    "Pasang: Limit BUY/SELL @ mid PRZ" + SL/TP — user pasang pending order lalu tinggal, harga yang datang ke order.
  - `in_prz` ✅ **MASUK ZONA**: harga sudah di PRZ (± `entry_tol`, forex 8 pip). Limit harusnya aktif; kalau belum pasang,
    boleh entry sekarang.
  - `left` ⚠️ **JANGAN KEJAR**: D sudah terbentuk dan harga sudah lewat PRZ menuju TP — pesan teks, hanya kalau tahap
    sebelumnya pernah dikirim (kalau limit sudah kena: kelola SL/TP; kalau belum: lewatkan).
  - Tahap `far` (masih jauh) dan `pierced` (menembus zona) tidak pernah dikirim. Setiap pesan mencantumkan **jam scan
    sebenarnya** dan harga saat scan, bukan jam candle, supaya jelas seberapa basi harganya.
  Alasannya: cron GitHub free tier telat 5–30 menit, jadi entry market saat notif masuk rawan ngejar harga (exit liquidity).
- `MIN_RR_TP2=2.0`: kandidat dengan R:R ke TP2 (harmonic) / R:R efektif (POC) di bawah 2 dibuang sebelum grading.
- M15/M30: `scripts/scan_m15.py` + workflow `scan-m15.yml` (universe `SCALP_SYMBOLS` = EUR/USD, GBP/USD, USD/JPY,
  XAU/USD; HTF M15 = 1h; parameter jarak di-scale `TF_SCALE` 0.3 karena struktur M15 jauh lebih pendek).
  Cron-nya **sengaja nonaktif**: 52 run/hari (07–19 UTC, Sen–Jum) × 2 menit ≈ 2.300 menit/bulan, melebihi jatah repo
  private. Aktifkan (hapus `#` di `schedule:`) hanya kalau repo sudah public. Twelve Data: +208 request/hari, masih di bawah 800.

## Tuning

Simbol & asset class di `config/pairs.py` (`SYMBOL_META`: XAU/XAG = metal, BTC/ETH = crypto 24/7).
Parameter per asset (`ASSET_PARAMS`) dan knob lain di `config/settings.py`: pivot left/right, `MIN_LEG_ATR`,
`ASSET_PARAMS[...]["approach"]` / `["entry_tol"]` (jarak ke PRZ yang dianggap actionable / sudah di zona),
`ENTRY_MODE`, `MIN_RR_TP2`, `TF_SCALE`,
`MAX_D_AGE_BARS`, `PRZ_BAND_PCT`, `SL_BUFFER_XA`, threshold R:R & confluence
per grade. Katalog rasio di `config/patterns.py`.

## Eksekusi otomatis ke MetaTrader 5 (HFM)

Setiap sinyal yang dikirim ke Telegram (harmonic tahap SIAPKAN ORDER / MASUK ZONA, POC) juga ditulis sebagai event
order ke antrean Upstash `mt5:queue` (`lib/orders.py`, `MT5_QUEUE=true`). Eksekutor `executor/` di PC Windows yang
terminal MT5-nya nyala membaca antrean itu dan memasang pending limit (atau market kalau harga sudah di zona) dengan lot
= risiko 1% ekuitas (Grade B 0.5%), 50/50 TP1/TP2, SL ke breakeven setelah TP1, pembatalan otomatis saat "jangan
kejar" / zona tembus / kedaluwarsa, batas 3 setup aktif dan rugi harian 3%. Panduan pasang: `executor/README.md`.

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
- POC forex/crypto memakai TPO (bukan volume) karena Twelve Data free tidak kirim volume;
  saham IDX tidak tersedia di Twelve Data free → dipakai endpoint Yahoo Finance yang tidak resmi
  (bisa berubah sewaktu-waktu).
- Grade rubric butuh kalibrasi 20–30 setup real (lihat skill).
