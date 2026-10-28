@echo off
cd /d "%~dp0"
echo ============================================
echo   抓取已连接手机的设备指纹 + 云运动账户
echo ============================================
echo 提示：如果抓不到 token，退出后运行下面这条补：
echo    .venv\Scripts\python.exe grab_device.py --username 学号 --password 密码
echo.
".venv\Scripts\python.exe" grab_device.py
pause
