# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

block_cipher = None

# Base directories
project_dir = Path.cwd()

datas = [
    (str(project_dir / "app" / "templates"), "app/templates"),
    (str(project_dir / "app" / "static"), "app/static"),
]

hiddenimports = [
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespans",
    "uvicorn.lifespans.on",
    "fastapi",
    "starlette",
    "jinja2",
    "pyftpdlib",
    "pyftpdlib.authorizers",
    "pyftpdlib.handlers",
    "pyftpdlib.servers",
    "qrcode",
    "PIL",
    "websockets",
    "tkinter",
    "tkinter.filedialog",
]

# Exclude heavy unrelated machine-learning & numerical packages to keep file size small
excludes = [
    "torch",
    "torchvision",
    "torchaudio",
    "numpy",
    "scipy",
    "cv2",
    "moviepy",
    "imageio",
    "onnxruntime",
    "sympy",
    "numba",
    "llvmlite",
    "ollama",
    "google.generativeai",
    "boto3",
    "botocore",
    "whisper",
    "openai_whisper",
    "fpdf2",
    "matplotlib",
    "pandas",
    "IPython",
    "jupyter",
]

a = Analysis(
    ['main.py'],
    pathex=[str(project_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PixVibeFTP',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # GUI application, no black console window!
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_dir / "app" / "static" / "favicon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PixVibeFTP',
)
