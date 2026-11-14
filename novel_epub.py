"""Generate a minimal standards-compliant EPUB 3 archive without extra dependencies."""

from html import escape
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile


def export_epub(store, target):
    """Atomically export committed chapters to EPUB; keep the SQLite source intact."""
    import os
    import tempfile

    task = store.task()
    book_name = task["book_name"]
    chapters = list(store.connection.execute(
        "SELECT title, content FROM chapters ORDER BY position"
    ))
    if not chapters:
        raise ValueError("没有可导出的章节。")

    manifest = []
    spine = []
    navigation = []
    with tempfile.NamedTemporaryFile(
        mode="wb", suffix=".epub.tmp", prefix=".novel-export-",
        dir=target.parent, delete=False
    ) as scratch:
        temporary = Path(scratch.name)
    try:
        with ZipFile(temporary, "w") as book:
            book.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
            book.writestr("META-INF/container.xml", (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<container version="1.0" '
                'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                '<rootfiles><rootfile full-path="EPUB/package.opf" '
                'media-type="application/oebps-package+xml"/></rootfiles></container>'
            ))
            for index, chapter in enumerate(chapters, 1):
                filename = f"chapter-{index:05d}.xhtml"
                title = escape(chapter["title"])
                paragraphs = "".join(
                    f"<p>{escape(part)}</p>"
                    for part in chapter["content"].split("\n\n") if part.strip()
                )
                book.writestr("EPUB/" + filename, (
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN">'
                    f'<head><title>{title}</title></head><body><h1>{title}</h1>'
                    f'{paragraphs}</body></html>'
                ), compress_type=ZIP_DEFLATED)
                manifest.append(
                    f'<item id="c{index}" href="{filename}" '
                    'media-type="application/xhtml+xml"/>'
                )
                spine.append(f'<itemref idref="c{index}"/>')
                navigation.append(f'<li><a href="{filename}">{title}</a></li>')
            book.writestr("EPUB/nav.xhtml", (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<html xmlns="http://www.w3.org/1999/xhtml" '
                'xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="zh-CN">'
                '<head><title>目录</title></head><body>'
                '<nav epub:type="toc" id="toc"><h1>目录</h1><ol>'
                + "".join(navigation) + '</ol></nav></body></html>'
            ), compress_type=ZIP_DEFLATED)
            manifest.insert(0,
                '<item id="nav" href="nav.xhtml" '
                'media-type="application/xhtml+xml" properties="nav"/>'
            )
            book.writestr("EPUB/package.opf", (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
                'unique-identifier="book-id" xml:lang="zh-CN">'
                '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
                f'<dc:identifier id="book-id">{escape(task["start_url"])}</dc:identifier>'
                f'<dc:title>{escape(book_name)}</dc:title>'
                '<dc:language>zh-CN</dc:language></metadata>'
                '<manifest>' + "".join(manifest) + '</manifest>'
                '<spine>' + "".join(spine) + '</spine></package>'
            ), compress_type=ZIP_DEFLATED)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target
