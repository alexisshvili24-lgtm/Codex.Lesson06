"""Дочерний процесс преобразования; stdout содержит только JSON."""
import io,json,sys
from pathlib import Path
# Не позволять соседнему адаптеру docling.py затенять пакет docling.
sys.path[0]=str(Path(__file__).resolve().parents[2])

def main():
    try:
        from docling.document_converter import DocumentConverter
        from docling_core.types.io import DocumentStream
        request=json.load(sys.stdin)
        stream=DocumentStream(name=request['name'],stream=io.BytesIO(request['text'].encode('utf-8')))
        result=DocumentConverter().convert(stream,raises_on_error=False)
        if result.status.name!='SUCCESS':
            message='; '.join(str(item.error_message) for item in result.errors) or str(result.status)
            raise ValueError(message)
        print(json.dumps({'markdown':result.document.export_to_markdown()},ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'error':str(exc)},ensure_ascii=False))
        return 1
    return 0
if __name__=='__main__':
    sys.exit(main())
