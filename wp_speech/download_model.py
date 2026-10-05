"""Download official small Chinese/English models outside the source tree."""

import argparse
from pathlib import Path
import shutil
import tempfile
from urllib.request import urlopen
import zipfile

MODEL_NAMES = {'cn': 'vosk-model-small-cn-0.22', 'en': 'vosk-model-small-en-us-0.15'}
DEFAULT_MODELS = {
    language: str(Path.home() / '.cache' / 'vosk' / name)
    for language, name in MODEL_NAMES.items()
}
DEFAULT_MODEL = DEFAULT_MODELS['cn']


def check_model(path):
    path = Path(path).expanduser()
    for item in ('am/final.mdl', 'conf/model.conf', 'conf/mfcc.conf'):
        if not (path / item).is_file():
            raise ValueError(f'Incomplete Vosk model: missing {path / item}')
    return path


def download_model(destination=None, language='cn'):
    model_name = MODEL_NAMES[language]
    model_url = 'https://alphacephei.com/vosk/models/' + model_name + '.zip'
    if destination is None:
        destination = DEFAULT_MODELS[language]
    destination = Path(destination).expanduser().absolute()
    if destination.exists():
        check_model(destination)
        print(f'Model already exists: {destination}', flush=True)
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Download/extract beside the target, so interruption never leaves a partial model there.
    with tempfile.TemporaryDirectory(prefix='.vosk-download-', dir=destination.parent) as tmp:
        root = Path(tmp)
        archive = root / 'model.zip'
        print(f'Downloading {model_url}', flush=True)
        with urlopen(model_url, timeout=60) as response, archive.open('wb') as output:
            shutil.copyfileobj(response, output)
        with zipfile.ZipFile(archive) as zipped:
            for member in zipped.infolist():
                target = (root / member.filename).resolve()
                if not target.is_relative_to(root.resolve()):
                    raise ValueError('Unsafe path in model archive')
            zipped.extractall(root)
        extracted = check_model(root / model_name)
        extracted.rename(destination)
    print(f'Model ready: {destination}', flush=True)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--language', choices=['cn', 'en', 'all'], default='cn',
                        help='Model language; all downloads both languages')
    parser.add_argument('--model-dir', default=None,
                        help='Custom destination for a single language model')
    args = parser.parse_args()
    if args.language == 'all' and args.model_dir:
        parser.error('--model-dir requires a single --language (cn or en)')
    try:
        languages = ['cn', 'en'] if args.language == 'all' else [args.language]
        for language in languages:
            download_model(args.model_dir, language)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        parser.exit(1, f'Model download failed: {error}\n')


if __name__ == '__main__':
    main()
