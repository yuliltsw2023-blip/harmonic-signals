@echo off
rem Jalankan eksekutor MT5 terus-menerus; kalau crash, mulai lagi setelah 30 detik.
cd /d "%~dp0.."
:loop
python -m executor.run
echo eksekutor berhenti (kode %errorlevel%), mulai lagi 30 detik...
timeout /t 30 /nobreak >nul
goto loop
