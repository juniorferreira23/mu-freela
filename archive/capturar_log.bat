@echo off
REM Captura o logcat do BlueStacks oficial em tempo real para um arquivo.
REM Uso: capturar_log.bat   (Ctrl+C para parar)  ->  gera logcat_YYYYMMDD_HHMMSS.txt
set ADB="C:\Program Files\BlueStacks_nxt\HD-Adb.exe"
%ADB% connect 127.0.0.1:5555 >nul
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /format:list ^| find "="') do set TS=%%I
set ARQUIVO=logcat_%TS:~0,8%_%TS:~8,6%.txt
echo Gravando em %ARQUIVO% ... (Ctrl+C para parar)
%ADB% -s emulator-5554 logcat -v time > %ARQUIVO%
