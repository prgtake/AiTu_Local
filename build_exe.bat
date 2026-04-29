@echo off
echo ===================================================
echo   AiTu_Local EXE Build Script (Python 3.13 Fix)
echo ===================================================
echo.
echo [1/2] Installing required libraries...
python -m pip install --upgrade pip
python -m pip install pyinstaller opencv-python Pillow plotly pandas genanki markdown beautifulsoup4 google-genai

echo [2/3] Cleaning up old build files...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
timeout /t 2 > nul

echo.
echo [3/3] Starting PyInstaller...
:: --exclude-module でエラーの原因となっている pytest を除外します
python -m PyInstaller --onefile --noconsole --clean --name "AiTu_Local" ^
 --exclude-module pytest ^
 --exclude-module py ^
 --hidden-import="cv2" ^
 --hidden-import="PIL._tkinter_finder" ^
 --hidden-import="genanki" ^
 --hidden-import="markdown" ^
 --hidden-import="bs4" ^
 --hidden-import="pandas" ^
 --hidden-import="plotly" ^
 --collect-data "plotly" ^
 app_tkinter.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] PyInstaller failed with error code %ERRORLEVEL%
) else (
    echo.
    echo ===================================================
    echo   Build Process Finished!
    echo   Check the 'dist' folder for AiTu_Local.exe
    echo ===================================================
)
pause
