import hashlib
import io
import re
import uuid
from threading import Lock
from datetime import datetime, timezone, date
from html.parser import HTMLParser
from pathlib import PurePath
from urllib.parse import urlsplit
from pypdf import PdfReader
from src import document_repository as store
from src.repository import Repository

MAX_BYTES = 20 * 1024 * 1024
EXTENSIONS = {'.txt', '.md', '.markdown', '.adoc', '.asciidoc', '.asc', '.html', '.htm', '.zip'}

class DocumentError(ValueError):
    pass

class TextHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'head'):
            self.hidden += 1
        elif not self.hidden and tag in ('p', 'div', 'br', 'li', 'pre', 'h1', 'h2', 'h3', 'h4', 'section', 'article'):
            self.parts.append('\n')
    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'head') and self.hidden:
            self.hidden -= 1
        elif not self.hidden and tag in ('p', 'div', 'li', 'pre', 'h1', 'h2', 'h3', 'h4', 'section', 'article'):
            self.parts.append('\n')
    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)

def extract(filename, data):
    suffix = PurePath(filename).suffix.lower()
    if suffix == '.pdf':
        raise DocumentError('Загрузка PDF отключена; используйте текстовый формат.')
    if suffix not in EXTENSIONS:
        raise DocumentError('Неподдерживаемый формат файла.')
    if not data:
        raise DocumentError('Файл пуст.')
    if len(data) > MAX_BYTES:
        raise DocumentError('Размер файла превышает 20 МБ.')
    if suffix == '.zip':
        from src.archive_reader import extract_archive, ArchiveError
        try:
            text = extract_archive(data)
        except ArchiveError as exc:
            raise DocumentError(str(exc)) from exc
    elif suffix == '.pdf':
        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise DocumentError('PDF защищён паролем.')
            text = '\n\n'.join(page.extract_text() or '' for page in reader.pages)
        except DocumentError:
            raise
        except Exception as exc:
            raise DocumentError('Не удалось прочитать PDF: файл повреждён или не поддерживается.') from exc
    else:
        try:
            text = data.decode('utf-16') if data.startswith((b'\xff\xfe', b'\xfe\xff')) else data.decode('utf-8-sig')
        except UnicodeError as exc:
            raise DocumentError('Не удалось прочитать кодировку. Используйте UTF-8 или UTF-16.') from exc
        if '\x00' in text:
            raise DocumentError('Файл содержит недопустимые нулевые символы.')
        if suffix in ('.html', '.htm'):
            parser = TextHTML()
            parser.feed(text)
            text = ''.join(parser.parts)
    if not text.strip():
        raise DocumentError('Документ не содержит извлекаемого текста; OCR не поддерживается.')
    return text

def prepare(filename, data, meta, document_id=None):
    filename = filename.replace('\\', '/').split('/')[-1]
    if not filename or len(filename) > 255:
        raise DocumentError('Некорректное имя файла.')
    title = meta.get('title', '').strip()
    language = meta.get('language', '').strip()
    source_type = meta.get('source_type', '')
    if not title or len(title) > 500 or not language or len(language) > 50 or source_type not in ('official', 'third_party'):
        raise DocumentError('Укажите название, язык и тип источника.')
    version, published, url, commit = (meta.get(k, '').strip() for k in ('version', 'published_at', 'source_url', 'git_commit'))
    if len(version) > 200 or len(commit) > 100 or len(url) > 2048:
        raise DocumentError('Слишком длинные метаданные.')
    if published:
        try:
            date.fromisoformat(published)
        except ValueError as exc:
            raise DocumentError('Дата публикации должна иметь формат ГГГГ-ММ-ДД.') from exc
    if url and (urlsplit(url).scheme not in ('http', 'https') or not urlsplit(url).netloc):
        raise DocumentError('URL должен начинаться с http:// или https://.')
    text = extract(filename, data)
    return {'id': document_id or str(uuid.uuid4()), 'title': title, 'language': language, 'source_type': source_type,
            'version': version, 'published_at': published, 'source_url': url, 'git_commit': commit,
            'filename': filename, 'sha256': hashlib.sha256(data).hexdigest(), 'uploaded_at': datetime.now(timezone.utc).isoformat(),
            'status': 'extracted', 'chunk_count': 0, 'extracted_text': text, 'original': data}
_document_write_lock = Lock()

def save_document(filename, data, meta, request_id, document_id=None):
    if len(data) > MAX_BYTES:
        raise DocumentError('Размер файла превышает 20 МБ.')
    with _document_write_lock:
        duplicate = store.find_duplicate(hashlib.sha256(data).hexdigest(), document_id)
        if duplicate:
            raise DocumentError(f"Этот файл уже загружен: «{duplicate['title']}» (ID {duplicate['id']}).")
        values = prepare(filename, data, meta, document_id)
        return store.write_document(values, request_id, replace=bool(document_id))