"""Vygenerovaný bash skript — syntaxe a skutečný běh obou režimů (vyžaduje bash a rsync 3.x)."""
from __future__ import annotations

import os
import shutil
import subprocess
import unicodedata
from pathlib import Path

import pytest

from app.core.keys import FileRec
from app.core.plan import CONFLICT, EXTRA, MISSING, Comparison, Item, PairPlan
from app.core.script import generate_script

pytestmark = pytest.mark.skipif(
    shutil.which("rsync") is None or shutil.which("bash") is None, reason="chybí rsync nebo bash"
)

# Názvy, které by rozbily skript se seznamem v uvozovkách (stará verze).
EVIL = [
    "mezera v názvu.mkv",
    "dolar $HOME $(touch PWNED).mkv",
    "backtick `touch PWNED`.mkv",
    'uvozovka " uvnitř.mkv',
    "apostrof ' uvnitř.mkv",
    "hvězdička * a ? otazník.mkv",
    "-zacina-pomlckou.mkv",
    "novy\nradek.mkv",
    "Seriály/Řada 01/Díl 1 – Začátek.mkv",
    unicodedata.normalize("NFD", "NFD/Pohádka é.mkv"),
    "__SYNC_LIST__",
]


def _rec(rel: str, size: int) -> FileRec:
    return FileRec(rel.encode("utf-8"), unicodedata.normalize("NFC", rel), size, 0.0)


def _write(root: Path, rel: str, content: bytes) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)


def _plan(copy: list[str], delete: list[str] = (), conflicts: list[tuple[str, str]] = (), same: list[str] = ()) -> PairPlan:
    items = [Item(_rec(p, 0).key, MISSING, _rec(p, len(p.encode())), None) for p in copy]
    items += [Item(_rec(s, 0).key, CONFLICT, _rec(s, len(s.encode())), _rec(t, 1)) for s, t in conflicts]
    cmp = Comparison(same_sample=[(s.encode(), s.encode()) for s in same])
    plan = PairPlan(1, cmp, on_disk=True, include_conflicts=True, include_extra=True)
    plan.transfer = plan.selected = items
    plan.deletions = [Item(p, EXTRA, None, _rec(p, 1)) for p in delete]
    return plan


def _script(tmp_path: Path, plan: PairPlan, slug="test") -> Path:
    path = tmp_path / f"sync_{slug}.sh"
    path.write_text(generate_script(pair_name="Test „pár“\n$(x)", slug=slug, plan=plan,
                                    source_desc="NAS1:src", target_desc="NAS2:/dst"), encoding="utf-8")
    return path


def _run(script: Path, *args: str, cwd: Path) -> subprocess.CompletedProcess:
    # errors="replace": openrsync na macOS vypisuje v průběhu názvy s diakritikou rozbitě (\#231)
    return subprocess.run(["bash", str(script), *args], cwd=cwd, capture_output=True, text=True, errors="replace",
                          stdin=subprocess.DEVNULL, timeout=60, start_new_session=True)


@pytest.fixture()
def dirs(tmp_path):
    d = {name: tmp_path / name for name in ("nas1", "disk", "nas2", "work")}
    for p in d.values():
        p.mkdir()
    return d


def test_syntax(tmp_path):
    script = _script(tmp_path, _plan(EVIL, delete=["x"]))
    subprocess.run(["bash", "-n", str(script)], check=True)


def test_evil_names_roundtrip(dirs, tmp_path):
    for rel in EVIL:
        _write(dirs["nas1"], rel, rel.encode())
    _write(dirs["nas2"], "stary/soubor navíc.mkv", b"old")
    _write(dirs["nas2"], "stary/jiny/hluboko.mkv", b"old")
    _write(dirs["nas2"], "zustava.mkv", b"keep")
    script = _script(tmp_path, _plan(EVIL, delete=["stary/soubor navíc.mkv", "stary/jiny/hluboko.mkv"]))

    r1 = _run(script, "to-disk", str(dirs["nas1"]), str(dirs["disk"]), "--yes", cwd=dirs["work"])
    assert r1.returncode == 0, r1.stdout + r1.stderr
    for rel in EVIL:
        assert (dirs["disk"] / "test" / rel).read_bytes() == rel.encode()
    assert (dirs["disk"] / "test/.sync-plan").exists()

    r2 = _run(script, "to-nas", str(dirs["disk"]), str(dirs["nas2"]), "--yes", cwd=dirs["work"])
    assert r2.returncode == 0, r2.stdout + r2.stderr
    for rel in EVIL:
        assert (dirs["nas2"] / rel).read_bytes() == rel.encode()
    assert not (dirs["nas2"] / "stary").exists()          # smazáno i s prázdnými složkami
    assert (dirs["nas2"] / "zustava.mkv").exists()
    assert not (dirs["nas2"] / ".sync-plan").exists()     # manifest se na NAS2 nekopíruje
    for d in dirs.values():                                # žádný název nic nespustil
        assert not (d / "PWNED").exists()


def test_without_tty_deletion_defaults_to_no(dirs, tmp_path):
    _write(dirs["nas1"], "a.mkv", b"a")
    _write(dirs["nas2"], "navic.mkv", b"x")
    script = _script(tmp_path, _plan(["a.mkv"], delete=["navic.mkv"]))
    assert _run(script, "to-disk", str(dirs["nas1"]), str(dirs["disk"]), cwd=dirs["work"]).returncode == 0
    r = _run(script, "to-nas", str(dirs["disk"]), str(dirs["nas2"]), cwd=dirs["work"])
    assert r.returncode == 0, r.stdout
    assert (dirs["nas2"] / "a.mkv").exists()
    assert (dirs["nas2"] / "navic.mkv").exists()           # bez potvrzení se nemaže
    assert "Mazání přeskočeno" in r.stdout


def test_dry_run_changes_nothing(dirs, tmp_path):
    _write(dirs["nas1"], "a.mkv", b"a")
    _write(dirs["disk"], "test/a.mkv", b"a")
    _write(dirs["disk"], "test/.sync-plan", b"PLAN=x\n")
    _write(dirs["nas2"], "navic.mkv", b"x")
    script = _script(tmp_path, _plan(["a.mkv"], delete=["navic.mkv"]))
    r = _run(script, "to-disk", str(dirs["nas1"]), str(dirs["disk"]), "--dry-run", "--yes", cwd=dirs["work"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert (dirs["disk"] / "test/.sync-plan").read_bytes() == b"PLAN=x\n"
    r = _run(script, "to-nas", str(dirs["disk"]), str(dirs["nas2"]), "--dry-run", "--yes", cwd=dirs["work"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (dirs["nas2"] / "a.mkv").exists()
    assert (dirs["nas2"] / "navic.mkv").exists()
    assert "smazal by se: navic.mkv" in r.stdout


def test_manifest_mismatch_aborts_without_confirmation(dirs, tmp_path):
    _write(dirs["nas1"], "a.mkv", b"a")
    script_a = _script(tmp_path, _plan(["a.mkv"]), slug="test")
    assert _run(script_a, "to-disk", str(dirs["nas1"]), str(dirs["disk"]), cwd=dirs["work"]).returncode == 0
    other = tmp_path / "other"
    other.mkdir()
    script_b = _script(other, _plan(["a.mkv", "b.mkv"]), slug="test")
    r = _run(script_b, "to-nas", str(dirs["disk"]), str(dirs["nas2"]), cwd=dirs["work"])
    assert r.returncode != 0
    assert "jiného plánu" in r.stdout
    assert not (dirs["nas2"] / "a.mkv").exists()


def test_wrong_target_folder_is_detected(dirs, tmp_path):
    _write(dirs["nas1"], "a.mkv", b"a")
    same = [f"shodny{i}.mkv" for i in range(5)]
    for rel in same:
        _write(dirs["nas1"], rel, b"s")
    script = _script(tmp_path, _plan(["a.mkv"], same=same))
    r = _run(script, "to-disk", str(dirs["nas1"]), str(dirs["disk"]), cwd=dirs["work"])
    assert r.returncode == 0 and "VAROVÁNÍ" not in r.stdout, r.stdout
    # NAS2 shodné soubory nemá → nejspíš zadaná špatná složka → bez potvrzení konec
    r = _run(script, "to-nas", str(dirs["disk"]), str(dirs["nas2"]), cwd=dirs["work"])
    assert r.returncode != 0 and "špatná složka" in r.stdout
    assert not (dirs["nas2"] / "a.mkv").exists()


def test_missing_source_files_are_reported(dirs, tmp_path):
    _write(dirs["nas1"], "a.mkv", b"a")
    script = _script(tmp_path, _plan(["a.mkv", "zmizel.mkv"]))
    r = _run(script, "to-disk", str(dirs["nas1"]), str(dirs["disk"]), "--yes", cwd=dirs["work"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Ve zdroji chybí 1" in r.stdout and "zmizel.mkv" in r.stdout
    assert (dirs["disk"] / "test/a.mkv").exists()


def test_conflict_with_different_target_spelling_is_replaced(dirs, tmp_path):
    nfc = "Pohádka.mkv"
    nfd = unicodedata.normalize("NFD", nfc)
    _write(dirs["nas1"], nfc, b"new content")
    _write(dirs["nas2"], nfd, b"old")
    script = _script(tmp_path, _plan([], conflicts=[(nfc, nfd)]))
    assert _run(script, "to-disk", str(dirs["nas1"]), str(dirs["disk"]), "--yes", cwd=dirs["work"]).returncode == 0
    r = _run(script, "to-nas", str(dirs["disk"]), str(dirs["nas2"]), "--yes", cwd=dirs["work"])
    assert r.returncode == 0, r.stdout + r.stderr
    names = os.listdir(dirs["nas2"])
    assert names == [nfc] and (dirs["nas2"] / nfc).read_bytes() == b"new content"


def test_usage_errors(dirs, tmp_path):
    script = _script(tmp_path, _plan(["a"]))
    assert _run(script, cwd=dirs["work"]).returncode == 2
    assert _run(script, "to-mars", "a", "b", cwd=dirs["work"]).returncode == 2
    r = _run(script, "to-disk", str(dirs["nas1"] / "neni"), str(dirs["disk"]), cwd=dirs["work"])
    assert r.returncode == 1 and "neexistuje" in r.stderr


def test_delete_finds_other_unicode_spelling(dirs, tmp_path):
    # plán má cestu složeně (NFC), na cíli je soubor zapsaný rozloženě (NFD) — typicky soubory z Macu
    nfc = "Pohádky/Krtek a paraplíčko.avi"
    _write(dirs["nas2"], unicodedata.normalize("NFD", nfc), b"x")
    _write(dirs["nas2"], "zustava.avi", b"k")
    script = _script(tmp_path, _plan([], delete=[nfc]))
    r = _run(script, "to-nas", str(dirs["disk"]), str(dirs["nas2"]), "--yes", cwd=dirs["work"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Smazáno na cíli:       1 (chyby: 0, nenalezeno: 0)" in r.stdout
    assert os.listdir(dirs["nas2"]) == ["zustava.avi"]       # prázdná složka Pohádky uklizena


def test_delete_reports_files_it_cannot_find(dirs, tmp_path):
    _write(dirs["nas2"], "a.avi", b"x")
    script = _script(tmp_path, _plan([], delete=["a.avi", "uz-neni.avi"]))
    r = _run(script, "to-nas", str(dirs["disk"]), str(dirs["nas2"]), "--yes", cwd=dirs["work"])
    assert r.returncode == 1                                   # plán neproběhl celý → nenulový kód
    assert "POZOR: 1 z 2 přebývajících souborů se na cíli nepodařilo najít" in r.stdout
    assert "uz-neni.avi" in r.stdout and "nenalezeno: 1" in r.stdout
    assert not (dirs["nas2"] / "a.avi").exists()


def test_delete_only_plan_does_not_need_the_disk(dirs, tmp_path):
    _write(dirs["nas2"], "navic.avi", b"x")
    script = _script(tmp_path, _plan([], delete=["navic.avi"]))
    missing_disk = str(tmp_path / "disk-neni-pripojeny")
    r = _run(script, "to-nas", missing_disk, str(dirs["nas2"]), "--dry-run", cwd=dirs["work"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "není potřeba — jen mazání" in r.stdout and "Smazalo by se na cíli: 1" in r.stdout
    r = _run(script, "to-nas", missing_disk, str(dirs["nas2"]), "--yes", cwd=dirs["work"])
    assert r.returncode == 0 and not (dirs["nas2"] / "navic.avi").exists()
    # kopírovací plán disk potřebuje dál
    script2 = _script(tmp_path / "work", _plan(["a.mkv"]))
    assert _run(script2, "to-nas", missing_disk, str(dirs["nas2"]), cwd=dirs["work"]).returncode == 1


def test_to_nas_accepts_the_pair_folder_directly(dirs, tmp_path):
    _write(dirs["nas1"], "a.mkv", b"a")
    script = _script(tmp_path, _plan(["a.mkv"]))
    assert _run(script, "to-disk", str(dirs["nas1"]), str(dirs["disk"]), cwd=dirs["work"]).returncode == 0
    r = _run(script, "to-nas", str(dirs["disk"] / "test"), str(dirs["nas2"]), cwd=dirs["work"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert (dirs["nas2"] / "a.mkv").read_bytes() == b"a"


def test_progress_resume_and_failed_file(dirs, tmp_path):
    names = [f"Seriál/Řada 1/díl {i}.mkv" for i in range(1, 5)]
    for rel in names:
        _write(dirs["nas1"], rel, rel.encode())
    script = _script(tmp_path, _plan(names))

    r = _run(script, "to-disk", str(dirs["nas1"]), str(dirs["disk"]), "--yes", cwd=dirs["work"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[1/4 · 0,0 % · 0 B z " in r.stdout and "] Seriál/Řada 1/" in r.stdout   # celkový průběh u souboru
    assert "Zkopírováno 4 z 4 souborů" in r.stdout

    # navázání: celé soubory se přeskočí, nedokončený (kratší) se zkopíruje znovu
    (dirs["disk"] / "test" / names[2]).write_bytes(b"zac")
    r = _run(script, "to-disk", str(dirs["nas1"]), str(dirs["disk"]), "--yes", cwd=dirs["work"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Zkopírováno 1 z 4 souborů" in r.stdout and "Už bylo na cíli (přeskočeno): 3" in r.stdout
    assert (dirs["disk"] / "test" / names[2]).read_bytes() == names[2].encode()

    # soubor, který nejde zapsat, nezastaví ostatní; skript skončí chybou a nemaže
    blocked = dirs["nas2"] / "Seriál" / "Řada 1"
    blocked.mkdir(parents=True)
    blocked.chmod(0o555)
    _write(dirs["nas2"], "navic.mkv", b"x")
    script2 = _script(tmp_path / "work", _plan(names + ["jiny.mkv"], delete=["navic.mkv"]))
    _write(dirs["disk"], "test/jiny.mkv", b"jiny.mkv")
    (dirs["disk"] / "test/.sync-plan").unlink()
    try:
        r = _run(script2, "to-nas", str(dirs["disk"]), str(dirs["nas2"]), "--yes", cwd=dirs["work"])
    finally:
        blocked.chmod(0o755)
    assert r.returncode == 1
    assert "POZOR: 4 souborů se nepodařilo zkopírovat" in r.stdout
    assert (dirs["nas2"] / "jiny.mkv").read_bytes() == b"jiny.mkv"
    assert "mazání přeskočeno" in r.stdout and (dirs["nas2"] / "navic.mkv").exists()
