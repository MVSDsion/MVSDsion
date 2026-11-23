"""Build MVSDsion as one .exe with the fast Rust launcher (Windows).

1. PyInstaller builds the program as a folder (MVSDSION_ONEDIR=1).
2. The folder is packed into a .zip.
3. Cargo builds rust/launcher with the .zip inside (unpacked once per version).
4. The launcher gets MVSDsion's icon and is copied to dist/.

Run:  uv run --frozen python scripts/build_launcher.py
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / 'dist' / 'MVSDsion-app'
PAYLOAD = ROOT / 'build' / 'mvsdsion-payload.zip'
LAUNCHER = ROOT / 'rust' / 'launcher'
ICON = ROOT / 'src' / 'fleasion' / 'fleasionlogoHR.ico'


def _cargo() -> str:
    found = shutil.which('cargo') or str(Path.home() / '.cargo' / 'bin' / 'cargo.exe')
    if not Path(found).exists():
        raise SystemExit('Rust (cargo) is not installed: https://rustup.rs')
    return found


def build_folder() -> None:
    if APP_DIR.exists():
        shutil.rmtree(APP_DIR)
    environment = {**os.environ, 'MVSDSION_ONEDIR': '1'}
    subprocess.run([sys.executable, '-m', 'fleasion.scripts.build'], cwd=ROOT, env=environment, check=True)
    if not (APP_DIR / 'MVSDsion.exe').is_file():
        raise SystemExit(f'The folder build is missing: {APP_DIR}')


def pack_folder() -> str:
    PAYLOAD.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(PAYLOAD, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(APP_DIR.rglob('*')):
            if path.is_file():
                archive.write(path, path.relative_to(APP_DIR).as_posix())
    digest = hashlib.sha256(PAYLOAD.read_bytes()).hexdigest()[:16]
    from fleasion.version import read_project_version

    return f'{read_project_version()}-{digest}'


def build_launcher(build_id: str) -> Path:
    environment = {**os.environ, 'MVSDSION_PAYLOAD': str(PAYLOAD), 'MVSDSION_BUILD_ID': build_id}
    subprocess.run([_cargo(), 'build', '--release'], cwd=LAUNCHER, env=environment, check=True)
    return LAUNCHER / 'target' / 'release' / 'mvsdsion-launcher.exe'


def finish(launcher: Path) -> Path:
    from fleasion.version import read_project_version

    target = ROOT / 'dist' / f'MVSDsion-v{read_project_version()}+local-Windows.exe'
    shutil.copy2(launcher, target)
    from PyInstaller import config
    from PyInstaller.utils.win32.icon import CopyIcons

    config.CONF.setdefault('workpath', str(ROOT / 'build'))
    CopyIcons(str(target), str(ICON))
    return target


def main() -> int:
    if sys.platform != 'win32':
        raise SystemExit('The Rust launcher is for Windows builds.')
    build_folder()
    build_id = pack_folder()
    target = finish(build_launcher(build_id))
    size = target.stat().st_size / 1024 / 1024
    print(f'Built {target} ({size:.1f} MB, build {build_id})')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
