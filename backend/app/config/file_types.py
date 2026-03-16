"""
Centralized file type configuration for LlamaParse support.
All supported formats organized by category based on:
https://developers.llamaindex.ai/python/cloud/llamaparse/features/supported_document_types/
"""
from enum import Enum
from typing import Dict, Set


class FileCategory(str, Enum):
    """File categories supported by LlamaParse."""
    DOCUMENT = "document"
    PRESENTATION = "presentation"
    SPREADSHEET = "spreadsheet"
    IMAGE = "image"
    WEB = "web"
    TEXT = "text"


# LlamaParse supported extensions by category
DOCUMENT_EXTENSIONS = {
    "pdf", "doc", "docx", "docm", "dot", "dotm", "rtf", "pages", "epub",
    "602", "abw", "cwk", "hwp", "lwp", "mw", "mcw", "pbd", "wpd", "wps",
    "sda", "sdw", "sgl", "stw", "sxw", "sxg", "uof", "uot", "vor", "zabw",
}

PRESENTATION_EXTENSIONS = {
    "ppt", "pptx", "pptm", "pot", "potm", "potx", "key",
    "sdd", "sdp", "sti", "sxi",
}

SPREADSHEET_EXTENSIONS = {
    "xlsx", "xls", "xlsm", "xlsb", "xlw", "csv", "numbers", "ods", "fods",
    "dif", "sylk", "slk", "prn", "et", "uos1", "uos2", "dbf",
    "wk1", "wk2", "wk3", "wk4", "wks", "123", "wq1", "wq2",
    "wb1", "wb2", "wb3", "qpw", "xlr", "eth", "tsv",
}

IMAGE_EXTENSIONS = {
    "jpg", "jpeg", "png",
}

WEB_EXTENSIONS = {
    "html", "htm", "web", "xml",
}

TEXT_EXTENSIONS = {
    "txt", "cgm",
}

# Combine all extensions
ALL_EXTENSIONS = (
    DOCUMENT_EXTENSIONS
    | PRESENTATION_EXTENSIONS
    | SPREADSHEET_EXTENSIONS
    | IMAGE_EXTENSIONS
    | WEB_EXTENSIONS
    | TEXT_EXTENSIONS
)

# Map extensions to MIME types (most common ones)
EXTENSION_TO_MIME: Dict[str, str] = {
    # Documents
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "docm": "application/vnd.ms-word.document.macroEnabled.12",
    "dot": "application/msword",
    "dotm": "application/vnd.ms-word.template.macroEnabled.12",
    "rtf": "application/rtf",
    "epub": "application/epub+zip",
    "pages": "application/vnd.apple.pages",
    # Presentations
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "pptm": "application/vnd.ms-powerpoint.presentation.macroEnabled.12",
    "pot": "application/vnd.ms-powerpoint",
    "potm": "application/vnd.ms-powerpoint.template.macroEnabled.12",
    "potx": "application/vnd.openxmlformats-officedocument.presentationml.template",
    "key": "application/vnd.apple.keynote",
    # Spreadsheets
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls": "application/vnd.ms-excel",
    "xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    "xlsb": "application/vnd.ms-excel.sheet.binary.macroEnabled.12",
    "csv": "text/csv",
    "numbers": "application/vnd.apple.numbers",
    "ods": "application/vnd.oasis.opendocument.spreadsheet",
    "tsv": "text/tab-separated-values",
    # Images
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    # Web
    "html": "text/html",
    "htm": "text/html",
    "xml": "application/xml",
    # Text
    "txt": "text/plain",
}

# Reverse mapping (MIME to primary extension)
MIME_TO_EXTENSION: Dict[str, str] = {}
for ext, mime in EXTENSION_TO_MIME.items():
    if mime not in MIME_TO_EXTENSION:
        MIME_TO_EXTENSION[mime] = ext


def get_category_for_extension(extension: str) -> FileCategory | None:
    """Get the file category for a given extension."""
    ext = extension.lower().lstrip(".")
    if ext in DOCUMENT_EXTENSIONS:
        return FileCategory.DOCUMENT
    elif ext in PRESENTATION_EXTENSIONS:
        return FileCategory.PRESENTATION
    elif ext in SPREADSHEET_EXTENSIONS:
        return FileCategory.SPREADSHEET
    elif ext in IMAGE_EXTENSIONS:
        return FileCategory.IMAGE
    elif ext in WEB_EXTENSIONS:
        return FileCategory.WEB
    elif ext in TEXT_EXTENSIONS:
        return FileCategory.TEXT
    return None


def get_allowed_file_types_list() -> list[str]:
    """Get sorted list of all allowed file extensions."""
    return sorted(list(ALL_EXTENSIONS))


def get_mime_type(extension: str) -> str:
    """Get MIME type for extension, fallback to octet-stream."""
    ext = extension.lower().lstrip(".")
    return EXTENSION_TO_MIME.get(ext, "application/octet-stream")
