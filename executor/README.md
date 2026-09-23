# Eksekutor MT5 (HFM) — pasang order otomatis dari sinyal

Alur: scanner (GitHub Actions) → antrean Upstash `mt5:queue` → **eksekutor di PC lo** → terminal MT5 HFM → order.

Yang dipasang eksekutor per sinyal (harmonic tahap SIAPKAN ORDER / MASUK ZONA, dan POC):
- **Pending limit** di entry (mid PRZ / POC). Kalau harga sudah lewat entry saat pesan datang (tahap MASUK ZONA), pakai market.
- Lot dihitung supaya rugi di SL = `RISK_PCT` % ekuitas (Grade A 1%, Grade B 0.5%).
- Dua order: 50% lot TP1, 50% lot TP2. Setelah TP1 kena, SL sisa dipindah ke breakeven.
- Pending yang tidak terisi dibatalkan setelah 8 jam (H1), 36 jam (H4), 5 hari (D1); juga kalau scanner bilang "jangan kejar" / zona tembus.
- Pengaman: maksimal 3 setup aktif, rugi harian ≥ 3% saldo → stop sampai besok, kill switch (file `executor/STOP` atau key Upstash `mt5:halt`).
- Setiap aksi dilaporkan ke Telegram dengan awalan 🤖 MT5.

## Pasang di PC eksekutor (Windows)

1. **Python 3.11 atau 3.12 (64-bit)** dari python.org. Centang "Add to PATH". Modul MetaTrader5 belum tentu ada untuk versi lebih baru.
2. **MetaTrader 5 dari HFM** (installer dari area klien HFM). Login akun **demo** dulu. Di MT5: Tools → Options → Expert Advisors → centang **Allow algorithmic trading**, lalu tombol **Algo Trading** di toolbar harus hijau/ON.
3. Salin folder repo ini ke PC itu (zip dari PC ini, atau `git clone` kalau sudah login GitHub di sana).
4. Di folder repo:
   ```bat
   pip install -r executor\requirements.txt
   copy .env.executor.example .env.executor
   ```
   Buka `.env.executor` dengan Notepad, isi `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER` (nama server persis seperti di MT5, contoh `HFMarketsGlobal-Demo`), dan `UPSTASH_*` + `TELEGRAM_*` (sama dengan `.env` scanner).
5. Tes koneksi:
   ```bat
   python -m executor.run --once
   ```
   Harus muncul akun, saldo, dan mapping simbol (`EUR/USD → EURUSD`, `XAU/USD → XAUUSD`, crypto HFM berawalan `#`:
   `BTC/USD → #BTCUSD`). Kalau simbol tidak ketemu, isi `MT5_SYMBOL_MAP` di `.env.executor`. Cek cepat tanpa sentuh
   antrean: `python -m executor.run --check`.
   Catatan HFM (23 Sep 2026): nama server di aplikasi HFM tertulis "HFMarketsGlobal-Demo 4", tapi di MT5 harus
   **tanpa spasi**: `HFMarketsGlobal-Demo4`. Tombol Algo Trading bisa dinyalakan dengan Ctrl+E di jendela MT5.
6. Jalan terus: klik dua kali `executor\run_executor.bat` (restart sendiri kalau crash). Supaya jalan otomatis saat PC nyala: Task Scheduler → Create Basic Task → trigger "When I log on" → action start program `executor\run_executor.bat`. PC jangan sleep (Power options).

## Cara stop / kontrol
- Berhenti sementara pasang order baru: buat file kosong `executor\STOP` (hapus untuk lanjut), atau dari HP: console Upstash → set key `mt5:halt` = `1`.
- Pending/posisi yang sudah ada tetap harus dikelola manual kalau eksekutor dimatikan.
- State lokal ada di `executor\state.json` (tiket per setup). Hapus file itu = eksekutor lupa apa yang sudah dipasang (bisa dobel).

## Catatan jujur
- Jalankan di **demo minimal 1 bulan**. Cek: order masuk di harga yang benar, lot sesuai risiko, SL/TP benar, breakeven jalan.
- Eksekutor cuma jalan kalau PC + terminal MT5 nyala. PC mati = order baru tidak masuk (order yang sudah terpasang tetap hidup di server broker).
- Spread HFM saat pasar tipis (Asia session, berita) bisa bikin SL kena lebih cepat dari hitungan scanner.
