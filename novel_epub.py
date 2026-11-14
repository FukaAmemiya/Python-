"""Generate a minimal standards-compliant EPUB 3 archive without extra dependencies."""

from html import escape
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile


def _xml_escape(value):
    """清除不允许出现在 XML 1.0 中的字符，避免整本 EPUB 无法打开。"""
    valid = (
        char for char in value
        if (ord(char) in (9, 10, 13)
            or 0x20 <= ord(char) <= 0xD7FF
            or 0xE000 <= ord(char) <= 0xFFFD
            or 0x10000 <= ord(char) <= 0x10FFFF)
    )
    return escape("".join(valid))


def export_epub(store, target):
    """Atomically export committed chapters to EPUB; keep the SQLite source intact."""
    import os
    import tempfile

    task = store.task()
    book_name = task["book_name"]
    if not store.count():
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
            book.writestr("EPUB/style.css", (
                "body{font-family:serif;line-height:1.8;margin:1em;} "
                "h1{font-size:1.35em;line-height:1.5;margin:1em 0;} "
                "p{text-indent:2em;margin:.5em 0;}"
            ), compress_type=ZIP_DEFLATED)
            for index, chapter in enumerate(store.iter_chapters(), 1):
                filename = f"chapter-{index:05d}.xhtml"
                title = _xml_escape(chapter["title"])
                paragraphs = "".join(
                    f"<p>{_xml_escape(part).replace(chr(10), '<br/>')}</p>"
                    for part in chapter["content"].split("\n\n") if part.strip()
                )
                book.writestr("EPUB/" + filename, (
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN">'
                    f'<head><title>{title}</title>'
                    '<link rel="stylesheet" type="text/css" href="style.css"/>'
                    '</head><body><h1>' + title + '</h1>'
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
                '<item id="css" href="style.css" media-type="text/css"/>'
            )
            book.writestr("EPUB/package.opf", (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
                'unique-identifier="book-id" xml:lang="zh-CN">'
                '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
                f'<dc:identifier id="book-id">{_xml_escape(task["start_url"])}</dc:identifier>'
                f'<dc:title>{_xml_escape(book_name)}</dc:title>'
                '<dc:language>zh-CN</dc:language></metadata>'
                '<manifest>' + "".join(manifest) + '</manifest>'
                '<spine>' + "".join(spine) + '</spine></package>'
            ), compress_type=ZIP_DEFLATED)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target
