"""Download the sherpa-onnx Melo Chinese/English TTS model into the user cache."""

import argparse
from pathlib import Path
import shutil
import tarfile
import tempfile
from urllib.request import urlopen

MODEL_NAME = 'vits-melo-tts-zh_en'
MODEL_URL = ('https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/'
             + MODEL_NAME + '.tar.bz2')
DEFAULT_TTS_MODEL = str(Path.home() / '.cache' / 'sherpa-onnx' / MODEL_NAME)


def check_tts_model(path):
    path = Path(path).expanduser()
    for name in ('model.onnx', 'tokens.txt', 'lexicon.txt', 'date.fst', 'number.fst', 'phone.fst'):
        file = path / name
        if not file.is_file() or file.stat().st_size == 0:
            raise ValueError(f'Incomplete TTS model: missing or empty {file}')
    if not (path / 'dict').is_dir():
        raise ValueError(f'Incomplete TTS model: missing {path / "dict"}')
    return path


def extract_model(archive, destination):
    """Extract only regular files/directories with paths confined to destination."""
    root = Path(destination).resolve()
    with tarfile.open(archive, 'r:bz2') as bundle:
        for member in bundle:
            target = (root / member.name).resolve()
            if not target.is_relative_to(root) or not (member.isfile() or member.isdir()):
                raise ValueError(f'Unsupported or unsafe archive entry: {member.name}')
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.extractfile(member) as source, target.open('wb') as output:
                    shutil.copyfileobj(source, output)


def download_tts_model(destination=DEFAULT_TTS_MODEL):
    destination = Path(destination).expanduser().absolute()
    if destination.exists():
        check_tts_model(destination)
        print(f'TTS model already exists: {destination}', flush=True)
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.tts-download-', dir=destination.parent) as tmp:
        root = Path(tmp)
        archive = root / 'model.tar.bz2'
        print(f'Downloading {MODEL_URL}', flush=True)
        with urlopen(MODEL_URL, timeout=60) as response, archive.open('wb') as output:
            received = 0
            report_at = 16 * 1024 * 1024
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                output.write(block)
                received += len(block)
                if received >= report_at:
                    print(f'Downloaded {received // (1024 * 1024)} MiB', flush=True)
                    report_at += 16 * 1024 * 1024
        extract_model(archive, root)
        check_tts_model(root / MODEL_NAME).rename(destination)
    print(f'TTS model ready: {destination}', flush=True)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-dir', default=DEFAULT_TTS_MODEL)
    args = parser.parse_args()
    try:
        download_tts_model(args.model_dir)
    except (OSError, ValueError, tarfile.TarError) as error:
        parser.exit(1, f'TTS model download failed: {error}\n')


if __name__ == '__main__':
    main()
