@echo off
chcp 65001 >nul
title Atualizar Olho Vivo e Faro Fino
echo Feche a janela do Olho Vivo e Faro Fino antes de continuar.
pause
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0atualizar.ps1"
echo.
pause
