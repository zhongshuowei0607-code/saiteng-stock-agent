from html import escape
from html.parser import HTMLParser


class SafeHTML(HTMLParser):
    """独立 HTML 日报仅保留排版标签，不接受外部文本生成的活动内容。"""

    allowed = {
        "h1",
        "h2",
        "h3",
        "h4",
        "p",
        "pre",
        "code",
        "ul",
        "ol",
        "li",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "strong",
        "em",
        "blockquote",
        "br",
        "hr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.allowed:
            self.parts.append("<" + tag + ">")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.allowed:
            self.parts.append("</" + tag + ">")

    def handle_data(self, data: str) -> None:
        self.parts.append(escape(data))


def sanitize(body: str) -> str:
    parser = SafeHTML()
    parser.feed(body)
    parser.close()
    return "".join(parser.parts)
