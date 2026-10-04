@echo off
chcp 65001 >nul
title Instalar a IA local do doc-forense
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar_ia.ps1"
echo.
pause
