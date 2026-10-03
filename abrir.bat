@echo off
chcp 65001 >nul
title doc-forense (feche esta janela para encerrar)
cd /d "%~dp0"
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
where uv >nul 2>nul || (echo uv nao encontrado. Rode primeiro o instalar.bat. & pause & exit /b 1)
echo Abrindo o doc-forense no navegador...
echo Esta janela precisa ficar aberta enquanto voce usa o aplicativo.
start "" /b cmd /c "timeout /t 4 /nobreak >nul & start http://localhost:8501"
uv run --no-dev streamlit run app.py
pause
