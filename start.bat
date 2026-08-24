@echo off
REM ============================================================
REM  Face Image Extractor - local start
REM  Builds frontend\dist first, then starts backend and dev server.
REM
REM  The build is NOT optional. backend (:52840) serves frontend\dist,
REM  and that same dist is what Tailscale Serve exposes at
REM  https://i3-2060.tail673a53.ts.net:8443/face-detect/. A stale or
REM  wrongly-based dist shows an old or blank screen there while
REM  http://localhost:52840/ still looks fine - so it is easy to miss.
REM  "npm run build" passes --base=/face-detect/ for exactly that reason.
REM
REM  NOTE: keep this file ASCII-only. cmd mis-parses UTF-8 Japanese.
REM ============================================================

echo Starting Face Image Extractor...
echo.

echo [Frontend] building dist ^(base=/face-detect/^)...
pushd "%~dp0frontend"
call npm run build
if errorlevel 1 (
  echo.
  echo [ERROR] frontend build failed - see the error above.
  echo         Not starting: the servers would serve a stale dist.
  popd
  pause
  exit /b 1
)
popd
echo.

echo [Backend] starting...
start "Backend" cmd /k "cd /d %~dp0backend && %~dp0venv\Scripts\activate.bat && python -m uvicorn main:app --reload --port 52840"

timeout /t 2 /nobreak >nul

echo [Frontend] dev server starting...
start "Frontend" cmd /k "cd /d %~dp0frontend && npm run dev -- --port 52841"

echo.
echo Ready:
echo   Backend:  http://localhost:52840
echo   Frontend: http://localhost:52841        ^(dev server, hot reload^)
echo   Tailscale: https://i3-2060.tail673a53.ts.net:8443/face-detect/
echo.
echo   The Tailscale URL serves frontend\dist, not the dev server.
echo   After changing the frontend, re-run this script ^(or npm run build^)
echo   to refresh it.
echo.
pause
