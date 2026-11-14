@echo off
REM بناء ملف FreeDM.exe واحد جاهز للتشغيل على ويندوز
python -m pip install -r requirements.txt
python -m PyInstaller --noconsole --onefile --name FreeDM run_fdm.py
echo.
echo تم. الملف موجود في: dist\FreeDM.exe
pause
