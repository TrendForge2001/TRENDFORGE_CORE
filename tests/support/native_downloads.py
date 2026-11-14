"""Inspect native download anchors rendered by Streamlit AppTest."""

import base64
from html.parser import HTMLParser


class DownloadParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.downloads = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "a" and values.get("data-tf-download") == "true":
            self.current = {**values, "label": ""}

    def handle_data(self, value):
        if self.current is not None:
            self.current["label"] += value

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            self.downloads.append(self.current)
            self.current = None


def downloads(app):
    parser = DownloadParser()
    for item in app.markdown:
        parser.feed(item.value)
    return parser.downloads


def content(download):
    return base64.b64decode(download["href"].split(",", 1)[1], validate=True)
