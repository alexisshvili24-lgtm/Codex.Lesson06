"""Экспериментальный чанкинг: вызов только после проверки структуры документа."""
from dataclasses import dataclass
from pathlib import Path
import re
from tokenizers import Tokenizer

@dataclass(frozen=True)
class Chunk:
    section: str
    text: str
    tokens: int
    chapter: str = ''
    subsection: str = ''

class ChunkingError(ValueError):
    pass

def bge_counter(path):
    tokenizer = Tokenizer.from_str(Path(path).read_text(encoding='utf-8-sig'))
    return lambda text: len(tokenizer.encode(text, add_special_tokens=True).ids)

def _sentences(text):
    text = text.strip()
    parts = []
    start = 0
    # Сокращения перед именем или названием не завершают предложение.
    non_terminal = re.compile(r'(?:^|\s)(?:г|ул|им|рис|стр|см|dr|mr|mrs|ms|prof)\.$', re.I)
    for boundary in re.finditer(r'(?<=[.!?])\s+(?=[А-ЯЁA-Z«"0-9])', text):
        prefix = text[start:boundary.start()]
        if non_terminal.search(prefix):
            continue
        parts.append(prefix.strip())
        start = boundary.end()
    if text[start:].strip():
        parts.append(text[start:].strip())
    return parts

def _list_items(text):
    """Разделяет список по пунктам верхнего уровня, сохраняя вложенные пункты."""
    matches = list(re.finditer(r'(?m)^( *)(?:[-*+]\s+|\d+[.)]\s+|[a-zA-Z][.)]\s+)', text))
    if not matches:
        return []
    indent = min(len(match.group(1)) for match in matches)
    boundaries = [match.start() for match in matches if len(match.group(1)) == indent]
    if len(boundaries) < 2:
        return []
    boundaries[0] = 0
    return [text[start:end].strip() for start, end in zip(boundaries, boundaries[1:] + [len(text)])]

def _overlap_start(units, start, end, count, limit):
    selected=[]
    result=end-1
    for index in range(end-1, start-1, -1):
        for sentence in reversed(_sentences(units[index][0])):
            if selected and count(' '.join([sentence, *selected])) > limit:
                return result
            selected.insert(0, sentence)
            result=index
    return result
def chunk_sections(blocks, count, target=500, soft_limit=800, overlap_ratio=0.15, hard_limit=8192, line_fallback=False):
    if target <= 0 or soft_limit < target or hard_limit < soft_limit or not 0 < overlap_ratio < 1:
        raise ValueError('Некорректные параметры чанкинга.')
    sections=[]; title=''; chapter=''; subsection=''; units=[]
    for block in blocks:
        if block.kind == 'heading':
            if units: sections.append((chapter, title, subsection, units)); units=[]
            raw=block.text.strip()
            mark=re.match(r'^(=+|#+)\s+(.+)', raw)
            if mark:
                level=len(mark.group(1)) - (1 if mark.group(1).startswith('=') else 0)
                value=mark.group(2).splitlines()[0].strip()
            elif block.level:
                level=block.level; value=raw.splitlines()[0].strip()
            else:
                level=2; value=raw
            if level <= 1: chapter=value; title=''; subsection=''
            elif level == 2: title=value; subsection=''
            else: subsection=value
            continue
        if block.kind == 'page_number' or not block.text.strip(): continue
        text=block.text.strip()
        if block.kind == 'code' and units and units[-1][0].rstrip().endswith(':'):
            text=units.pop()[0]+'\n\n'+text
        if count(text)>hard_limit and block.kind == 'list':
            items = _list_items(text)
            if len(items) < 2 or any(count(item) > hard_limit for item in items):
                raise ChunkingError('Список невозможно безопасно разделить по пунктам; требуется проверка.')
            units.extend((item, True) for item in items)
            continue
        if count(text)>hard_limit and block.kind in ('code', 'warning'):
            raise ChunkingError('Смысловой блок превышает физический предел модели; требуется проверка.')
        if count(text)>soft_limit and block.kind not in ('code', 'warning', 'list'):
            parts=_sentences(text)
            if len(parts)<2:
                parts=[line for line in text.splitlines(keepends=True) if line.strip()] if line_fallback else []
                if len(parts)<2:
                    if count(text) <= hard_limit:
                        units.append((text, False))
                        continue
                    raise ChunkingError('Длинное предложение невозможно безопасно разделить автоматически.')
            if any(count(part)>hard_limit for part in parts):
                raise ChunkingError('Предложение превышает физический предел модели; требуется проверка.')
            units.extend((part, False) for part in parts)
        else:
            units.append((text, block.kind in ('code', 'warning', 'list')))
    if units: sections.append((chapter,title,subsection,units))
    chunks=[]
    for chapter, title, subsection, paragraphs in sections:
        start=0
        overlap=''
        while start < len(paragraphs):
            end=start+1
            def render(stop):
                core='\n\n'.join(p[0] for p in paragraphs[start:stop])
                return (overlap+'\n\n' if overlap else '')+core
            while end < len(paragraphs):
                current=count(render(end)); size=count(render(end+1))
                if size>soft_limit or (size>target and abs(size-target)>=abs(current-target)):
                    break
                end+=1
            text=render(end); n=count(text)
            if n>hard_limit: raise ChunkingError('Чанк с обязательным перекрытием превышает предел модели.')
            chunks.append(Chunk(title,text,n,chapter,subsection))
            if end==len(paragraphs): break
            last, atomic = paragraphs[end-1]
            if atomic:
                overlap=last
            else:
                selected=[]; limit=max(1,round(n*overlap_ratio))
                for sentence in reversed(_sentences(last)):
                    candidate=' '.join([sentence,*selected])
                    if selected and count(candidate)>limit: break
                    selected.insert(0,sentence)
                overlap=' '.join(selected)
            if not overlap:
                raise ChunkingError('Не удалось определить перекрытие; требуется проверка.')
            start=end
    return chunks
