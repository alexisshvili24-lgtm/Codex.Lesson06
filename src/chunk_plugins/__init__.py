"""Реестр подготовщиков документов; тяжёлые зависимости загружаются по запросу."""
from importlib.metadata import entry_points
from pathlib import Path
from typing import Protocol

ROOT = Path(__file__).resolve().parents[2]

class ChunkPlugin(Protocol):
    name: str
    def prepare_file(self, path: str, text: str, count): ...

class PluginError(ValueError):
    pass

def docling_python():
    for base in (ROOT / '.venv-docling', ROOT / '.tmp' / 'docling-lab'):
        for part in ('Scripts/python.exe', 'bin/python'):
            candidate=base / part
            if candidate.is_file(): return candidate
    return None

def installed_plugins():
    plugins=[{'id':'local','name':'Локальный обработчик','available':True},
             {'id':'docling','name':'Docling (экспериментальный)','available':docling_python() is not None}]
    builtins={'local','docling'}
    names=[item.name for item in entry_points(group='git_support.chunk_plugins') if item.name not in builtins]
    for name in sorted(set(names)):
        plugins.append({'id':name,'name':name,'available':names.count(name)==1})
    return plugins

def get_plugin(name):
    if name == 'local':
        from .local import LocalPlugin
        return LocalPlugin()
    if name == 'docling':
        from .docling import DoclingPlugin
        return DoclingPlugin()
    matches = entry_points(group='git_support.chunk_plugins', name=name)
    if len(matches) > 1:
        raise PluginError(f'Найдено несколько плагинов с именем {name}.')
    if matches:
        try:
            return matches[0].load()()
        except Exception as exc:
            raise PluginError(f'Не удалось загрузить плагин {name}: {exc}') from exc
    raise PluginError(f'Неизвестный плагин подготовки: {name}.')
