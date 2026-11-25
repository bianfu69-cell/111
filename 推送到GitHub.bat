@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在推送 Dynabook G83 捡漏雷达代码到 GitHub...
echo 如果弹出 GitHub 登录授权窗口，点 Sign in with your browser 授权即可。
echo.
git push -u origin main
echo.
if %errorlevel% equ 0 (
    echo ✅ 推送成功！现在可以去仓库开启 Actions 和 GitHub Pages 了！
) else (
    echo ❌ 推送未完成，请查看上面的报错信息。
)
pause
