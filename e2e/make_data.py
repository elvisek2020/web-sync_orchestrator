"""Testovací data pro E2E: NAS1 (lokálně) a NAS2 (přes SSH kontejner).

Soubory jsou řídké (sparse) — velikosti v GB nezaberou místo na disku.
Spuštění:  python3 e2e/make_data.py   (smaže a znovu vytvoří e2e/data/)
"""
from __future__ import annotations

import shutil
import unicodedata
from pathlib import Path

BASE = Path(__file__).resolve().parent / "data"
GB = 1000**2  # v E2E stačí MB — rsync by jinak zapsal gigabajty nul


def sparse(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        if size:
            f.seek(size - 1)
            f.write(b"\0")


def main() -> None:
    if BASE.exists():
        shutil.rmtree(BASE)
    nas1 = BASE / "nas1"
    nas2 = BASE / "nas2"
    (BASE / "app").mkdir(parents=True)
    (BASE / "disk").mkdir(parents=True)

    # --- Filmy: 3 chybí, 1 konflikt, zbytek shodný, smetí NASu ---
    films = {
        "Movie-Scifi/Vanilla Sky (2001)/Vanilla Sky (2001).mkv": 4 * GB,
        "Movie-Akcni/Chatrč (2017)/Chatrč (2017).mkv": 3 * GB,
        "Movie-Akcni/Kill Switch (2008)/Kill Switch (2008).mkv": 2 * GB,
        "Movie-Drama/Pelíšky (1999)/Pelíšky (1999).mkv": 5 * GB,
        "Movie-Drama/Kolja (1996)/Kolja (1996).mkv": 4 * GB,
        "Movie-Drama/Kolja (1996)/Kolja (1996).srt": 80_000,
    }
    for rel, size in films.items():
        sparse(nas1 / "NAS-FILMY" / rel, size)
    sparse(nas1 / "NAS-FILMY/Movie-Drama/@eaDir/thumb.jpg", 1000)
    sparse(nas1 / "NAS-FILMY/.DS_Store", 100)
    sparse(nas2 / "Filmy/Movie-Drama/Pelíšky (1999)/Pelíšky (1999).mkv", 5 * GB - 7)   # konflikt
    sparse(nas2 / "Filmy/Movie-Drama/Kolja (1996)/Kolja (1996).mkv", 4 * GB)
    sparse(nas2 / "Filmy/Movie-Drama/Kolja (1996)/Kolja (1996).srt", 80_000)
    sparse(nas2 / "Filmy/.@__thumb/x.jpg", 100)

    # --- Seriály: přejmenované řady (Season 3 → Season 03), NFD názvy, přebývající ---
    for season in (1, 2, 3):
        for ep in range(1, 7):
            sparse(nas1 / f"NAS-SERIALY/Přátelé (1994)/Season {season:02d}/S{season:02d}E{ep:02d}.mkv", 1 * GB + ep)
            sparse(nas2 / f"Serialy/Přátelé (1994)/Season {season}/S{season:02d}E{ep:02d}.mkv", 1 * GB + ep)
    nfd = unicodedata.normalize("NFD", "Četnické humoresky (2001)/Season 01/Díl 1.avi")
    sparse(nas1 / "NAS-SERIALY" / "Četnické humoresky (2001)/Season 01/Díl 1.avi", 700_000_000)
    sparse(nas2 / "Serialy" / nfd, 700_000_000)  # stejné, jen NFD na NAS2
    sparse(nas1 / "NAS-SERIALY/Nový seriál (2025)/S01E01.mkv", 2 * GB)
    sparse(nas1 / 'NAS-SERIALY/Divné názvy/Otázka?.mkv', 1000)  # exFAT to nezvládne → problém

    # --- Pohádky: prázdný cíl (první synchronizace) ---
    for i in range(1, 4):
        sparse(nas1 / f"NAS-POHADKY/Krtek/Krtek {i}.avi", 300_000_000)
    (nas2 / "Pohadky").mkdir(parents=True, exist_ok=True)

    print(f"Hotovo: {BASE}")


if __name__ == "__main__":
    main()
