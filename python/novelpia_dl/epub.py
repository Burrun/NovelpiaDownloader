"""EPUB 2 writer (same layout as the C# version: OEBPS/Text, Styles, Images)."""

import datetime
import html
import zipfile

CONTAINER = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles>
<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
</rootfiles>
</container>
"""

SGC_TOC_CSS = """div.sgc-toc-title {
font-size: 1em;
font-weight: bold;
margin-bottom: 1em;
text-align: left;
text-indent: 0;
margin-top: 1.0em;
}

div.sgc-toc-level-1 {
margin-left: 0em;
text-indent: 0;
margin-top: 0.2em;
line-height: 1.6em;
}

div.sgc-toc-level-2 {
margin-left: 0;
}

div.sgc-toc-level-3 {
margin-left: 0;
}

div.sgc-toc-level-4 {
margin-left: 0;
}

div.sgc-toc-level-5 {
margin-left: 0;
}

div.sgc-toc-level-6 {
margin-left: 0;
}
"""

BASE_CSS = """.border01 {

border: 2px solid black;
padding: 0;
margin: 1.0em 0;
line-height: 1.6em;
font-size: 1.0em;
font-style: normal;
font-weight: normal;
text-align: left;
}


/* 바디 기본 설정 */
/* 나눔고딕체 설정 필요 (임베딩 불가)*/

body{
margin:0;
padding:0;
font-family: 'KoPub바탕체 Light', 'KoPub돋움체 Light';
}

/*폰트 고딕*/

.dotum{font-family:'KoPub돋움체 Light';}


/* 목차 설정까지 한큐 */

h1{
display: block;
font-size: 1em;
font-style: normal;
font-weight: bold;
line-height: 1.6em;
margin-bottom: 0;
margin-left: 0;
margin-right: 0;
margin-top: 1.6em;
text-align: left;
text-indent: 0;
padding-left: 0;
padding-right: 0;
padding-top: 0;
}

/* 커버 */

div{
font-style: normal;
font-weight: normal;
}


/* 본문 */

p{
font-size: 1.0em;
font-style: normal;
font-weight: normal;
line-height: 1.6em;
margin-bottom: 0;
margin-left: 0;
margin-right: 0;
margin-top: 0.2em;
text-align: left;
text-indent: 0;
padding-left: 0;
padding-right: 0;
}

/*크게, 작게*/

.t09{
font-size: 1em;
font-style: normal;
font-weight: normal;
line-height: 1.6em;
margin-bottom: 0em;
margin-left: 0;
margin-right: 0;
margin-top: 0.2em;
text-indent: 0em;
padding-left: 0;
padding-right: 0;
}

.t12{
font-family: inherit;
font-size: 1em;
font-style: normal;
font-weight: bold;
line-height: 1.6em;
margin-bottom: 0em;
margin-left: 0;
margin-right: 0;
margin-top: 0.2em;
text-align: left;
text-indent: 0;
padding-left: 0;
padding-right: 0;
}

/*중간, 오른쪽, 볼드, 이탤릭, 들여쓰기*/

.ridicenter{
display: block;
text-align: left;
}
.c{
text-align:left;
}

.r{
text-align: left;
}

.b{
font-weight: bold;
}

.i{
font-style: italic;
}

.ridibox {
padding: 0.5em 0;
}

/*흐리게*/

.flashback {
color: #868a8e !important;
}

.blur{
color: #8F908A;
}

/*커버, 이미지*/

.cover {
text-align: center;
width: 100%;
margin-top: 0;
margin-right: 0;
}

.img{
width:100%;
text-align:center;
margin-top: 0;
margin-right: 0;
}


/* * * * */

.devide{
color:#33394c;
display:block;
font-size:1.0em;
font-style:normal;
font-weight:normal;
line-height:1.5em;
margin-bottom:1.5em;
margin-left:0;
margin-right:0;
margin-top:1.5em;
padding-left:0;
padding-right:0;
padding-top:0;
text-align:left;
text-indent:0;
}

/*루비문자*/
rt {
font-size: 1em;
font-style: normal;
font-weight: normal;
}


/*양 옆 들여쓰기*/

.pad07 {
padding:0;
}
/*이미지에 패딩 주고 싶을 때*/

div#wrap{margin:0;}
div#wrap2{ margin: 0; text-align: center; }

/*각주처리*/


.footnote p
{
text-indent:0;
font-size:1em;
line-height:1.6em;
}

span.br {
color:gray;
font-size: 1em;
}

/*글상자*/

.ridiborder {
padding: 0.5em 0;
border-radius: 0.5em;
border: 0.1em solid #868a8e;
}




.ridipost {
padding: 0.5em 0;
background-color: #FFFF00;
border-radius: 0.5em;
}
"""

OLD_BODY = "body{\nmargin:0;\npadding:0;\nfont-family: 'KoPub바탕체 Light', 'KoPub돋움체 Light';\n}\n"

COVER_XHTML = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN"
"http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">

<html xmlns="http://www.w3.org/1999/xhtml" xmlns:xml="http://www.w3.org/XML/1998/namespace" xml:lang="ko">
<head>
<title></title>
<style type="text/css">
html, body { margin:0; padding:0; }
</style>

<link href="../Styles/sgc-toc.css" type="text/css" rel="stylesheet"/>
<link href="../Styles/Stylesheet.css" type="text/css" rel="stylesheet"/>
</head>

<body>
<div class="cover"><img alt="cover" src="../Images/cover.{ext}" width="100%"/></div>
</body>
</html>
"""

TOC_HEAD = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN"
"http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
<head>
<meta name="dtb:depth" content="0" />
<meta name="dtb:totalPageCount" content="0" />
<meta name="dtb:maxPageNumber" content="0" />
</head>
<docTitle>
"""

OPF_HEAD = """<?xml version="1.0" encoding="utf-8"?>
<package version="2.0" unique-identifier="BookId" xmlns="http://www.idpf.org/2007/opf">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
"""

MANIFEST_HEAD = """<meta content="1.9.10" name="Sigil version"/>
</metadata>
<manifest>
<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
<item id="sgc-toc.css" href="Styles/sgc-toc.css" media-type="text/css"/>
<item id="Stylesheet.css" href="Styles/Stylesheet.css" media-type="text/css"/>
"""


def stylesheet(vertical, gothic):
    body = ["body{", "margin:0;", "padding:0;"]
    if vertical:
        body.append('font-family: "@Malgun Gothic","Malgun Gothic","Dotum","Gulim",sans-serif;' if gothic
                    else 'font-family: "@Batang","Batang","Gungsuh",serif;')
        body += ["line-height: 1.8em;", "writing-mode: vertical-rl;", "text-orientation: mixed;",
                 "-epub-writing-mode: vertical-rl;"]
    else:
        body.append('font-family: "Malgun Gothic","Dotum","Gulim",sans-serif;' if gothic
                    else 'font-family: "Batang","Gungsuh","KoPub바탕체 Light","KoPub돋움체 Light",serif;')
        body.append("line-height: 1.6em;")
    body.append("}")
    return (BASE_CSS.replace(OLD_BODY, "\n".join(body) + "\n")
            + "\nbody, body * { text-align: left !important; text-indent: 0 !important; "
              "margin-left: 0 !important; margin-right: 0 !important; padding-left: 0 !important; "
              "padding-right: 0 !important; }\n"
            + ".cover, .img, div#wrap2 { text-align: center !important; }\n")


IMAGE_TYPES = [
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
    (b"\xff\xd8\xff", "jpg", "image/jpeg"),
    (b"GIF87a", "gif", "image/gif"),
    (b"GIF89a", "gif", "image/gif"),
    (b"BM", "bmp", "image/bmp"),
]


def image_type(data):
    """-> (ext, mime) sniffed from magic bytes; JPEG if unknown."""
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    for magic, ext, mime in IMAGE_TYPES:
        if data.startswith(magic):
            return ext, mime
    return "jpg", "image/jpeg"


def write_epub(path, *, novel_no, title, author, chapters, images, cover, compress, vertical, gothic):
    """chapters: [(title, file_stem, xhtml)]; images: [(name, bytes)] e.g. ("3.png", b"..");
    cover: bytes or None."""
    esc = html.escape
    method = zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED

    ncx = [TOC_HEAD, f"<text>{esc(title)}</text>\n</docTitle>\n<navMap>\n"]
    for i, (name, stem, _) in enumerate(chapters, 1):
        ncx.append(f'<navPoint id="navPoint-{i}" playOrder="{i}">\n'
                   f"<navLabel>\n<text>{esc(name)}</text>\n</navLabel>\n"
                   f'<content src="Text/chapter{stem}.html" />\n</navPoint>\n')
    ncx.append("</navMap>\n</ncx>\n")

    cover_ext, cover_mime = image_type(cover) if cover else ("jpg", "image/jpeg")
    opf = [OPF_HEAD,
           f'<dc:identifier id="BookId" opf:scheme="NovelpiaNovelNo">{novel_no}</dc:identifier>\n',
           f"<dc:title>{esc(title)}</dc:title>\n",
           "<dc:language>ko</dc:language>\n"]
    if author:
        opf.append(f'<dc:creator opf:role="aut">{esc(author)}</dc:creator>\n')
    opf.append(f"<dc:date>{datetime.datetime.now(datetime.timezone.utc):%Y-%m-%d}</dc:date>\n")
    if cover:
        opf.append('<meta name="cover" content="cover-img"/>\n')
    opf.append(MANIFEST_HEAD)
    if cover:
        opf.append('<item id="cover.html" href="Text/cover.html" media-type="application/xhtml+xml"/>\n')
        opf.append(f'<item id="cover-img" href="Images/cover.{cover_ext}" media-type="{cover_mime}"/>\n')
    for _, stem, _ in chapters:
        opf.append(f'<item id="chapter{stem}.html" href="Text/chapter{stem}.html" '
                   'media-type="application/xhtml+xml"/>\n')
    for name, data in images:
        opf.append(f'<item id="img{name.split(".")[0]}" href="Images/{name}" '
                   f'media-type="{image_type(data)[1]}"/>\n')
    opf.append('</manifest>\n<spine toc="ncx">\n')
    if cover:
        opf.append('<itemref idref="cover.html"/>\n')
    for _, stem, _ in chapters:
        opf.append(f'<itemref idref="chapter{stem}.html"/>\n')
    opf.append("</spine>\n")
    if cover:
        opf.append('<guide>\n<reference type="cover" title="Cover" href="Text/cover.html"/>\n</guide>\n')
    opf.append("</package>\n")

    with zipfile.ZipFile(path, "w") as z:
        # EPUB OCF: "mimetype" first and uncompressed.
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        put = lambda name, data: z.writestr(name, data, compress_type=method)
        put("META-INF/container.xml", CONTAINER)
        put("OEBPS/Styles/sgc-toc.css", SGC_TOC_CSS)
        put("OEBPS/Styles/Stylesheet.css", stylesheet(vertical, gothic))
        if cover:
            put("OEBPS/Text/cover.html", COVER_XHTML.replace("{ext}", cover_ext))
            put(f"OEBPS/Images/cover.{cover_ext}", cover)
        for name, data in images:
            put(f"OEBPS/Images/{name}", data)
        for _, stem, xhtml in chapters:
            put(f"OEBPS/Text/chapter{stem}.html", xhtml)
        put("OEBPS/toc.ncx", "".join(ncx))
        put("OEBPS/content.opf", "".join(opf))
