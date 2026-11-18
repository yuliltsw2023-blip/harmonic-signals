# Gold Briefing — rekap berita & analisa sesi XAU/USD

Sistem otomatis (GitHub Actions) yang tiap hari kerja mengirim briefing emas ke
channel Telegram dan menyimpan history di website https://gold-briefing-beta.vercel.app
(dikunci password — username bebas, password = `GOLDNEWS_SITE_PASSWORD` di `.env`).

| Jam WIB (musim dingin) | Briefing | Isi |
|---|---|---|
| 06:30 | Pra-Asia | hasil sesi NY semalam, berita, kalender hari ini, outlook Asia |
| 14:30 | Pra-London | hasil Asia, outlook London |
| 19:30 | Pra-New York | hasil London, data AS yang akan rilis, outlook NY |
| 21:00 | Reaksi data AS | reaksi harga ke rilis 20:30 |
| Sabtu 06:30 | Rekap mingguan | ringkasan minggu + outlook minggu depan |

Saat Eropa/AS masuk jam musim panas (Mar–Okt/Nov), jam Pra-London, Pra-NY dan
Reaksi data AS otomatis maju 1 jam (dihitung `zoneinfo`).

## Alur satu run (`scripts/gold_news.py` → `goldnews/run.py`)
1. Tentukan slot yang jatuh tempo (`goldnews/sessions.py`); slot yang sudah terkirim dilewati.
2. Ambil candle XAU/USD 15m (Twelve Data), berita RSS (Google News 7 query, investingLive,
   FXStreet, CNBC, MarketWatch, The Fed, World Gold Council), kalender ForexFactory minggu
   ini, pasar terkait (Yahoo: DXY, US10Y, WTI, S&P 500, perak, VIX).
3. Hitung hasil sesi Asia/London/NY → Bullish/Bearish/Sideways (perubahan ≥ 20% ADR dan
   close di 40% teratas/terbawah range; selain itu Sideways).
4. Claude (`GOLDNEWS_MODEL`, default `claude-opus-5-5`) menulis analisa makro & mikro,
   memilih berita kunci beserta arah dampaknya, event berisiko, level & skenario, dan bias
   sesi target. Output JSON terstruktur.
5. Outlook lama yang sesinya sudah selesai dinilai otomatis (tepat/meleset) → tab Akurasi.
6. Data disimpan ke `goldnews/site/data/` (di-commit) → website di-deploy → pesan Telegram.

## Biaya per bulan (perkiraan)
- Claude Opus 5.5: ±15 rb token masuk + ±3–4 rb keluar per briefing ≈ $0.13 → ±92 briefing
  ≈ **$12/bulan**. Ganti ke Sonnet 5.5 (Variable `GOLDNEWS_MODEL=claude-sonnet-5-5`) ≈ $6.
- GitHub Actions ±21 run kecil/hari kerja ≈ 500–650 menit (kuota repo private 2.000).
- Twelve Data, RSS, ForexFactory, Yahoo, Vercel Hobby: gratis.

## Setup
GitHub → Settings → Secrets and variables → Actions:
- Secrets yang sudah ada dipakai ulang: `TWELVEDATA_API_KEY`, `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`.
- Secret baru: `GOLDNEWS_CHAT_ID` (id channel Telegram Gold News), `VERCEL_TOKEN`
  (vercel.com/account/tokens → Create).
- Variable opsional: `GOLDNEWS_MODEL`, `GOLDNEWS_SITE_URL`.

### Pemicu tepat waktu (disarankan)
Cron GitHub sering telat/melewatkan run. Buat 4 job di https://cron-job.org (gratis):
- URL `https://api.github.com/repos/yuliltsw2023-blip/harmonic-signals/actions/workflows/gold-news.yml/dispatches`
- Method POST, body `{"ref":"main"}`, header `Authorization: Bearer <fine-grained token: Actions read & write>`,
  `Accept: application/vnd.github+json`.
- Jadwal (zona Asia/Jakarta): 06:28 setiap hari kecuali Minggu; 14:28, 19:28, 20:58 Senin–Jumat
  (musim panas: 13:28, 18:28, 19:58).

## Manual
```bash
# uji tanpa kirim (report tetap disimpan ke goldnews/site/data)
GOLDNEWS_SLOT=pre_ny DRY_RUN=true python scripts/gold_news.py
# deploy website manual
cd goldnews/site && vercel deploy --prod
```
GitHub Actions → Gold News Briefing → Run workflow (isi `slot` untuk memaksa slot tertentu,
`force=true` untuk mengirim ulang).
