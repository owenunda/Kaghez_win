# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the Windows build. Run through build.sh, which
# sets KAGHEZ_PREFIX (the `meson install` prefix) and KAGHEZ_OUT.

import os

prefix = os.environ['KAGHEZ_PREFIX']
out = os.environ['KAGHEZ_OUT']
share = os.path.join(prefix, 'share')
pkgdatadir = os.path.join(share, 'kaghez')

# Laid out under _internal/ exactly as `meson install` does under the
# prefix, which is what kaghez.in's frozen branch expects. The Python
# sources in share/kaghez/kaghez are left out: PyInstaller freezes them.
# The JRE is copied in by build.sh afterwards, so PyInstaller doesn't try
# to analyze its DLLs as if they were Python extension dependencies.
datas = [
    (os.path.join(pkgdatadir, 'kaghez.gresource'), 'share/kaghez'),
    (os.path.join(pkgdatadir, 'Suwayomi-Server-v2.3.2361.jar'), 'share/kaghez'),
    (os.path.join(pkgdatadir, 'schemas'), 'share/kaghez/schemas'),
    (os.path.join(share, 'icons'), 'share/icons'),
]
if os.path.isdir(os.path.join(share, 'locale')):
    datas.append((os.path.join(share, 'locale'), 'share/locale'))

a = Analysis(
    [os.path.join(out, 'Kaghez.py')],
    # kaghez.in imports the app as `from kaghez import main`.
    pathex=[pkgdatadir],
    binaries=[],
    datas=datas,
    # Imported lazily or only on some paths, so the analysis can miss them.
    hiddenimports=['kaghez.winproc', 'PIL.Image', 'PIL.AvifImagePlugin', 'PIL.WebPImagePlugin'],
    hookspath=[],
    hooksconfig={
        'gi': {
            'icons': ['Adwaita', 'hicolor'],
            'themes': ['Adwaita'],
            'module-versions': {
                'Gtk': '4.0',
                'Adw': '1',
            },
        },
    },
    runtime_hooks=[],
    excludes=['tkinter'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Kaghez',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=os.path.join(out, 'kaghez.ico'),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='Kaghez',
)
