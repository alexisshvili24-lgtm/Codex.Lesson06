"""Формирование предварительных чанков отдельно для каждого источника."""
import hashlib
from pathlib import PurePosixPath
from src.archive_reader import read_archive_files, ArchiveError
from src.chunk_plugins import get_plugin, PluginError

class PreparationError(ValueError):
    pass

def prepare_chunks(metadata, filename, original, count, plugin=None):
    suffix=PurePosixPath(filename).suffix.lower()
    if suffix=='.pdf': raise PreparationError('PDF исключён из обработки; используйте текстовый источник.')
    name = 'local' if plugin is None else plugin
    try:
        processor = get_plugin(name)
    except PluginError as exc:
        raise PreparationError(str(exc)) from exc
    try:
        files=read_archive_files(original) if suffix=='.zip' else [(filename, original.decode('utf-16') if original.startswith((b'\xff\xfe',b'\xfe\xff')) else original.decode('utf-8-sig'))]
    except (ArchiveError, UnicodeError) as exc: raise PreparationError(str(exc)) from exc
    result=[]; warnings=[]
    for path,text in files:
        try:
            chunks,file_warnings=processor.prepare_file(path,text,count)
            warnings.extend(f'{path}: {message}' for message in file_warnings)
        except PluginError as exc:
            raise PreparationError(f'{path}: {exc}') from exc
        except Exception as exc:
            raise PreparationError(f'{path}: ошибка плагина {name}: {exc}') from exc
        if not chunks:
            warnings.append(f'{path}: нет текстовых блоков для чанков.')
        for index,chunk in enumerate(chunks):
            digest=hashlib.sha256(chunk.text.encode('utf-8')).hexdigest()
            identity='\0'.join((name, str(metadata['id']), path, str(index), digest))
            result.append({'plugin':name, 'chunk_id':hashlib.sha256(identity.encode('utf-8')).hexdigest(),
                           'document_id':metadata['id'], 'document_title':metadata.get('title',''),
                           'source_file':path, 'source_type':metadata.get('source_type',''),
                           'source_url':metadata.get('source_url',''), 'document_version':metadata.get('version',''),
                           'language':metadata.get('language',''), 'chapter':chunk.chapter, 'section':chunk.section, 'subsection':chunk.subsection,
                           'chunk_index':index, 'text':chunk.text, 'text_hash':digest, 'tokens':chunk.tokens})
    if not result: raise PreparationError('Не найдено пригодного текста для чанкинга.')
    return {'plugin':name,'chunks':result,'warnings':warnings}