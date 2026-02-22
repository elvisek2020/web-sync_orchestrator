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
    - Root appears deeper in path: "share/Filmy/Movie/file.mkv" with root "Filmy" -> "Movie/file.mkv"
    - Multi-component root: "share/Filmy/Movie/file.mkv" with root "share/Filmy" -> "Movie/file.mkv"
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

    # Case 1: path starts with root/ (exact prefix match on path boundary)
    if path_clean.startswith(root_clean + "/"):
        result = path_clean[len(root_clean) + 1:]
    elif path_clean == root_clean:
        return ""

    # Case 2: root appears as a path segment deeper in the path
    # e.g. path="share/Filmy/Movie/file.mkv", root="Filmy" → "Movie/file.mkv"
    if result is None:
        needle = "/" + root_clean + "/"
        idx = path_clean.find(needle)
        if idx >= 0:
            result = path_clean[idx + len(needle):]
        else:
            # Check if path ends with /root (no trailing content)
            needle_end = "/" + root_clean
            if path_clean.endswith(needle_end):
                return ""

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
