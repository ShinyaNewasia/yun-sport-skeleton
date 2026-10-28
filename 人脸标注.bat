@echo off
cd /d "%~dp0"
echo ============================================
echo   自拍照 -^> 云运动人脸标注 JSON
echo   （纯本地检测，照片不上传）
echo ============================================
echo.
set /p PHOTO=把自拍照拖进来或输入路径，然后回车：
if "%PHOTO%"=="" goto end
".venv\Scripts\python.exe" tools\detect_face.py "%PHOTO%"
echo.
echo 标注文件生成在照片旁边的 xxx.face.json
echo 跑的时候这样用：
echo   .venv\Scripts\python.exe main.py --face-photo "照片" --face-detection "标注.json"
:end
pause
