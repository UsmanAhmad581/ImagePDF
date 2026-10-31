@echo off
REM ============================================================
REM  Builds ImagePDF.exe + Setup installer on Windows
REM  Needs: Python 3.10+, Tesseract OCR (UB-Mannheim), Inno Setup 6.3+
REM ============================================================
setlocal
set TESS="C:\Program Files\Tesseract-OCR"
if not exist %TESS%\tesseract.exe (
  echo Tesseract not found in %TESS%.  Install it first:
  echo https://github.com/UB-Mannheim/tesseract/wiki
  exit /b 1
)

py -m venv .venv || exit /b 1
call .venv\Scripts\activate
pip install -r requirements.txt pyinstaller || exit /b 1

pyinstaller --noconfirm --clean --windowed --name ImagePDF ^
  --collect-all customtkinter --collect-all tkinterdnd2 main.py || exit /b 1

echo Bundling Tesseract OCR...
xcopy /E /I /Y /Q %TESS% dist\ImagePDF\tesseract >nul

set ISCC=
where iscc >nul 2>nul && set ISCC=iscc
if not defined ISCC if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not defined ISCC (
  echo Inno Setup not found - installer NOT built. App folder: dist\ImagePDF
  exit /b 1
)
%ISCC% installer.iss || (
  echo Inno Setup failed - installer NOT built.
  exit /b 1
)
if not exist installer_output\ImagePDF-Setup.exe (
  echo Installer file was not produced.
  exit /b 1
)
echo.
echo DONE.  Installer: installer_output\ImagePDF-Setup.exe
endlocal
