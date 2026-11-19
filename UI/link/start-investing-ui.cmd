@echo off
rem Starts the investing UI server and opens the page in your browser.
rem Keep this window open while you use the page; close it to stop the server.
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" "UI\server.py" --open
