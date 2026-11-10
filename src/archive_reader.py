"""Чтение текстовых файлов ZIP по отдельности, без распаковки и выполнения ссылок."""
import io
import stat
import zipfile
from pathlib import PurePosixPath

class ArchiveError(ValueError):
    pass

TEXT_EXTENSIONS = {'.asc', '.adoc', '.asciidoc', '.txt', '.md', '.markdown', '.html', '.htm', '.rst', '.json', '.jsonl', '.csv', '.tsv', '.yaml', '.yml', '.xml', '.ini', '.cfg'}
MAX_ENTRIES = 3000
MAX_UNPACKED = 300 * 1024 * 1024
MAX_TEXT = 30 * 1024 * 1024

def read_archive_files(data):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_ENTRIES or sum(x.file_size for x in entries) > MAX_UNPACKED:
                raise ArchiveError('Архив превышает допустимый объём или количество файлов.')
            seen = set()
            selected = []
            for item in entries:
                name = item.filename
                parts = PurePosixPath(name).parts
                if '\\' in name or name.startswith('/') or any(p in ('..', '.') or ':' in p for p in parts):
                    raise ArchiveError('Недопустимый путь внутри архива.')
                if stat.S_ISLNK(item.external_attr >> 16):
                    raise ArchiveError('Символические ссылки в архиве не поддерживаются.')
                if item.is_dir(): continue
                if name in seen: raise ArchiveError('В архиве повторяются пути файлов.')
                seen.add(name)
                if PurePosixPath(name).suffix.lower() not in TEXT_EXTENSIONS: continue
                if item.flag_bits & 1: raise ArchiveError('Зашифрованный текстовый файл не поддерживается: ' + name)
                selected.append(item)
            progit_roots = {str(PurePosixPath(item.filename).parent) for item in selected if PurePosixPath(item.filename).name.lower() == 'progit.asc'}
            selected = [item for item in selected if not any(item.filename == (root + '/book/contributors.asc' if root != '.' else 'book/contributors.asc') for root in progit_roots)]
            if not selected: raise ArchiveError('В архиве нет поддерживаемых текстовых файлов.')
            if sum(item.file_size for item in selected) > MAX_TEXT:
                raise ArchiveError('Текст архива превышает допустимый размер.')
            parts = []
            for item in sorted(selected, key=lambda value: value.filename):
                try:
                    raw=archive.read(item)
                    text=raw.decode('utf-16') if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else raw.decode('utf-8-sig')
                except (UnicodeError, RuntimeError, zipfile.BadZipFile) as exc:
                    raise ArchiveError('Не удалось прочитать текстовый файл: ' + item.filename) from exc
                if '\x00' in text: raise ArchiveError('Недопустимые нулевые символы в файле: ' + item.filename)
                if text.strip():
                    parts.append((item.filename, text))
            if not parts: raise ArchiveError('Текстовые файлы архива пусты.')
            return parts
    except (zipfile.BadZipFile, OSError, EOFError) as exc:
        raise ArchiveError('Не удалось прочитать ZIP-архив.') from exc

def extract_archive(data):
    return '\n\n'.join('=== Файл архива: ' + name + '\n\n' + text for name, text in read_archive_files(data))