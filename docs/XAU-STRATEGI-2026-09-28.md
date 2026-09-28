# XAU/USD — rencana dua arah (28 Sep 2026)

Data: OANDA:XAUUSD, dibaca 28 Sep 2026 ~07:20 UTC, harga 4.160 (D1 −2,95%, range 4.235–4.255 jebol).
Eksekusi: **manual-konfirmasi → antrean EA** (`scripts/manual/queue_manual.py`), bias dari D1, entry dari struktur M15/H1.

## Peta

| Level | Harga | Arti |
|---|---|---|
| A | 4.697 | high 25 Agu (lower high vs 4.891) |
| Zona short retest | 4.235–4.290 | lantai range yang jebol + 0,5–0,618 leg turun |
| C | 4.399,67 | 18 Sep |
| **PRZ Gartley bull** | **4.096–4.134** | 0,786 XA 4.117,6 · 1,618 BC 4.133,5 · AB=CD 4.096,5 · 4.100 |
| 0,886 XA | 4.043,9 | batas terakhir sebelum Gartley gugur |
| X / double bottom | 3.942–3.960 | target short lanjutan |

Gartley D1: X 3.959,80 (17 Jul) → A 4.697,11 (25 Agu) → B 4.235,17 (16 Sep) → C 4.399,67 (18 Sep).
AB/XA 0,627 ✅ · BC/AB 0,356 ⚠️ (<0,382) → **Grade C** di rubric skill; HTF (weekly lower highs sejak 5.602) = long counter-trend.

## Aturan umum
- Sesi: 07:00–20:00 UTC saja. Tidak ada entry ±2 jam dari rilis berdampak besar (NFP Jumat 2 Okt 2026, CPI, FOMC-speak).
- Maks 1 posisi XAU. **Risiko 1,5% (≈ $15) → SL ≤ 15 poin** (0,01 lot = $1/poin; keputusan user 28 Sep). SL lebih jauh = skip, jangan paksa.
- **Keluar (default script): TP = 2R, SL→BE setelah +1R** (`--exit tpbe`, EA v1.3). Simulasi M15 7 Agu–28 Sep, SL ≤ 15: n 16, win 38%, PF 1,27, maxDD 3,1R — lebih baik dari trailing (PF 1,05) dan TP 3R (PF 0,96). Sampel kecil.
- Trailing tetap tersedia (`--exit trail --tf H1`) tapi bukan default.
- 2 kali SL XAU = −3% = batas rugi harian EA → EA berhenti sampai besok.
- Lot 0,01 tidak bisa dibagi TP1/TP2.

## LONG — Gartley PRZ 4.096–4.134 (counter-trend, wajib konfirmasi)
1. Harga masuk PRZ.
2. Trigger M15: higher low + candle close menembus lower-high M15 terakhir (CHoCH), **atau** H1 bullish engulfing / pin bar yang close di dalam/atas PRZ.
3. Entry: limit di retest level yang ditembus (atau market kalau langsung lari ≤ 0,25R).
4. SL: di bawah low reaksi −2 poin, maksimal 15 poin.
5. TP: 2R otomatis; SL→BE di +1R.
6. Batal: H4 close < 4.090, atau D1 close < 4.096.

Contoh: `python scripts/manual/queue_manual.py XAU/USD buy --entry 4120 --sl 4108 --setup GartleyD1`

## SHORT A — retest 4.235–4.290 (searah tren)
1. Harga memantul dari PRZ dan kembali ke 4.235–4.290.
2. Trigger M15/H1: lower high + close menembus higher-low M15 terakhir, atau H1 bearish engulfing di zona.
3. SL di atas high rejection +2, maks 15 poin. TP 2R, SL→BE di +1R.

`python scripts/manual/queue_manual.py XAU/USD sell --entry 4262 --sl 4275 --setup RetestShort`

## SHORT B — breakdown (kalau PRZ gagal)
1. D1 close < 4.096.
2. Retest 4.096–4.130 dari bawah + trigger M15 bearish.
3. SL ≤ 15 poin di atas rejection. TP 2R, SL→BE di +1R (level 4.044 / 4.000 / 3.960 = acuan arah).

## Cara kirim ke EA (butuh EA v1.3 di Mac)
1. Pratinjau dulu (tanpa `--send`), cek R:R & peringatan lot.
2. Tambah `--send` → event masuk `mt5:queue`, EA di Mac memasang order dalam ~20 detik, konfirmasi "🤖 MT5 EA" di Telegram.
3. Pending kedaluwarsa otomatis (M15 2 jam, H1 8 jam; ubah dengan `--expires`).
4. Batalkan: perintah Telegram `/cancel` ke EA (membatalkan SEMUA pending EA, bukan cuma XAU).

⚠️ Analisis edukatif. Backtest 24–26 Sep belum menunjukkan edge yang meyakinkan untuk sistem ini; perlakukan sebagai paper trade di akun demo.
