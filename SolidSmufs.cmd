@echo off
rem Start the SolidSmufs part viewer (optionally with a file: SolidSmufs.cmd "C:\path\part.step")
start "" /D "%~dp0" "%~dp0.venv\Scripts\pythonw.exe" -m solidsmufs %*
