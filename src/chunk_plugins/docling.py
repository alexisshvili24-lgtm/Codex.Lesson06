"""Необязательный Docling запускается в отдельном Python-окружении."""
import json
import os
import subprocess
from pathlib import Path, PurePosixPath
from src.document_structure import prepare_structure, StructureError
from src.chunking import chunk_sections, ChunkingError
from . import PluginError, docling_python

ROOT=Path(__file__).resolve().parents[2]

class DoclingPlugin:
    name = 'docling'
    def __init__(self):
        self.python=docling_python()
        if self.python is None:
            raise PluginError('Окружение Docling не найдено; установите его согласно README.')

    def prepare_file(self,path,text,count):
        suffix=PurePosixPath(path).suffix.lower()
        if suffix not in {'.md','.markdown','.asc','.adoc','.asciidoc','.html','.htm'}:
            from .local import LocalPlugin
            chunks,warnings=LocalPlugin().prepare_file(path,text,count)
            return chunks,['Docling не обрабатывает этот формат; использован локальный разбор.',*warnings]
        env=os.environ.copy()
        env.update({'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','PYTHONIOENCODING':'utf-8','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1'})
        try:
            result=subprocess.run([str(self.python),str(ROOT/'src/chunk_plugins/docling_worker.py')],
                input=json.dumps({'name':PurePosixPath(path).name,'text':text},ensure_ascii=False),
                capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=120,env=env,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except (OSError,subprocess.TimeoutExpired) as exc:
            raise PluginError('Не удалось запустить Docling или истекло время обработки.') from exc
        try:
            response=json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise PluginError('Docling завершился без корректного результата; проверьте окружение.') from exc
        if result.returncode or response.get('error'):
            raise PluginError('Docling не смог разобрать файл: '+str(response.get('error','неизвестная ошибка')))
        try:
            structure=prepare_structure('converted.md',response['markdown'].encode('utf-8'))
            chunks=chunk_sections(structure.blocks,count)
        except (StructureError,ChunkingError) as exc:
            raise PluginError(str(exc)) from exc
        return chunks,['Экспериментальный Docling: проверьте структуру, команды и порядок текста.',*structure.warnings]
