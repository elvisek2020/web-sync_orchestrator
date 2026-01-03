"""
Globální konfigurace aplikace
"""
# Výchozí výjimky - soubory, které se nebudou kopírovat
DEFAULT_EXCLUDE_PATTERNS = [
    ".DS_Store",  # macOS
    "._*",  # macOS resource forks
    ".AppleDouble",  # macOS
    "Thumbs.db",  # Windows
    "desktop.ini",  # Windows
    ".Trash*",  # Linux trash
    "*.tmp",  # Dočasné soubory
    "*.swp",  # Vim swap files
    "*.bak",  # Backup files
    ".git",  # Git repository
    ".svn",  # SVN repository
    ".hg",  # Mercurial repository
    "@eaDir",  # Synology Extended Attributes directory
    "*@SynoEAStream",  # Synology Extended Attributes stream files
    "*@SynoResource",  # Synology resource files
    "*@SynoStream",  # Synology stream files
]

def match_exclude_pattern(path: str, patterns: list) -> bool:
    """
    Zkontroluje, zda cesta odpovídá některému z exclude patternů.
    Podporuje glob patterns:
    - ".DS_Store" - přesná shoda názvu souboru
    - "*.tmp" - soubory s příponou .tmp
    - ".DS_Store" - soubory s názvem .DS_Store kdekoli v cestě
    - "folder/.DS_Store" - přesná cesta
    """
    import fnmatch
    import os
    
    # Normalizace cesty
    path_normalized = path.replace("\\", "/")
    filename = os.path.basename(path_normalized)
    
    for pattern in patterns:
        if not pattern:
            continue
        
        # Přesná shoda názvu souboru
        if filename == pattern:
            return True
        
        # Glob pattern pro název souboru
        if fnmatch.fnmatch(filename, pattern):
            return True
        
        # Glob pattern pro celou cestu
        if fnmatch.fnmatch(path_normalized, pattern):
            return True
        
        # Pattern může být relativní cesta
        if pattern in path_normalized:
            return True
    
    return False

