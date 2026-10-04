@echo off
chcp 65001 >nul
title Atualizar doc-forense
echo Feche a janela do doc-forense antes de continuar.
pause
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0atualizar.ps1"
echo.
pause
