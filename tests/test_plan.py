"""Porovnání, vzory k vynechání a přidělení kapacity — čistá logika."""
from __future__ import annotations

import unicodedata

from app.core.excludes import DEFAULT_EXCLUDE_PATTERNS, Excluder, parse_patterns
from app.core.keys import FileRec, key_from_remote
from app.core.plan import allocate, build_plan, compare, exfat_problem

from .conftest import rec

NO_EXCLUDES = Excluder([])


def test_categories():
    src = [rec("a.mkv", 10), rec("b.mkv", 20), rec("same.mkv", 5)]
    tgt = [rec("b.mkv", 21), rec("same.mkv", 5), rec("old.mkv", 7)]
    cmp = compare(src, tgt, NO_EXCLUDES)
    assert [i.key for i in cmp.missing] == ["a.mkv"]
    assert [i.key for i in cmp.conflict] == ["b.mkv"]
    assert [i.key for i in cmp.extra] == ["old.mkv"]
    assert cmp.same_count == 1 and cmp.same_size == 5


def test_conflict_ignores_mtime():
    src = [FileRec(b"a", "a", 10, 100.0)]
    tgt = [FileRec(b"a", "a", 10, 999999.0)]
    cmp = compare(src, tgt, NO_EXCLUDES)
    assert cmp.same_count == 1 and not cmp.conflict


def test_nfc_nfd_pair_up():
    nfd = unicodedata.normalize("NFD", "Pohádky/Příběh.mkv")
    src = [rec("Pohádky/Příběh.mkv", 3)]
    tgt = [FileRec(nfd.encode(), key_from_remote(nfd), 3, 0)]
    cmp = compare(src, tgt, NO_EXCLUDES)
    assert cmp.same_count == 1 and not cmp.missing and not cmp.extra


def test_mojibake_is_fixed_only_in_key():
    broken = "Ajťáci".encode("utf-8").decode("cp1252")
    assert key_from_remote(f"{broken}/x.avi") == "Ajťáci/x.avi"


def test_excludes_are_symmetric_and_not_substring():
    ex = Excluder(parse_patterns(".git\n@eaDir\n*.tmp\nSkip Me/*"))
    src = [rec("a/.gitignore"), rec("a/.git/config"), rec("x.tmp"), rec("Skip Me/a.mkv"), rec("keep.mkv")]
    tgt = [rec("b/@eaDir/thumb.jpg"), rec("y.TMP")]
    cmp = compare(src, tgt, ex)
    assert sorted(i.key for i in cmp.missing) == ["a/.gitignore", "keep.mkv"]
    assert cmp.extra == []  # vyloučené soubory na cíli se nesmí objevit jako „přebývá“
    assert cmp.excluded_count == 5


def test_default_patterns_cover_nas_junk():
    ex = Excluder(DEFAULT_EXCLUDE_PATTERNS)
    for path in ["a/@eaDir/x", "@Recycle/x.mkv", ".@__thumb/x", "#recycle/a", "a/.DS_Store", "a/._x.mkv", "Thumbs.db"]:
        assert ex.excluded(path), path
    assert not ex.excluded("Filmy/Film (2001)/Film.mkv")


def test_skips_move_items_out_of_plan():
    src = [rec("a"), rec("b")]
    cmp = compare(src, [], NO_EXCLUDES, skips={"b"})
    assert [i.key for i in cmp.missing] == ["a"]
    assert [i.key for i in cmp.skipped] == ["b"]


def test_collisions_are_problems_not_transfers():
    nfd = unicodedata.normalize("NFD", "é.txt")
    src = [FileRec("é.txt".encode(), "é.txt", 1, 0), FileRec(nfd.encode(), "é.txt", 1, 0)]
    cmp = compare(src, [], NO_EXCLUDES)
    assert not cmp.missing
    assert len(cmp.problems) == 2 and "Kolize" in cmp.problems[0].problem


def test_exfat_problems():
    assert exfat_problem('a/b"c.txt')
    assert exfat_problem("a/tečka./x")
    assert exfat_problem("a/new\nline")
    assert exfat_problem("Film (2001)/Film - CZ, EN.mkv") is None
    src = [rec("Dir/A.txt"), rec("dir/a.txt"), rec("ok.txt")]
    cmp = compare(src, [], NO_EXCLUDES)
    assert [i.key for i in cmp.missing] == ["ok.txt"]
    assert len(cmp.problems) == 2


def test_bad_encoding_never_deleted():
    tgt = [FileRec(b"\xff.txt", "�.txt", 1, 0)]
    cmp = compare([rec("x")], tgt, NO_EXCLUDES)
    assert cmp.extra == [] and cmp.problems[0].problem.startswith("Název souboru není")


def test_deletions_blocked_for_empty_source():
    cmp = compare([], [rec("x")], NO_EXCLUDES)
    plan = build_plan(1, cmp, on_disk=True, include_conflicts=True, include_extra=True)
    assert plan.deletions == [] and plan.deletion_blocked


def test_conflicts_only_when_enabled():
    cmp = compare([rec("a", 2)], [rec("a", 1)], NO_EXCLUDES)
    assert build_plan(1, cmp, on_disk=True, include_conflicts=False, include_extra=False).transfer == []
    assert len(build_plan(1, cmp, on_disk=True, include_conflicts=True, include_extra=False).transfer) == 1


def _plan(pid, sizes, on_disk=True):
    cmp = compare([rec(f"p{pid}/{i:03d}", s) for i, s in enumerate(sizes)], [], NO_EXCLUDES)
    return build_plan(pid, cmp, on_disk=on_disk, include_conflicts=True, include_extra=False)


def test_allocation_first_fit_across_pairs_in_order():
    a, b, c = _plan(1, [40, 70, 10]), _plan(2, [30, 25]), _plan(3, [1], on_disk=False)
    remaining = allocate([a, b, c], 100)
    assert [i.size for i in a.selected] == [40, 10]   # 70 se nevešlo, 10 ano (first-fit)
    assert [i.size for i in a.deferred] == [70]
    assert [i.size for i in b.selected] == [30]
    assert [i.size for i in b.deferred] == [25]
    assert c.selected == [] and c.deferred == []       # není zahrnutý do přenosu
    assert remaining == 20


def test_allocation_exact_fit_and_no_limit():
    a = _plan(1, [50, 50])
    allocate([a], 100)
    assert len(a.selected) == 2 and not a.deferred
    b = _plan(1, [10**15])
    allocate([b], 0)  # bez limitu
    assert len(b.selected) == 1


def test_plan_is_deterministic():
    src = [rec(f"f{i}", i + 1) for i in range(50)]
    p1 = build_plan(1, compare(list(reversed(src)), [], NO_EXCLUDES), on_disk=True, include_conflicts=True, include_extra=False)
    p2 = build_plan(1, compare(src, [], NO_EXCLUDES), on_disk=True, include_conflicts=True, include_extra=False)
    allocate([p1], 500)
    allocate([p2], 500)
    assert p1.plan_hash() == p2.plan_hash()
    assert [i.key for i in p1.selected] == [i.key for i in p2.selected]
