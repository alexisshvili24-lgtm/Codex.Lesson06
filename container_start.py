"""Подготавливает постоянное хранилище перед запуском приложения."""
import os
from pathlib import Path
import shutil

os.umask(0o077)
data = Path('/app/data')
(data / 'tmp').mkdir(parents=True, exist_ok=True)
tokenizer = data / 'tokenizers' / 'bge-m3-tokenizer.json'
tokenizer.parent.mkdir(parents=True, exist_ok=True)
if not tokenizer.exists():
    shutil.copyfile('/opt/bge-m3-tokenizer.json', tokenizer)
os.execvp('python', ['python', '-m', 'uvicorn', 'app:app', '--host', '0.0.0.0', '--port', '8025', '--workers', '1'])
