@echo off
chcp 65001 >nul
title Instalador doc-forense
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar.ps1"
echo.
pause
