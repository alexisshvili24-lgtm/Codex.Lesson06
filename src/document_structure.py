"""Подготовка документа к чанкингу без сетевых вызовов и изменения исходника."""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, asdict, replace
from html.parser import HTMLParser
from pathlib import PurePath
from statistics import median
from pypdf import PdfReader

@dataclass(frozen=True)
class Block:
    kind: str
    text: str
    page: int | None = None
    level: int | None = None

@dataclass(frozen=True)
class PreparedDocument:
    blocks: list[Block]
    warnings: list[str]
    status: str
    def to_dict(self):
        return {'blocks': [asdict(block) for block in self.blocks], 'warnings': self.warnings, 'status': self.status}

class StructureError(ValueError):
    pass

def _decode(data):
    try:
        return data.decode('utf-16') if data.startswith((b'\xff\xfe', b'\xfe\xff')) else data.decode('utf-8-sig')
    except UnicodeError as exc:
        raise StructureError('Кодировка документа не поддерживается.') from exc

def _text_blocks(text, markup):
    lines = text.splitlines(keepends=True)
    blocks, pending, block_warnings = [], [], []
    fence = None
    def flush(kind='paragraph'):
        if pending:
            text = ''.join(pending)
            if not text.strip() and blocks:
                blocks[-1] = replace(blocks[-1], text=blocks[-1].text + text)
            else:
                if markup and kind == 'paragraph' and re.search(r'(?m)^\s*(?:[-*+]\s+|\d+[.)]\s+|[a-zA-Z][.)]\s+)', text):
                    kind = 'list'
                blocks.append(Block(kind, text))
            pending.clear()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if markup and re.fullmatch(r'\[(?:source[^\]]*|NOTE|WARNING|TIP|IMPORTANT|CAUTION)\]', stripped, re.I) and i+1 < len(lines) and lines[i+1].strip() in ('----','....','====','****','____','|==='):
            flush()
            delimiter=lines[i+1].strip(); start=i; i+=2
            while i < len(lines) and lines[i].strip()!=delimiter: i+=1
            closed=i < len(lines)
            if closed: i+=1
            else: block_warnings.append('Незакрытый блок AsciiDoc: проверьте разметку.')
            kind='code' if stripped.lower().startswith('[source') else 'warning'
            blocks.append(Block(kind, ''.join(lines[start:i])))
            continue
        if fence:
            pending.append(line)
            if stripped.startswith(fence):
                flush('code'); fence = None
            i += 1; continue
        if markup and (stripped.startswith('```') or stripped in ('----', '....', '|===')):
            flush(); fence = '```' if stripped.startswith('```') else stripped
            pending.append(line); i += 1; continue
        match = re.match(r'^(#{1,6}|={1,6})\s+(.+?)\s*$', line) if markup else None
        underline = i + 1 < len(lines) and re.fullmatch(r'\s*(={3,}|-{3,}|\^{3,}|~{3,})\s*', lines[i+1])
        if match:
            flush(); blocks.append(Block('heading', line, level=len(match.group(1)))); i += 1; continue
        if markup and stripped and underline and len(stripped) <= 80 and not stripped.endswith(('.', ':', ';', ',', '!', '?')) and not stripped.startswith(('[', ':')) and (i == 0 or not lines[i-1].strip()):
            flush(); marker = lines[i+1].strip()[0]
            blocks.append(Block('heading', line + lines[i+1], level={'=':1, '-':2, '^':3, '~':4}[marker])); i += 2; continue
        if not stripped:
            pending.append(line); flush(); i += 1; continue
        pending.append(line); i += 1
    flush('code' if fence else 'paragraph')
    return blocks, block_warnings + (['Незакрытый блок кода или таблицы: проверьте разметку.'] if fence else [])

class _HTMLBlocks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = []; self.pending = []; self.kind = 'paragraph'; self.level = None; self.hidden = 0
    def flush(self):
        text = ''.join(self.pending)
        if text.strip(): self.blocks.append(Block(self.kind, text, level=self.level))
        self.pending = []; self.kind = 'paragraph'; self.level = None
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'head'): self.hidden += 1; return
        if self.hidden: return
        if tag in ('p','pre','li','h1','h2','h3','h4','h5','h6'):
            self.flush(); self.kind = 'heading' if tag.startswith('h') else 'code' if tag == 'pre' else 'list' if tag == 'li' else 'paragraph'
            self.level = int(tag[1]) if self.kind == 'heading' else None
        elif tag == 'br': self.pending.append('\n')
    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'head') and self.hidden: self.hidden -= 1; return
        if not self.hidden and tag in ('p','pre','li','h1','h2','h3','h4','h5','h6'): self.flush()
    def handle_data(self, data):
        if not self.hidden: self.pending.append(data)

def _pdf_blocks(data):
    try: reader = PdfReader(io.BytesIO(data))
    except Exception as exc: raise StructureError('Не удалось открыть PDF.') from exc
    if reader.is_encrypted: raise StructureError('PDF защищён паролем.')
    blocks, warnings = [], []
    for page_number, page in enumerate(reader.pages, 1):
        fragments = []
        def visitor(text, cm, tm, font, size):
            if text and text.strip():
                fragments.append((text, float(tm[4]), float(tm[5]), float(size), str(font.get('/BaseFont', '')) if font else ''))
            elif text and fragments and abs(fragments[-1][2] - float(tm[5])) < 1.0 and '\n' not in text and '\r' not in text:
                fragments.append((text, float(tm[4]), float(tm[5]), float(size), str(font.get('/BaseFont', '')) if font else ''))
        try: page.extract_text(visitor_text=visitor)
        except Exception as exc: raise StructureError(f'Ошибка чтения страницы {page_number} PDF.') from exc
        if not fragments:
            warnings.append(f'Страница {page_number}: текст не извлечён; возможны изображения или скан.')
            continue
        sizes = [size for text,x,y,size,font in fragments if size > 0]
        base = median(sizes) if sizes else 0
        lines = []
        for text,x,y,size,font in fragments:
            if lines and abs(lines[-1]['y']-y) < 1.0:
                lines[-1]['parts'].append(text); lines[-1]['xs'].append(x); lines[-1]['sizes'].append(size); lines[-1]['fonts'].append(font)
            else:
                lines.append({'y':y, 'parts':[text], 'xs':[x], 'sizes':[size], 'fonts':[font]})
        # Порядок возврата фрагментов pypdf может нарушаться на колонках и сложных макетах.
        if any(lines[i+1]['y'] > lines[i]['y'] + 30 for i in range(len(lines)-1)):
            warnings.append(f'Страница {page_number}: возможен многостолбцовый или сложный макет; проверьте порядок текста.')
        pending=[]; last_y=None; last_size=None; pending_kind='paragraph'
        def flush():
            if pending:
                blocks.append(Block(pending_kind, '\n'.join(pending), page=page_number)); pending.clear()
        for line in lines:
            raw_text=''.join(line['parts']).rstrip()
            text=raw_text.strip()
            if not text: continue
            if line['y'] < 30 and re.fullmatch(r'\d{1,4}', text):
                flush(); blocks.append(Block('page_number', text, page=page_number)); last_y=None; continue
            size=max(line['sizes'])
            if base and size >= base*1.22 and len(text)<180:
                flush(); blocks.append(Block('heading', text, page=page_number, level=None)); last_y=None; continue
            mono = sum(len(part.strip()) for part, font in zip(line['parts'], line['fonts']) if re.search(r'mono|courier|mplus1mn', font, re.I))
            line_kind = 'code' if mono >= max(1, len(text) * 0.7) else 'paragraph'
            if pending and (line_kind != pending_kind or (line_kind != 'code' and last_y is not None and abs(last_y-line['y']) > max(20, (last_size or base)*2.05))):
                flush()
            pending_kind = line_kind
            pending.append(raw_text if line_kind == 'code' else text); last_y=line['y']; last_size=size
        flush()
    if not blocks: raise StructureError('PDF не содержит извлекаемого текста.')
    warnings.append('PDF: границы абзацев, заголовков и порядок чтения определены автоматически и требуют проверки.')
    return blocks, warnings

def prepare_structure(filename: str, original: bytes) -> PreparedDocument:
    suffix=PurePath(filename).suffix.lower()
    if suffix == '.pdf': blocks, warnings = _pdf_blocks(original)
    elif suffix in ('.html', '.htm'):
        parser=_HTMLBlocks(); parser.feed(_decode(original)); parser.flush()
        blocks, warnings = parser.blocks, []
    elif suffix in ('.txt','.md','.markdown','.adoc','.asciidoc','.asc'):
        blocks, warnings = _text_blocks(_decode(original), suffix != '.txt')
        if suffix == '.txt': warnings.append('TXT: заголовки не размечены; структура разделов может отсутствовать.')
    else: raise StructureError('Неподдерживаемый формат документа.')
    if not blocks: raise StructureError('Документ не содержит текста.')
    return PreparedDocument(blocks, warnings, 'needs_review' if warnings else 'prepared')