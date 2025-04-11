import lxml.html
import markdown
import markupsafe


def md(t: str) -> markupsafe.Markup:
    """Take markdown-formatted text as input and render into HTML."""
    _md = markdown.Markdown()
    doc = lxml.html.fragment_fromstring(_md.convert(t), create_parent="div")
    for el in doc.xpath(f"//blockquote"):
        el.classes.update(("border-3", "border-start", "ps-2"))
    result = lxml.html.tostring(doc, encoding="unicode")
    return markupsafe.Markup(result)
