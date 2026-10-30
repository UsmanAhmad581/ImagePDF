@echo off
REM ============================================================
REM  Builds ImagePDF.exe + Setup installer on Windows
REM  Needs: Python 3.10+, Tesseract OCR (UB-Mannheim), Inno Setup 6
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

where iscc >nul 2>nul
if %errorlevel%==0 (
  iscc installer.iss
) else if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
  "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
) else (
  echo Inno Setup not found - skipped installer. App folder: dist\ImagePDF
)
echo.
echo DONE.  Installer: installer_output\ImagePDF-Setup.exe
endlocal
