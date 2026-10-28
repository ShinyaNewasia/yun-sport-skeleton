@echo off
cd /d "%~dp0"
echo ============================================
echo   从现有轨迹里随机融合出 5 条新轨迹
echo   （每圈从不同源轨迹抽取，接缝自动校验）
echo ============================================
".venv\Scripts\python.exe" tools\fuse_track.py --count 5
echo.
echo 生成结果在 tasks\tasklist_fused_*.json
echo 双击「一键跑-打表.bat」时会随机挑到其中一条。
pause
