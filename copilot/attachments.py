"""Uploaded invoices for the chat: stored as files under a random id, read back only by that id.

The bytes are not parsed here: the rule engine parses them safely when the graph validates, and a file that is not
a readable invoice becomes finding XML-00 (which the assistant can explain).
"""
import re
import uuid

from copilot import config

ATTACHMENT_ID = re.compile(r"^[0-9a-f]{32}$")


class AttachmentError(ValueError):
    pass


def save(data: bytes) -> str:
    if not data:
        raise AttachmentError("The file is empty.")
    if len(data) > config.MAX_UPLOAD_KB * 1024:
        raise AttachmentError(f"The invoice is larger than {config.MAX_UPLOAD_KB} KB.")
    config.ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
    attachment_id = uuid.uuid4().hex
    (config.ATTACHMENTS_DIR / f"{attachment_id}.xml").write_bytes(data)
    return attachment_id


def load(attachment_id: str) -> bytes | None:
    """The stored bytes, or None for an unknown id (only ids of the expected shape reach the file system)."""
    if not ATTACHMENT_ID.match(attachment_id or ""):
        return None
    path = config.ATTACHMENTS_DIR / f"{attachment_id}.xml"
    return path.read_bytes() if path.is_file() else None
