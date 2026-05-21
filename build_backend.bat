@echo off
setlocal
cd /d "%~dp0"
python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --windowed ^
  --name design_output_backend ^
  --distpath dist-backend ^
  --workpath build-backend ^
  backend_main.py
