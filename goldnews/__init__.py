"""Gold News — rekap berita, kalender & analisa sesi XAU/USD.

Alur satu run (scripts/gold_news.py):
  slot jatuh tempo? → kumpulkan berita (RSS) + kalender (ForexFactory) + harga
  (Twelve Data 15m) + makro (Yahoo: DXY, US10Y, minyak, S&P) → hitung hasil
  sesi Asia/London/NY → Claude menganalisa → simpan ke Upstash (dibaca website
  Vercel) → kirim ringkasan ke Telegram.
"""
