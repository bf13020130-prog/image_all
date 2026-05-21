# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules


hiddenimports = (
    collect_submodules('anyio')
    + collect_submodules('fastapi')
    + collect_submodules('multipart')
    + collect_submodules('starlette')
    + collect_submodules('uvicorn')
)

a = Analysis(
    ['backend_main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='design_output_backend_console',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='design_output_backend_console',
)
