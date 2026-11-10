"""Локальная подготовка текста и разбиение по структуре."""
from pathlib import PurePosixPath
from dataclasses import replace
import re
from src.document_structure import prepare_structure, StructureError
from src.chunking import chunk_sections, ChunkingError
from . import PluginError

def _clean_asciidoc(blocks):
    """Удаляет управляющие элементы только из обычного текста, не меняя примеры кода."""
    cleaned = []
    skipped_includes = False
    for block in blocks:
        if block.kind not in ('paragraph', 'list'):
            if re.search(r'(?m)^\s*include::[^\n]+\[.*\]\s*$', block.text):
                skipped_includes = True
            cleaned.append(block)
            continue
        lines = []
        for line in block.text.splitlines(keepends=True):
            stripped = line.strip()
            if re.fullmatch(r'include::[^\n]+\[.*\]', stripped):
                skipped_includes = True
                continue
            if re.fullmatch(r'(?:\[\[[^\]]+\]\]|\[#[^\]]+\]|\[appendix\]|={4,})', stripped, re.I):
                continue
            line = re.sub(r'\(\(\([^\n]*?\)\)\)', '', line)
            line = re.sub(r'\[\[[^\]\n]+\]\]', '', line)
            lines.append(line)
        text = ''.join(lines)
        if text.strip():
            cleaned.append(replace(block, text=text))
    return cleaned, skipped_includes

class LocalPlugin:
    name = 'local'
    def prepare_file(self, path, text, count):
        ext=PurePosixPath(path).suffix.lower()
        supported={'.txt','.md','.markdown','.adoc','.asciidoc','.asc','.html','.htm'}
        asciidoc = ext in {'.asc', '.adoc', '.asciidoc'} or path.lower().endswith(('.asc.txt', '.adoc.txt', '.asciidoc.txt'))
        parse_name=path[:-4] if asciidoc and ext == '.txt' else path if ext in supported else 'text.txt'
        warnings=[] if ext in supported else ['Формат разобран как обычный текст.']
        try:
            structure=prepare_structure(parse_name,text.encode('utf-8'))
            warnings.extend(structure.warnings)
            blocks, skipped_includes = _clean_asciidoc(structure.blocks) if asciidoc else (structure.blocks, False)
            if skipped_includes:
                warnings.append('Директивы include не раскрываются; содержимое подключаемых файлов обрабатывается отдельно, если оно загружено.')
            chunks=chunk_sections(blocks,count,line_fallback=ext in {'.json','.jsonl','.csv','.tsv','.yaml','.yml','.xml','.ini','.cfg'})
        except StructureError as exc:
            if str(exc)=='Документ не содержит текста.':
                return [], warnings+['Извлекаемого текста нет; файл пропущен.']
            raise PluginError(str(exc)) from exc
        except ChunkingError as exc:
            raise PluginError(str(exc)) from exc
        return chunks,warnings
