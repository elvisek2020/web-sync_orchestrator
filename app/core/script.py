"""Generátor bash skriptu pro přenos jednoho páru přes disk.

Jeden soubor, dva režimy:
  to-disk  (na NAS1)  NAS1 → <kořen disku>/<slug>/
  to-nas   (na NAS2)  <kořen disku>/<slug>/ → NAS2, volitelně smaže přebývající soubory

Seznamy cest jsou ve skriptu jako base64 s položkami oddělenými znakem NUL — přesně na bajt,
bez escapování a bez rizika, že by `$`, backtick, uvozovka nebo nový řádek v názvu souboru
spustily příkaz nebo rozbily skript. Kopíruje jedno volání `rsync -rt --from0 --files-from`
(bez vlastníků a práv — cílový disk je exFAT).
"""
from __future__ import annotations

import base64
import re
from datetime import datetime

from .plan import CONFLICT, PairPlan

SLUG_RE = re.compile(r"^[a-z0-9-]+$")


def _b64_list(paths: list[bytes]) -> str:
    data = b"".join(p + b"\0" for p in paths)
    return base64.encodebytes(data).decode("ascii").rstrip("\n")


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
        "sample_src": [s for s, _ in sample],
        "sample_tgt": [t for _, t in sample],
    }
    list_blocks = "\n".join(
        f"base64 -d > \"$TMP/{name}\" <<'__SYNC_LIST__' || die \"Nelze dekódovat seznam {name}.\"\n"
        f"{_b64_list(paths)}\n__SYNC_LIST__"
        for name, paths in lists.items()
    )

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
# Na disku se soubory ukládají do <kořen disku>/{slug}/.
# Volby: --dry-run  jen ukáže, co by se stalo
#        --yes      na všechny dotazy odpoví „ano“
# ============================================================

SLUG='{slug}'
PLAN='{plan_hash}'
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

human() {
  awk -v b="$1" 'BEGIN { split("B kB MB GB TB", u, " "); i = 1
    while (b >= 1000 && i < 5) { b /= 1000; i++ }
    if (i == 1) printf "%d %s", b, u[i]; else printf "%.1f %s", b, u[i] }'
}

count0() { tr -cd '\000' < "$1" | wc -c | tr -d ' '; }

command -v rsync >/dev/null 2>&1 || die "rsync není nainstalovaný."
command -v base64 >/dev/null 2>&1 || die "base64 není k dispozici."

[ "$SRC" = "/" ] || SRC="${SRC%/}"
[ "$DST" = "/" ] || DST="${DST%/}"
if [ "$MODE" = to-disk ]; then
  SRC_ROOT="$SRC"; DST_ROOT="${DST%/}/$SLUG"
else
  SRC_ROOT="${SRC%/}/$SLUG"; DST_ROOT="$DST"
fi
[ -d "$SRC_ROOT" ] || die "Zdrojová složka neexistuje: $SRC_ROOT"
[ -d "$DST" ] || die "Cílová složka neexistuje: $DST"

TMP="$(mktemp -d "${TMPDIR:-/tmp}/sync_${SLUG}.XXXXXX")" || die "Nelze vytvořit dočasnou složku."
trap 'rm -rf "$TMP"' EXIT

'''

_BODY_AFTER_LISTS = r'''
echo "========================================"
echo "  Pár: $SLUG   plán: $PLAN   režim: $MODE"
echo "  Zdroj: $SRC_ROOT"
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
  if [ -f "$SRC_ROOT/.sync-plan" ]; then
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
MISSING_SRC=0
: > "$TMP/ok"
: > "$TMP/missing"
while IFS= read -r -d '' f; do
  if [ -f "$SRC_ROOT/$f" ]; then
    printf '%s\0' "$f" >> "$TMP/ok"
  else
    MISSING_SRC=$((MISSING_SRC + 1))
    printf '%s\n' "$f" >> "$TMP/missing"
  fi
done < "$TMP/copy"
OK_COUNT="$(count0 "$TMP/ok")"

echo "Ke kopírování: $OK_COUNT z $COPY_TOTAL souborů ($(human "$COPY_BYTES") podle plánu)"
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

# ---- kopírování ----
RC=0
if [ "$OK_COUNT" -gt 0 ]; then
  if ask "Spustit kopírování $OK_COUNT souborů?" a; then
    OPTS=(-rt --modify-window=2 --partial --from0 "--files-from=$TMP/ok")
    if rsync --help 2>&1 | grep -q -- '--info'; then OPTS+=(--info=progress2); else OPTS+=(--progress); fi
    [ "$DRY_RUN" = 1 ] && OPTS+=(-n -v)
    [ "$DRY_RUN" = 1 ] || mkdir -p -- "$DST_ROOT" || die "Nelze vytvořit $DST_ROOT"
    echo ">> rsync ${OPTS[*]} \"$SRC_ROOT/\" \"$DST_ROOT/\""
    rsync "${OPTS[@]}" "$SRC_ROOT/" "$DST_ROOT/"
    RC=$?
    case "$RC" in
      0) echo "Kopírování dokončeno." ;;
      24) echo "Kopírování dokončeno; některé zdrojové soubory mezitím zmizely." ;;
      23) echo "POZOR: Některé soubory se nepodařilo přenést (viz výpis rsync výše)." ;;
      *) echo "CHYBA: rsync skončil s kódem $RC." ;;
    esac
  else
    echo "Kopírování přeskočeno."
    RC=-1
  fi
else
  echo "Není co kopírovat."
fi

COPY_OK=0
case "$RC" in 0|24) COPY_OK=1 ;; esac

if [ "$MODE" = to-disk ] && [ "$DRY_RUN" = 0 ] && [ "$COPY_OK" = 1 ]; then
  mkdir -p -- "$DST_ROOT" && printf 'PLAN=%s\nCREATED=%s\n' "$PLAN" "$(date '+%Y-%m-%d %H:%M:%S')" > "$DST_ROOT/.sync-plan"
fi

# ---- mazání přebývajících souborů na NAS2 ----
DELETED=0; DELETE_FAILED=0
DEL_COUNT="$(count0 "$TMP/delete")"
if [ "$MODE" = to-nas ] && [ "$DEL_COUNT" -gt 0 ]; then
  echo ""
  echo "Na cíli je $DEL_COUNT přebývajících souborů ($(human "$DELETE_BYTES")), které ve zdroji nejsou."
  if [ "$COPY_OK" != 1 ] && [ "$OK_COUNT" -gt 0 ]; then
    echo "Kopírování neproběhlo bez chyb — mazání přeskočeno."
  elif [ "$DRY_RUN" = 1 ]; then
    tr '\000' '\n' < "$TMP/delete" | head -n 20 | sed 's/^/  smazal by se: /'
  elif ask "Smazat je z $DST_ROOT?" n; then
    while IFS= read -r -d '' f; do
      p="$DST_ROOT/$f"
      [ -f "$p" ] || [ -L "$p" ] || continue
      if rm -f -- "$p"; then
        DELETED=$((DELETED + 1))
        d="$(dirname -- "$p")"
        while [ "$d" != "$DST_ROOT" ] && [ "${d#"$DST_ROOT"/}" != "$d" ] && rmdir -- "$d" 2>/dev/null; do
          d="$(dirname -- "$d")"
        done
      else
        DELETE_FAILED=$((DELETE_FAILED + 1))
      fi
    done < "$TMP/delete"
  else
    echo "Mazání přeskočeno."
  fi
fi

echo ""
echo "========================================"
echo "  Hotovo ($MODE)"
echo "    Zkopírováno (rsync):   $OK_COUNT souborů, kód $RC"
echo "    Chybí ve zdroji:       $MISSING_SRC"
[ "$MODE" = to-nas ] && echo "    Nahrazeno (NFC/NFD):   $REPLACED"
[ "$MODE" = to-nas ] && echo "    Smazáno na cíli:       $DELETED (chyby: $DELETE_FAILED)"
echo "========================================"

if [ "$RC" != 0 ] && [ "$RC" != 24 ] && [ "$RC" != -1 ]; then exit 1; fi
[ "$DELETE_FAILED" -eq 0 ] || exit 1
exit 0
'''
