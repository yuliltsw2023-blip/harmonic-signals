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

## Versi Expert Advisor (MQL5) — untuk Mac mini / VPS tanpa Python

`executor/mql5/HarmonicExecutor.mq5` = logika yang sama, jalan di dalam MT5 (Windows maupun MT5 for Mac), tanpa Python.
Baca antrean Upstash lewat WebRequest, pasang limit/market, lot dari risiko %, 50/50 TP1/TP2 (komentar
`HS<hash>|TP1|<jam kedaluwarsa>`), SL→BE setelah TP1 untung, cancel, batas setup & rugi harian, notifikasi Telegram
"🤖 MT5 EA". Kill switch: key Upstash `mt5:halt` = 1 atau Global Variable terminal `HS_HALT` = 1 (F3 di MT5).

Pasang:
1. Salin `HarmonicExecutor.mq5` ke folder data terminal `MQL5\Experts\` (File → Open Data Folder), compile di MetaEditor (F7).
2. Tools → Options → Expert Advisors: centang **Allow WebRequest for listed URL** dan tambahkan
   `https://<akun>.upstash.io` (host dari UPSTASH_REDIS_REST_URL) dan `https://api.telegram.org`. Tombol Algo Trading ON.
3. Taruh file `harmonic_executor.cfg` (baris `upstash_url=`, `upstash_token=`, `telegram_token=`, `telegram_chat=`)
   di folder data terminal `MQL5\Files\`. EA membacanya saat input Upstash di dialog dibiarkan kosong — jadi tidak
   perlu mengetik apa pun di dialog EA. (Alternatif: isi tab Inputs manual / Load preset.)
4. Buka satu chart apa saja (mis. EURUSD H1), Navigator → Expert Advisors → HarmonicExecutor → drag ke chart → OK.
   Catatan: kalau EA dicompile ulang dari luar (metaeditor /compile), terminal TIDAK me-reload EA di chart —
   lepas & pasang lagi, atau restart terminal.
5. Tab Experts di bawah harus menampilkan "[HS] config dibaca ..." dan "[HS] EA jalan", Telegram dapat pesan "EA jalan".
6. **Hanya satu eksekutor yang boleh jalan** (EA ini ATAU `python -m executor.run`), kalau tidak order dobel.
Mac: MT5 for Mac dari HFM, langkah sama; System Settings → Energy → matikan sleep; MT5 masuk Login Items.

### Laporan & perintah lewat Telegram (EA)
- Laporan portofolio otomatis pada jam `InpReportHours` (UTC, default `2,14` = 09:00 & 21:00 WIB): saldo, ekuitas,
  floating, realized hari ini & 7 hari, posisi terbuka, pending, status EA.
- Perintah diketik di channel Telegram (hanya admin channel yang bisa posting) atau dari user id `InpTelegramAdmin`:
  `/status` laporan sekarang · `/off` berhenti pasang order baru (pending & posisi tetap) · `/on` lanjut ·
  `/cancel` hapus semua pending EA · `/help`. Bot harus admin channel supaya menerima channel_post.
- Update EA di Mac: salin `.ex5` baru ke `MQL5/Experts`, lalu **quit & buka lagi MT5** (EA tidak di-reload otomatis).

## Cara stop / kontrol
- Berhenti sementara pasang order baru: buat file kosong `executor\STOP` (hapus untuk lanjut), atau dari HP: console Upstash → set key `mt5:halt` = `1`.
- Pending/posisi yang sudah ada tetap harus dikelola manual kalau eksekutor dimatikan.
- State lokal ada di `executor\state.json` (tiket per setup). Hapus file itu = eksekutor lupa apa yang sudah dipasang (bisa dobel).

## Catatan jujur
- Jalankan di **demo minimal 1 bulan**. Cek: order masuk di harga yang benar, lot sesuai risiko, SL/TP benar, breakeven jalan.
- Eksekutor cuma jalan kalau PC + terminal MT5 nyala. PC mati = order baru tidak masuk (order yang sudah terpasang tetap hidup di server broker).
- Spread HFM saat pasar tipis (Asia session, berita) bisa bikin SL kena lebih cepat dari hitungan scanner.
