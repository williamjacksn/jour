import markdown
import markupsafe


def md(t: str) -> markupsafe.Markup:
    """Take markdown-formatted text as input and render into HTML."""
    _md = markdown.Markdown()
    return markupsafe.Markup(_md.convert(t))
