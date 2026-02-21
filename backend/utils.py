"""
Shared utility functions for path normalization and file operations.
"""
import logging
import unicodedata

logger = logging.getLogger(__name__)

IGNORED_PATH_SEGMENTS = (".streams",)


def normalize_path(path: str, root: str) -> str:
    """Remove the root directory prefix from a path and return the Unicode-NFC-normalized relative path.
    
    Handles various cases:
    - Path starts with root folder: "NAS-FILMY/Movie/file.mkv" -> "Movie/file.mkv"
    - Path is already normalized: "Movie/file.mkv" -> "Movie/file.mkv"
    - Root is not in path: returns path as-is (stripped of leading slashes)
    
    All returned paths are normalized to Unicode NFC form to avoid mismatches
    between filesystems that use NFD (e.g. macOS HFS+) vs NFC (e.g. Linux ext4, SMB).
    """
    if not path:
        return path or ""

    if not root:
        return unicodedata.normalize("NFC", path.strip("/"))

    root_clean = unicodedata.normalize("NFC", root.strip("/"))
    path_clean = unicodedata.normalize("NFC", path.strip("/"))

    if not root_clean:
        return unicodedata.normalize("NFC", path_clean)

    result = None

    if path_clean.startswith(root_clean + "/"):
        result = path_clean[len(root_clean) + 1:]
    elif path_clean == root_clean:
        return ""
    elif path_clean.startswith(root_clean):
        rest = path_clean[len(root_clean):]
        if rest.startswith("/"):
            result = rest.lstrip("/")
    
    if result is None:
        parts = path_clean.split("/")
        if parts and parts[0] == root_clean:
            result = "/".join(parts[1:]) if len(parts) > 1 else ""
    
    if result is None:
        result = path_clean

    return unicodedata.normalize("NFC", result)


def is_ignored_path(path: str) -> bool:
    """Check if a path should be ignored (e.g. macOS/NTFS metadata streams)."""
    for segment in IGNORED_PATH_SEGMENTS:
        if segment in path.split("/"):
            return True
    if ":$DATA" in path:
        return True
    return False


def normalize_root_rel_path(root_rel_path: str) -> str:
    """Normalize root_rel_path to a consistent format (no leading/trailing slashes).
    
    Both local and SSH adapters should produce the same format.
    """
    if not root_rel_path or root_rel_path == "/":
        return ""
    return root_rel_path.strip("/")
