@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在启动 Dynabook G83 雅虎日拍捡漏雷达...
echo 启动后会自动在浏览器打开 http://127.0.0.1:8783
echo.
python server.py --port 8783
pause
