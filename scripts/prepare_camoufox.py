import hashlib
import os
import subprocess
import sys
import tempfile
from contextlib import suppress
from pathlib import Path


def matches(directory, version):
    ini = directory / 'application.ini'
    return (os.access(directory / 'camoufox-bin', os.X_OK) and ini.is_file()
            and f'Version={version}' in ini.read_text().splitlines())


def extract_verified(url, checksum, stage):
    digest = hashlib.sha256()
    stage.mkdir()
    # Keep the archive off disk: the persistent volume only has room for the extracted browser.
    with subprocess.Popen(['curl', '--fail', '--location', '--silent', '--show-error',
                           '--connect-timeout', '15', '--max-time', '480', url], stdout=subprocess.PIPE) as download, \
         subprocess.Popen(['bsdtar', '-xf', '-', '-C', str(stage)], stdin=subprocess.PIPE) as extract:
        try:
            for chunk in iter(lambda: download.stdout.read(1024 * 1024), b''):
                digest.update(chunk)
                if not extract.stdin.closed:
                    try:
                        extract.stdin.write(chunk)
                    except BrokenPipeError:
                        # A stream reader can exit before the ZIP directory/trailer. Hash it anyway.
                        with suppress(BrokenPipeError):
                            extract.stdin.close()
            with suppress(BrokenPipeError):
                extract.stdin.close()
            download_status, extract_status = download.wait(), extract.wait()
            if download_status or extract_status:
                raise RuntimeError('Camoufox download or extraction failed')
        finally:
            for process in (download, extract):
                if process.poll() is None:
                    process.kill()
    if digest.hexdigest() != checksum:
        raise RuntimeError('Camoufox archive SHA-256 mismatch')


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
        stage = Path(temporary) / 'runtime'
        extract_verified(url, checksum, stage)
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
