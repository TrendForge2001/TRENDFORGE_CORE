"""Native file links for authenticated pages, without a lazy JS download widget."""

import base64
import mimetypes
from html import escape

import streamlit as st

MIMES = frozenset(
    {
        "text/csv",
        "text/plain",
        "application/json",
        "application/zip",
        "application/octet-stream",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
)


def download_html(label, data, file_name, mime=None, *, primary=False):
    name = str(file_name).replace("\\", "/").rsplit("/", 1)[-1]
    if not name or name in {".", ".."} or any(ord(char) < 32 for char in name):
        raise ValueError("Invalid download filename")
    content_type = mime or mimetypes.guess_type(name)[0] or "application/octet-stream"
    if content_type not in MIMES:
        raise ValueError("Unsupported download content type")
    if hasattr(data, "getvalue"):
        data = data.getvalue()
    if isinstance(data, str):
        data = data.encode("utf-8")
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("Download data must be text or bytes")
    encoded = base64.b64encode(data).decode("ascii")
    background = "#254d75" if primary else "#15273d"
    return (
        f'<a data-tf-download="true" download="{escape(name, quote=True)}" '
        f'href="data:{content_type};base64,{encoded}" '
        'style="display:flex;align-items:center;justify-content:center;'
        "min-height:44px;padding:8px 12px;border:1px solid #7794b3;"
        f"border-radius:8px;background:{background};color:#f1f5fc;"
        "text-decoration:none;font-weight:600;box-sizing:border-box;"
        f'width:100%;white-space:normal">{escape(str(label))}</a>'
    )


def download_link(
    label,
    data,
    file_name,
    mime=None,
    *,
    key=None,
    width=None,
    type="secondary",
    container=None,
    **_kwargs,
):
    # The bytes are already authorized by the page's access gate and backend
    # request. No API key, server credential or public report endpoint is added.
    target = st if container is None else container
    target.markdown(
        download_html(label, data, file_name, mime, primary=type == "primary"),
        unsafe_allow_html=True,
    )
