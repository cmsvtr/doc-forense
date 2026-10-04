@echo off
chcp 65001 >nul
title Teste de velocidade da IA local
cd /d "%~dp0"
set "PATH=%USERPROFILE%\.local\bin;%LOCALAPPDATA%\Programs\Ollama;%PATH%"
echo Teste de velocidade da IA local (pode levar de 1 a 5 minutos; a primeira vez e mais lenta).
echo.
uv run --no-dev python -m forense ia
echo.
echo Copie as linhas acima (Leitura, Escrita e Estimativa) e envie.
pause
