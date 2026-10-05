@echo off
setlocal EnableExtensions
title Climate Misinformation SNA - Demo
cd /d "%~dp0"

echo.
echo  ============================================================
echo    Climate Misinformation - Social Network Analysis demo
echo  ============================================================
echo.

if not exist "app.py" (
  echo  [!] app.py was not found next to this file.
  echo      Extract the whole zip first: right-click the zip ^> Extract All,
  echo      then run START_WINDOWS.bat from the extracted folder.
  goto :fail
)

rem ---------- find Python 3.10+ ----------------------------------------------
set "PY="
for %%V in (3.14 3.13 3.12 3.11 3.10) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>nul && set "PY=py -%%V"
  )
)
if not defined PY (
  python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo  [!] Python 3.10 or newer was not found.
  echo      Install it from https://www.python.org/downloads/
  echo      and tick "Add python.exe to PATH" in the installer, then run this again.
  goto :fail
)
for /f "delims=" %%v in ('%PY% -c "import sys; print(sys.version.split()[0])"') do set "PYVER=%%v"
echo  Using Python %PYVER%

rem ---------- one-time setup ---------------------------------------------------
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo  First run: creating a private Python environment in .venv ...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo  [!] Could not create the virtual environment.
    goto :fail
  )
)

if not exist ".venv\setup_done.txt" (
  echo.
  echo  First run: installing libraries - Flask, NumPy, SciPy, scikit-learn, NetworkX.
  echo  This needs internet once and takes 1-3 minutes.
  echo.
  ".venv\Scripts\python.exe" -m pip install --upgrade pip --disable-pip-version-check
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt --disable-pip-version-check
  if errorlevel 1 (
    echo.
    echo  [!] Installing the libraries failed. Check the internet connection and run this file again.
    goto :fail
  )
  echo done> ".venv\setup_done.txt"
)

rem ---------- launch -------------------------------------------------------------
echo.
echo  Starting the app. Your browser will open automatically.
echo  The very first start also processes the dataset (about 1 minute) - progress shows in the browser.
echo.
".venv\Scripts\python.exe" app.py
if errorlevel 1 goto :fail
goto :eof

:fail
echo.
echo  Something went wrong - read the message above.
pause
exit /b 1
