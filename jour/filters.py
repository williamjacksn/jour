import lxml.html
import markdown
import markupsafe


def add_css_class_to_tag(html: str, tag: str, css_class: str) -> markupsafe.Markup:
    doc = lxml.html.fragment_fromstring(html, create_parent='div')
    for el in doc.xpath(f'//{tag}'):
        tag.classes.add(css_class)
    result = lxml.html.tostring(doc, encoding='unicode')
    return markupsafe.Markup(result)


def md(t: str) -> markupsafe.Markup:
    """Take markdown-formatted text as input and render into HTML."""
    _md = markdown.Markdown()
    return markupsafe.Markup(_md.convert(t))
