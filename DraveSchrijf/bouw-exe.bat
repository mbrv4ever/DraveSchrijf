@echo off
title DraveSchrijf - EXE bouwen
cd /d "%~dp0"
set "VPY=%~dp0.venv\Scripts\python.exe"
if not exist "%VPY%" (
  echo Nieuwe .venv maken met Python 3.13...
  py -3.13 -m venv .venv || goto mislukt
)
"%VPY%" -m pip install -q --upgrade pip
"%VPY%" -m pip install -q -r requirements.txt pyinstaller pillow || goto mislukt
"%VPY%" make_icon.py
"%VPY%" -m PyInstaller --noconfirm --clean --windowed --onedir --name DraveSchrijf --icon assets\icon.ico --add-data "assets;assets" --add-data "DraveSchrijf-Snelgids.pdf;." --collect-all faster_whisper --collect-all ctranslate2 --collect-all neuvoice --collect-all onnxruntime --collect-all sounddevice --collect-data av --hidden-import stem --hidden-import oren --hidden-import drave_update --exclude-module tkinter --exclude-module PyQt6.QtWebEngineCore --exclude-module PyQt6.QtWebEngineWidgets --exclude-module PyQt6.QtQml --exclude-module PyQt6.QtQuick --exclude-module matplotlib --exclude-module PIL draveschrijf.py
if errorlevel 1 goto mislukt
if not exist "dist\DraveSchrijf\DraveSchrijf.exe" goto mislukt
xcopy /e /i /y assets "dist\DraveSchrijf\assets" >nul
copy /y DraveSchrijf-Snelgids.pdf "dist\DraveSchrijf\" >nul
echo.
echo KLAAR: dist\DraveSchrijf\DraveSchrijf.exe
exit /b 0
:mislukt
echo MISLUKT - kijk hierboven voor de fout.
exit /b 1
