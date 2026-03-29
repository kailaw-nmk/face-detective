@echo off
echo Starting Face Image Extractor...
echo.

echo [Backend] starting...
start "Backend" cmd /k "cd /d %~dp0backend && %~dp0venv\Scripts\activate.bat && python -m uvicorn main:app --reload --port 52840"

timeout /t 2 /nobreak >nul

echo [Frontend] starting...
start "Frontend" cmd /k "cd /d %~dp0frontend && npm run dev -- --port 52841"

echo.
echo Ready:
echo   Backend:  http://localhost:52840
echo   Frontend: http://localhost:52841
echo.
pause
