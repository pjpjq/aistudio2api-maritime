import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def matches(directory, version):
    ini = directory / 'application.ini'
    return (os.access(directory / 'camoufox-bin', os.X_OK) and ini.is_file()
            and f'Version={version}' in ini.read_text().splitlines())


def main():
    url = os.environ['CAMOUFOX_URL']
    checksum = os.environ['CAMOUFOX_SHA256']
    version = url.split('/')[-2].removeprefix('v')
    legacy = Path.cwd() / 'runtime/camoufox'
    # Upstream replaces its default install directory; never download into the rollback cache.
    target = legacy if matches(legacy, version) else legacy.with_name(f'camoufox-{version}-{checksum}')
    if sys.argv[1:] == ['--path']:
        print(target / 'camoufox-bin')
        return
    if matches(target, version):
        return
    with tempfile.TemporaryDirectory(dir=target.parent) as temporary:
        archive = Path(temporary) / 'camoufox.zip'
        stage = Path(temporary) / 'runtime'
        subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error', '--connect-timeout', '15',
                        '--max-time', '240', '--retry', '2', '--retry-max-time', '240',
                        '--output', str(archive), url], check=True)
        with archive.open('rb') as source:
            if hashlib.file_digest(source, 'sha256').hexdigest() != checksum:
                raise RuntimeError('Camoufox archive SHA-256 mismatch')
        subprocess.run(['unzip', '-q', str(archive), '-d', str(stage)], check=True)
        (stage / 'camoufox-bin').chmod(0o755)
        if not matches(stage, version):
            raise RuntimeError('Camoufox archive version mismatch')
        try:
            stage.rename(target)
        except OSError:
            if not matches(target, version):
                raise


if __name__ == '__main__':
    main()
