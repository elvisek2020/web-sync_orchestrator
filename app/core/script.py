"""Generátor bash skriptu pro přenos jednoho páru přes disk.

Jeden soubor, dva režimy:
  to-disk  (na NAS1)  NAS1 → <kořen disku>/<slug>/
  to-nas   (na NAS2)  <kořen disku>/<slug>/ → NAS2, volitelně smaže přebývající soubory

Seznamy cest jsou ve skriptu jako base64 s položkami oddělenými znakem NUL — přesně na bajt,
bez escapování a bez rizika, že by `$`, backtick, uvozovka nebo nový řádek v názvu souboru
spustily příkaz nebo rozbily skript. Kopíruje se po souborech (`rsync -t`, bez vlastníků a práv —
cílový disk je exFAT): u každého souboru se vypíše celkový průběh a odhad konce, soubory, které už
na cíli jsou (navázání po přerušení), se přeskočí. Funguje stejně s rsync 3.x i s openrsync na Macu.
"""
from __future__ import annotations

import base64
import re
import unicodedata
from datetime import datetime

from .plan import CONFLICT, PairPlan

SLUG_RE = re.compile(r"^[a-z0-9-]+$")


def _b64_list(paths: list[bytes]) -> str:
    data = b"".join(p + b"\0" for p in paths)
    return base64.encodebytes(data).decode("ascii").rstrip("\n")


def _variant(path: bytes, form: str) -> bytes:
    """Stejná cesta s diakritikou v jiném zápisu (NFC složeně / NFD rozloženě)."""
    return unicodedata.normalize(form, path.decode("utf-8", "surrogateescape")).encode("utf-8", "surrogateescape")


def _comment(text: str) -> str:
    return "".join(c if c.isprintable() else "?" for c in text)


def _human(size: int) -> str:
    value, units = float(size), ["B", "kB", "MB", "GB", "TB"]
    i = 0
    while value >= 1000 and i < len(units) - 1:
        value /= 1000
        i += 1
    return f"{int(value)} {units[i]}" if i == 0 else f"{value:.1f} {units[i]}".replace(".", ",")


def script_filename(slug: str) -> str:
    return f"sync_{slug}.sh"


def generate_script(*, pair_name: str, slug: str, plan: PairPlan, source_desc: str, target_desc: str,
                    generated_at: datetime | None = None) -> str:
    if not SLUG_RE.match(slug):
        raise ValueError(f"Neplatný slug páru: {slug!r}")
    generated_at = generated_at or datetime.now()
    plan_hash = plan.plan_hash()

    copy_paths = [i.src.path for i in plan.selected]
    copy_bytes = sum(i.src.size for i in plan.selected)
    replace_paths = [i.tgt.path for i in plan.selected
                     if i.category == CONFLICT and i.tgt is not None and i.tgt.path != i.src.path]
    delete_paths = [i.tgt.path for i in plan.deletions]
    delete_bytes = sum(i.tgt.size for i in plan.deletions)
    sample = plan.comparison.same_sample

    lists = {
        "copy": copy_paths,
        "replace": replace_paths,
        "delete": delete_paths,
        # Cíl připojený přes síť (např. SMB na Macu) může diakritiku při hledání převést
        # na jiný zápis — mazání proto zkouší i NFC a NFD variantu téže cesty.
        "delete_nfc": [_variant(p, "NFC") for p in delete_paths],
        "delete_nfd": [_variant(p, "NFD") for p in delete_paths],
        "sample_src": [s for s, _ in sample],
        "sample_tgt": [t for _, t in sample],
    }
    list_blocks = "\n".join(
        f"base64 -d > \"$TMP/{name}\" <<'__SYNC_LIST__' || die \"Nelze dekódovat seznam {name}.\"\n"
        f"{_b64_list(paths)}\n__SYNC_LIST__"
        for name, paths in lists.items()
    )
    # velikosti podle plánu, řádek po řádku ve stejném pořadí jako seznam copy (pro celkový průběh)
    sizes = "".join(f"{i.src.size}\n" for i in plan.selected)
    list_blocks += f"\ncat > \"$TMP/copy_sizes\" <<'__SYNC_SIZES__'\n{sizes}__SYNC_SIZES__"

    header = f"""#!/usr/bin/env bash
# ============================================================
# Sync Orchestrator — pár „{_comment(pair_name)}“
# Vygenerováno: {generated_at.strftime("%Y-%m-%d %H:%M")}   Plán: {plan_hash}
# ------------------------------------------------------------
# Kopírovat:        {len(copy_paths)} souborů ({_human(copy_bytes)})
# Odloženo:         {len(plan.deferred)} souborů ({_human(plan.deferred_size)}) — nevešlo se na disk
# Smazat na cíli:   {len(delete_paths)} souborů ({_human(delete_bytes)}) — jen po potvrzení
# Zdroj v aplikaci: {_comment(source_desc)}
# Cíl v aplikaci:   {_comment(target_desc)}
# ------------------------------------------------------------
# Použití:
#   1) na NAS1:  bash {script_filename(slug)} to-disk <složka na NAS1> <kořen disku>
#   2) na NAS2:  bash {script_filename(slug)} to-nas  <kořen disku> <složka na NAS2>
# Na disku se soubory ukládají do <kořen disku>/{slug}/ (pro to-nas lze zadat i přímo tuto složku).
# Když se jen maže (není co kopírovat), to-nas disk nepotřebuje — pusťte ho přímo na NAS2.
# Volby: --dry-run  jen ukáže, co by se stalo
#        --yes      na všechny dotazy odpoví „ano“
# ============================================================

SLUG='{slug}'
PLAN='{plan_hash}'
COPY_COUNT={len(copy_paths)}
COPY_BYTES={copy_bytes}
DELETE_BYTES={delete_bytes}
"""
    return header + _BODY_BEFORE_LISTS + list_blocks + "\n" + _BODY_AFTER_LISTS


_BODY_BEFORE_LISTS = r'''
set -u

usage() {
  echo "Použití:"
  echo "  bash $0 to-disk <složka na NAS1> <kořen disku>"
  echo "  bash $0 to-nas  <kořen disku> <složka na NAS2>"
  echo "Volby: --dry-run (jen ukáže, co by se stalo), --yes (odpoví „ano“ na dotazy)"
  exit "${1:-2}"
}

die() { echo "CHYBA: $*" >&2; exit 1; }

MODE=""; SRC=""; DST=""; DRY_RUN=0; ASSUME_YES=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --yes) ASSUME_YES=1 ;;
    -h|--help) usage 0 ;;
    *)
      if [ -z "$MODE" ]; then MODE="$arg"
      elif [ -z "$SRC" ]; then SRC="$arg"
      elif [ -z "$DST" ]; then DST="$arg"
      else usage 2
      fi ;;
  esac
done

case "$MODE" in to-disk|to-nas) ;; *) usage 2 ;; esac
[ -n "$SRC" ] && [ -n "$DST" ] || usage 2

# ask "otázka" a|n  → návratový kód 0 = ano
ask() {
  local question="$1" default="$2" answer=""
  if [ "$ASSUME_YES" = 1 ]; then echo "$question → ano (--yes)"; return 0; fi
  if { : </dev/tty; } 2>/dev/null; then
    if [ "$default" = a ]; then printf '%s [A/n]: ' "$question"; else printf '%s [a/N]: ' "$question"; fi
    read -r answer </dev/tty || answer=""
  else
    echo "$question → bez terminálu, výchozí volba"
  fi
  [ -z "$answer" ] && answer="$default"
  case "$answer" in a|A|ano|Ano|ANO|y|Y|yes) return 0 ;; *) return 1 ;; esac
}

# velikost čitelně, vždy s desetinnou čárkou (nezávisle na jazyku terminálu)
human() {
  LC_ALL=C awk -v b="$1" 'BEGIN { split("B kB MB GB TB", u, " "); i = 1
    while (b >= 1000 && i < 5) { b /= 1000; i++ }
    if (i == 1) { printf "%d %s", b, u[i]; exit }
    s = sprintf("%.1f %s", b, u[i]); sub(/\./, ",", s); printf "%s", s }'
}

count0() { tr -cd '\000' < "$1" | wc -c | tr -d ' '; }

# délka trvání: 41 s / 9 min 52 s / 2 h 05 min
dur() {
  local s="$1"
  if [ "$s" -ge 3600 ]; then printf '%d h %02d min' $((s / 3600)) $((s % 3600 / 60))
  elif [ "$s" -ge 60 ]; then printf '%d min %02d s' $((s / 60)) $((s % 60))
  else printf '%d s' "$s"; fi
}

# procenta s jedním desetinným místem
pct() {
  local p=1000
  [ "$2" -gt 0 ] && p=$(($1 * 1000 / $2))
  printf '%d,%d %%' $((p / 10)) $((p % 10))
}

# velikost souboru a hodiny z unixového času — GNU (Synology) i BSD (Mac) varianta
if stat -c %s -- / >/dev/null 2>&1; then fsize() { stat -c %s -- "$1" 2>/dev/null; }
else fsize() { stat -f %z -- "$1" 2>/dev/null; }; fi
if date -d @0 +%H:%M >/dev/null 2>&1; then at_time() { date -d "@$1" +%H:%M; }
elif date -r 0 +%H:%M >/dev/null 2>&1; then at_time() { date -r "$1" +%H:%M; }
else at_time() { :; }; fi

command -v rsync >/dev/null 2>&1 || die "rsync není nainstalovaný."
command -v base64 >/dev/null 2>&1 || die "base64 není k dispozici."

[ "$SRC" = "/" ] || SRC="${SRC%/}"
[ "$DST" = "/" ] || DST="${DST%/}"
if [ "$MODE" = to-disk ]; then
  SRC_ROOT="$SRC"; DST_ROOT="${DST%/}/$SLUG"
else
  SRC_ROOT="${SRC%/}/$SLUG"; DST_ROOT="$DST"
  # zadaná rovnou složka páru na disku (obsahuje .sync-plan)?
  if [ ! -d "$SRC_ROOT" ] && [ -f "${SRC%/}/.sync-plan" ]; then SRC_ROOT="${SRC%/}"; fi
fi
SRC_NEEDED=1
if [ ! -d "$SRC_ROOT" ]; then
  if [ "$MODE" = to-nas ] && [ "$COPY_COUNT" = 0 ]; then
    SRC_NEEDED=0   # jen mazání na cíli — data z disku nejsou potřeba
  else
    die "Zdrojová složka neexistuje: $SRC_ROOT"
  fi
fi
[ -d "$DST" ] || die "Cílová složka neexistuje: $DST"

TMP="$(mktemp -d "${TMPDIR:-/tmp}/sync_${SLUG}.XXXXXX")" || die "Nelze vytvořit dočasnou složku."
trap 'rm -rf "$TMP"' EXIT

'''

_BODY_AFTER_LISTS = r'''
echo "========================================"
echo "  Pár: $SLUG   plán: $PLAN   režim: $MODE"
if [ "$SRC_NEEDED" = 1 ]; then echo "  Zdroj: $SRC_ROOT"; else echo "  Zdroj: (není potřeba — jen mazání na cíli)"; fi
echo "  Cíl:   $DST_ROOT"
[ "$DRY_RUN" = 1 ] && echo "  (zkouška nanečisto — nic se nemění)"
echo "========================================"

# ---- kontrola, že jsou zadané správné složky ----
check_sample() {
  local list="$1" root="$2" label="$3" total=0 found=0 f
  while IFS= read -r -d '' f; do
    total=$((total + 1))
    [ -e "$root/$f" ] && found=$((found + 1))
  done < "$list"
  if [ "$total" -gt 0 ] && [ $((found * 2)) -lt "$total" ]; then
    echo "VAROVÁNÍ: V $label ($root) chybí $((total - found)) z $total souborů, které tam podle skenu jsou."
    echo "          Není zadaná špatná složka?"
    ask "Přesto pokračovat?" n || die "Přerušeno."
  fi
}

if [ "$MODE" = to-disk ]; then
  check_sample "$TMP/sample_src" "$SRC_ROOT" "zdrojové složce"
else
  check_sample "$TMP/sample_tgt" "$DST_ROOT" "cílové složce"
  if [ "$SRC_NEEDED" = 0 ]; then
    :   # bez disku není co porovnávat s plánem na disku
  elif [ -f "$SRC_ROOT/.sync-plan" ]; then
    DISK_PLAN="$(sed -n 's/^PLAN=//p' "$SRC_ROOT/.sync-plan" | head -n 1)"
    if [ "$DISK_PLAN" != "$PLAN" ]; then
      echo "VAROVÁNÍ: Data na disku jsou z jiného plánu ($DISK_PLAN), tento skript je pro plán $PLAN."
      ask "Přesto pokračovat?" n || die "Přerušeno."
    fi
  else
    echo "VAROVÁNÍ: Na disku chybí $SRC_ROOT/.sync-plan — proběhl krok to-disk?"
    ask "Přesto pokračovat?" n || die "Přerušeno."
  fi
fi

# ---- co opravdu existuje ve zdroji ----
COPY_TOTAL="$(count0 "$TMP/copy")"
MISSING_SRC=0; OK_COUNT=0; OK_BYTES=0
: > "$TMP/ok"
: > "$TMP/ok_sizes"
: > "$TMP/missing"
while IFS= read -r -d '' f <&3 && read -r sz <&4; do
  if [ -f "$SRC_ROOT/$f" ]; then
    printf '%s\0' "$f" >> "$TMP/ok"
    printf '%s\n' "$sz" >> "$TMP/ok_sizes"
    OK_COUNT=$((OK_COUNT + 1)); OK_BYTES=$((OK_BYTES + sz))
  else
    MISSING_SRC=$((MISSING_SRC + 1))
    printf '%s\n' "$f" >> "$TMP/missing"
  fi
done 3<"$TMP/copy" 4<"$TMP/copy_sizes"

echo "Ke kopírování: $OK_COUNT z $COPY_TOTAL souborů ($(human "$OK_BYTES"))"
if [ "$MISSING_SRC" -gt 0 ]; then
  echo "Ve zdroji chybí $MISSING_SRC souborů (přeskočí se), např.:"
  head -n 10 "$TMP/missing" | sed 's/^/  - /'
fi

# ---- volné místo na disku ----
if [ "$MODE" = to-disk ] && [ "$OK_COUNT" -gt 0 ]; then
  AVAIL_KB="$(df -Pk "$DST" 2>/dev/null | awk 'NR == 2 { print $4 }')"
  NEED_KB=$(( (COPY_BYTES + 1023) / 1024 ))
  if [ -n "$AVAIL_KB" ] && [ "$AVAIL_KB" -lt "$NEED_KB" ]; then
    echo "VAROVÁNÍ: Na disku je volných $(human $((AVAIL_KB * 1024))), plán potřebuje $(human "$COPY_BYTES")."
    echo "          (Pokud navazujete na přerušený běh, část už na disku je.)"
    ask "Přesto pokračovat?" n || die "Přerušeno."
  fi
fi

# ---- konflikty s jinak zapsaným názvem na cíli (NFC/NFD) ----
REPLACED=0
if [ "$MODE" = to-nas ] && [ "$(count0 "$TMP/replace")" -gt 0 ]; then
  while IFS= read -r -d '' f; do
    if [ -e "$DST_ROOT/$f" ]; then
      if [ "$DRY_RUN" = 1 ]; then echo "  nahradil by se: $f"; else rm -f -- "$DST_ROOT/$f" && REPLACED=$((REPLACED + 1)); fi
    fi
  done < "$TMP/replace"
fi

# ---- kopírování: po souborech, u každého celkový průběh; průběh souboru ukazuje rsync ----
COPIED=0; COPIED_BYTES=0; DONE_BYTES=0; ALREADY=0; FAILED=0; STOPPED=""; COPY_OK=1
: > "$TMP/failed"

# [7/753 · 1,6 % · 8,2 GB z 512,0 GB · 13,9 MB/s · zbývá ~ 10 h 04 min (kolem 06:12)] Složka/
progress_line() {
  local line el speed rest at
  line="[$1/$OK_COUNT · $(pct "$DONE_BYTES" "$OK_BYTES") · $(human "$DONE_BYTES") z $(human "$OK_BYTES")"
  el=$((SECONDS - COPY_START))
  if [ "$COPIED_BYTES" -gt 0 ] && [ "$el" -gt 0 ]; then
    speed=$((COPIED_BYTES / el))
    rest=$(( (OK_BYTES - DONE_BYTES) * el / COPIED_BYTES ))
    line="$line · $(human "$speed")/s · zbývá ~ $(dur "$rest")"
    if [ "$rest" -lt 72000 ]; then
      at="$(at_time $(( $(date +%s) + rest )))"
      [ -n "$at" ] && line="$line (kolem $at)"
    fi
  fi
  line="$line]"
  case "$2" in */*) line="$line ${2%/*}/" ;; esac
  printf '%s\n' "$line"
}

if [ "$OK_COUNT" -gt 0 ]; then
  if ask "Spustit kopírování $OK_COUNT souborů ($(human "$OK_BYTES"))?" a; then
    [ "$DRY_RUN" = 1 ] || mkdir -p -- "$DST_ROOT" || die "Nelze vytvořit $DST_ROOT"
    # relativní cesta s dvojtečkou by rsync považoval za vzdálený stroj
    case "$SRC_ROOT" in /*) S="$SRC_ROOT" ;; *) S="./$SRC_ROOT" ;; esac
    case "$DST_ROOT" in /*) D="$DST_ROOT" ;; *) D="./$DST_ROOT" ;; esac
    INTERRUPTED=0
    trap 'INTERRUPTED=1' INT
    COPY_START=$SECONDS; N=0; IN_ROW=0
    while IFS= read -r -d '' f <&3 && read -r sz <&4; do
      N=$((N + 1))
      if [ "$DRY_RUN" = 1 ]; then
        echo "  zkopíroval by se: $f ($(human "$sz"))"
        continue
      fi
      # už je na cíli celý (navázání po přerušení) → přeskočit
      if [ -f "$D/$f" ] && [ "$(fsize "$D/$f")" = "$(fsize "$S/$f")" ]; then
        ALREADY=$((ALREADY + 1)); DONE_BYTES=$((DONE_BYTES + sz))
        continue
      fi
      progress_line "$N" "$f"
      case "$f" in */*) [ -d "$D/${f%/*}" ] || mkdir -p -- "$D/${f%/*}" ;; esac
      rsync -t --modify-window=2 --partial --progress -- "$S/$f" "$D/$f"
      rc=$?
      if [ "$INTERRUPTED" = 1 ] || [ "$rc" = 20 ]; then STOPPED="přerušeno"; break; fi
      if [ "$rc" = 0 ]; then
        COPIED=$((COPIED + 1)); COPIED_BYTES=$((COPIED_BYTES + sz)); DONE_BYTES=$((DONE_BYTES + sz)); IN_ROW=0
      else
        FAILED=$((FAILED + 1)); IN_ROW=$((IN_ROW + 1)); DONE_BYTES=$((DONE_BYTES + sz))
        printf '%s (rsync kód %s)\n' "$f" "$rc" >> "$TMP/failed"
        echo "  ! Soubor se nepodařilo zkopírovat (rsync kód $rc), pokračuji dalším."
        if [ "$IN_ROW" -ge 5 ]; then STOPPED="5 chyb za sebou — není odpojený disk nebo síť?"; break; fi
      fi
    done 3<"$TMP/ok" 4<"$TMP/ok_sizes"
    trap - INT
    EL=$((SECONDS - COPY_START))

    echo ""
    if [ "$DRY_RUN" = 1 ]; then
      echo "Zkopírovalo by se $OK_COUNT souborů ($(human "$OK_BYTES"))."
    else
      line="Zkopírováno $COPIED z $OK_COUNT souborů ($(human "$COPIED_BYTES")) za $(dur "$EL")"
      if [ "$EL" -gt 0 ] && [ "$COPIED_BYTES" -gt 0 ]; then line="$line, průměrně $(human $((COPIED_BYTES / EL)))/s"; fi
      echo "$line."
      [ "$ALREADY" -gt 0 ] && echo "Už bylo na cíli (přeskočeno): $ALREADY"
      if [ "$FAILED" -gt 0 ]; then
        echo "POZOR: $FAILED souborů se nepodařilo zkopírovat, např.:"
        head -n 10 "$TMP/failed" | sed 's/^/  - /'
      fi
      if [ -n "$STOPPED" ]; then
        echo "Kopírování zastaveno ($STOPPED)."
        echo "Při dalším spuštění naváže — hotové soubory se přeskočí."
      fi
      if [ "$FAILED" -gt 0 ] || [ -n "$STOPPED" ]; then COPY_OK=0; fi
    fi
    [ "$STOPPED" = "přerušeno" ] && exit 130
  else
    echo "Kopírování přeskočeno."
    COPY_OK=0
  fi
else
  echo "Není co kopírovat."
fi

if [ "$MODE" = to-disk ] && [ "$DRY_RUN" = 0 ] && [ "$COPY_OK" = 1 ]; then
  mkdir -p -- "$DST_ROOT" && printf 'PLAN=%s\nCREATED=%s\n' "$PLAN" "$(date '+%Y-%m-%d %H:%M:%S')" > "$DST_ROOT/.sync-plan"
fi

# ---- mazání přebývajících souborů na NAS2 ----
DELETED=0; DELETE_FAILED=0; NOT_FOUND=0
: > "$TMP/notfound"
DEL_COUNT="$(count0 "$TMP/delete")"

# find_target <cesta> <cesta NFC> <cesta NFD> → FOUND = skutečná cesta na cíli
find_target() {
  local cand
  for cand in "$1" "$2" "$3"; do
    if [ -f "$DST_ROOT/$cand" ] || [ -L "$DST_ROOT/$cand" ]; then FOUND="$DST_ROOT/$cand"; return 0; fi
  done
  FOUND=""
  return 1
}

if [ "$MODE" = to-nas ] && [ "$DEL_COUNT" -gt 0 ]; then
  echo ""
  echo "Na cíli je $DEL_COUNT přebývajících souborů ($(human "$DELETE_BYTES")), které ve zdroji nejsou."
  DO_DELETE=0
  if [ "$COPY_OK" != 1 ] && [ "$OK_COUNT" -gt 0 ]; then
    echo "Kopírování neproběhlo bez chyb — mazání přeskočeno."
  elif [ "$DRY_RUN" = 1 ]; then
    DO_DELETE=1   # jen projde a spočítá, nic nesmaže
  elif ask "Smazat je z $DST_ROOT?" n; then
    DO_DELETE=1
  else
    echo "Mazání přeskočeno."
  fi
  if [ "$DO_DELETE" = 1 ]; then
    while IFS= read -r -d '' f <&3 && IFS= read -r -d '' f_nfc <&4 && IFS= read -r -d '' f_nfd <&5; do
      if ! find_target "$f" "$f_nfc" "$f_nfd"; then
        NOT_FOUND=$((NOT_FOUND + 1))
        printf '%s\n' "$f" >> "$TMP/notfound"
        continue
      fi
      if [ "$DRY_RUN" = 1 ]; then
        DELETED=$((DELETED + 1))
        [ "$DELETED" -le 20 ] && echo "  smazal by se: $f"
        continue
      fi
      if rm -f -- "$FOUND"; then
        DELETED=$((DELETED + 1))
        d="$(dirname -- "$FOUND")"
        while [ "$d" != "$DST_ROOT" ] && [ "${d#"$DST_ROOT"/}" != "$d" ] && rmdir -- "$d" 2>/dev/null; do
          d="$(dirname -- "$d")"
        done
      else
        DELETE_FAILED=$((DELETE_FAILED + 1))
      fi
    done 3<"$TMP/delete" 4<"$TMP/delete_nfc" 5<"$TMP/delete_nfd"
    if [ "$NOT_FOUND" -gt 0 ]; then
      echo ""
      echo "POZOR: $NOT_FOUND z $DEL_COUNT přebývajících souborů se na cíli nepodařilo najít, např.:"
      head -n 10 "$TMP/notfound" | sed 's/^/  - /'
      echo "  Buď už byly smazané, nebo je cíl připojený tak, že cesty nesedí"
      echo "  (typicky síťový disk na Macu). Pak skript pusťte přímo na NAS2."
    fi
  fi
fi

echo ""
echo "========================================"
echo "  Hotovo ($MODE)"
echo "    Zkopírováno:           $COPIED z $OK_COUNT (už na cíli: $ALREADY, chyby: $FAILED)"
echo "    Chybí ve zdroji:       $MISSING_SRC"
[ "$MODE" = to-nas ] && echo "    Nahrazeno (NFC/NFD):   $REPLACED"
if [ "$MODE" = to-nas ]; then
  if [ "$DRY_RUN" = 1 ]; then LABEL="Smazalo by se na cíli:"; else LABEL="Smazáno na cíli:      "; fi
  echo "    $LABEL $DELETED (chyby: $DELETE_FAILED, nenalezeno: $NOT_FOUND)"
fi
echo "========================================"

if [ "$FAILED" -gt 0 ] || [ -n "$STOPPED" ]; then exit 1; fi
[ "$DELETE_FAILED" -eq 0 ] || exit 1
if [ "$DRY_RUN" = 0 ] && [ "$NOT_FOUND" -gt 0 ]; then exit 1; fi
exit 0
'''
