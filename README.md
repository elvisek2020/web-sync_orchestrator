# Sync Orchestrator

Plánovač přenosu velkých objemů dat z NAS1 na NAS2 přes fyzicky přenášený disk (exFAT), bez přímé síťové synchronizace.

## 📋 Popis

Složky na NAS1 a NAS2 tvoří **páry** (Filmy, Seriály, Pohádky…). Tlačítkem **Aktualizovat** aplikace přeskenuje obě strany, sama je porovná a spočítá plán. Výstupem je **bash skript** pro daný pár:

1. na NAS1 zkopíruje chybějící a změněné soubory na disk (`to-disk`),
2. disk se fyzicky přenese k NAS2,
3. na NAS2 soubory z disku nahraje a po potvrzení smaže soubory, které na NAS1 už nejsou (`to-nas`).

Aplikace běží jednou, u NAS1 (NAS1 je v kontejneru připojený pro čtení, NAS2 čte přes SSH/SFTP). **Sama nic nekopíruje ani nemaže** — jen skenuje a generuje skript.

## ✨ Funkce

- **Páry** — stálá dvojice složek NAS1 ↔ NAS2; pořadí párů určuje, v jakém pořadí se plní disk.
- **Aktualizovat / Aktualizovat vše** — sken obou stran na pozadí, živý průběh, možnost zrušit.
- **Jen poslední stav** — nový úspěšný sken nahradí starý; neúspěšný sken nechá platná předchozí data.
- **Porovnání** — `chybí` (jen na NAS1), `konflikt` (liší se velikost), `přebývá` (jen na NAS2), `shodné`.
  Názvy se párují po normalizaci Unicode (NFC/NFD), čas změny se nepoužívá.
- **Kapacita disku** — plán rozdělí zadanou kapacitu mezi páry zaškrtnuté *Zahrnout do přenosu*; co se nevejde, je *odloženo* a po dalším přenosu a novém skenu se objeví samo.
- **Ruční vyřazení souborů** — odškrtnutý soubor zůstane vyřazený i po dalších skenech.
- **Vzory k vynechání** — výchozí (`@eaDir`, `.DS_Store`, `@Recycle`, `*.tmp`…) i vlastní pro pár; platí na obou stranách.
- **Problémy** — názvy, které exFAT neuloží (`: * ? " < > |`, koncová tečka), kolize názvů a neplatné kódování se nepřenáší ani nemažou, jen se ukážou.
- **Skript** — seznamy cest jsou uvnitř jako base64 (bezpečné pro jakékoli znaky v názvu), kopíruje jedno volání `rsync`, kontroluje volné místo, správnost složek a shodu plánu mezi `to-disk` a `to-nas`.

## 📖 Použití

### Nastavení (jednou)

1. **Nastavení → SSH hosté → Přidat hosta**: adresa, port, uživatel a heslo NAS2 (heslo se už nikdy nezobrazí). Tlačítko *Otestovat spojení*.
2. **Nastavení → Páry → Přidat pár**: název, zdroj (lokálně, cesta relativně k `/mnt/nas1`, např. `NAS-FILMY`) a cíl (SSH host + absolutní cesta, např. `/share/Filmy`). Složku lze vybrat tlačítkem *Procházet*, pak *Ověřit složky*.
3. **Nastavení → Disk pro přenos**: *Načíst volné místo* (je-li disk připojený do kontejneru přes `DISK_PATH`), nebo kapacitu v GB zadat ručně (1 TB = 1000 GB).

### Každý přenos

1. **Přehled → Aktualizovat vše** (nebo *Aktualizovat* u jednoho páru) a počkat na dokončení skenů.
2. Zkontrolovat čísla u párů, případně v **detailu páru** odškrtnout, co se přenášet nemá. Zaškrtnutím *Zahrnout do přenosu* určit, které páry se tentokrát vezou na disku.
3. **Skript** u páru → stáhne `sync_<pár>.sh`.
4. Na NAS1:

   ```bash
   bash sync_filmy.sh to-disk /share/NAS-FILMY /share/external/USBDisk1
   ```

   Soubory se uloží do `<kořen disku>/filmy/`.
5. Disk přenést a připojit k NAS2, **stejný skript** spustit tam:

   ```bash
   bash sync_filmy.sh to-nas /share/external/USBDisk1 /share/Filmy
   ```

   Před mazáním přebývajících souborů se skript zeptá (výchozí odpověď je *ne*).
6. Po přenosu znovu **Aktualizovat** — odložené soubory se objeví v dalším plánu.

Volby skriptu: `--dry-run` (jen ukáže, co by se stalo), `--yes` (na dotazy odpoví „ano“). Skript potřebuje `bash`, `rsync` ≥ 3.0 a `base64`.

## 🚀 Deployment

### Předpoklady

- Docker a Docker Compose na NAS1
- složky NAS1 dostupné na hostiteli (připojí se do kontejneru jen pro čtení)
- SSH/SFTP přístup k NAS2
- přístup k aplikaci chráněný reverzní proxy / sítí (aplikace nemá vlastní přihlášení)

### Docker Compose

```yaml
services:
  app:
    image: ghcr.io/elvisek2020/web-sync_orchestrator:latest
    container_name: nas-sync-orchestrator
    restart: unless-stopped
    ports:
      - "8080:8000"
    environment:
      - TZ=Europe/Prague
      - LOG_LEVEL=INFO
      - DATABASE_PATH=/data/sync_orchestrator.db
      - LOCAL_ROOT=/mnt/nas1
    volumes:
      - ./data:/data              # databáze (lokální disk, vlastník UID 1000)
      - /share:/mnt/nas1:ro       # NAS1 — upravit podle systému
      - /volumeUSB1/usbshare:/mnt/disk:ro   # volitelně: přenosový disk (jen pro načtení volného místa)
    # user: "0:0"                 # jen pokud UID 1000 nemá právo číst všechny složky NAS1
```

```bash
mkdir -p data && sudo chown 1000:1000 data
docker compose pull
docker compose up -d
```

Aplikace bude na `http://<nas1>:8080`.

**Poznámky:**

- Databáze (SQLite, WAL) musí ležet na **lokálním disku** hostitele, ne na síťovém sdílení.
- Kontejner běží jako UID 1000. Pokud sken NAS1 skončí chybou *„Nelze přečíst složku…“*, nemá tento uživatel práva — odkomentuj `user: "0:0"`.
- **Synology:** sdílené složky mají ACL (`drwxrwxrwx+`), které UID 1000 nepustí ani při zobrazených právech 777. Spusť kontejner pod svým uživatelem DSM (`id <uživatel>`), např. `user: "1026:100"` + `group_add: ["101"]` (administrators), a `./data` mu předej (`chown -R 1026:100 data`).
- Uvicorn běží s jedním workerem (stav běžících skenů je v paměti procesu).

### Přechod ze staré verze (v1)

v2 používá **novou databázi** — stará (`/mnt/usb/sync_orchestrator.db`) se nečte ani nemění a aplikace odmítne start, když na ni `DATABASE_PATH` ukazuje. V compose:

1. `DATABASE_PATH=/data/sync_orchestrator.db` a volume `./data:/data` (`mkdir data && chown 1000:1000 data`),
2. NAS1 připojit do `/mnt/nas1` jen pro čtení,
3. odebrat volumes `usb` a `nas2`,
4. po startu v Nastavení zadat SSH hosta a páry.

### Proměnné prostředí

| Proměnná | Výchozí | Význam |
|---|---|---|
| `DATABASE_PATH` | `/data/sync_orchestrator.db` | soubor databáze |
| `LOCAL_ROOT` | `/mnt/nas1` | kořen NAS1 v kontejneru; lokální cesty párů jsou relativní k němu |
| `DISK_PATH` | `/mnt/disk` | přenosový disk v kontejneru (volitelné) — tlačítko *Načíst volné místo* v Nastavení |
| `LOG_LEVEL` | `INFO` | úroveň logování (průběh skenů je vidět v `docker compose logs`) |
| `APP_NAME` | `Sync Orchestrator` | název v hlavičce |

### Update a rollback

```bash
docker compose pull && docker compose up -d
```

Rollback: v compose nastavit `image: ghcr.io/elvisek2020/web-sync_orchestrator:sha-<commit>`.

### GitHub a CI/CD

Push do `main` spustí `.github/workflows/docker.yml`: build pro `linux/amd64` a `linux/arm64` a push do GHCR s tagy `latest` a `sha-<commit>`.

## 🔧 Technická dokumentace

### 🏗️ Architektura

- **Jediný background job je sken.** Běží ve vlákně, soubory sbírá do paměti a do databáze je zapíše **jednou krátkou transakcí** (`BEGIN IMMEDIATE`). Neúspěšný nebo zrušený sken nechá platný předchozí; po restartu aplikace se nedokončené skeny označí jako selhané. Nejvýš jeden sken na jednoho hosta najednou.
- **Sken nikdy nepřeskakuje potichu.** Nečitelná složka, neexistující nebo prázdný zdroj = chyba skenu (jinak by vznikly falešné „přebývající“ soubory a skript by je smazal).
- **Porovnání a plán se nepersistují** — počítají se za běhu čistými funkcemi z posledních skenů (`app/core/plan.py`).
- UI je serverem renderované HTML (Jinja2) s HTMX; průběh skenů se obnovuje pollingem, jen když něco běží.

### Technický stack

- Python 3.12, FastAPI, Jinja2, HTMX
- SQLite přes SQLAlchemy Core (bez ORM)
- Paramiko (SFTP)
- design systém `app.css` (paleta corporate, světlý i tmavý režim)

### 📁 Struktura projektu

```
app/
├── main.py, config.py, db.py, common.py, templates_engine.py
├── core/            # čistá logika bez DB: klíče cest, vzory, plán, generátor skriptu
├── scan/            # lokální a SFTP skener, runner skenů
├── apps/
│   ├── overview/    # Přehled
│   ├── pairs/       # detail páru, stav párů, skript, CSV, log skenu
│   └── settings/    # páry, SSH hosté, kapacita, vzory
├── templates/
└── static/          # css/app.css, js/app.js, js/htmx.min.js, version.json
tests/               # pytest (plán, skenery, runner, skript, stránky)
e2e/                 # E2E prostředí: aplikace + falešný NAS2 (openssh-server) + testovací data
```

### 💻 Vývoj

#### Testování

Testy běží v kontejneru (skript se ověřuje skutečným během `rsync`):

```bash
docker build --target test -t sync-orchestrator-test . && docker run --rm sync-orchestrator-test
```

#### E2E prostředí

```bash
python3 e2e/make_data.py
docker compose -f e2e/docker-compose.yml up -d --build
```

Aplikace na `http://localhost:8090`, falešný NAS2: host `nas2`, port `2222`, uživatel `nas`, heslo `nas2heslo`. Skript lze pustit v kontejneru `shell` (viz komentář v `e2e/docker-compose.yml`).

### 📝 Historie změn

#### v.20260921.1500 — v2

- ✅ **Nový koncept „páry → Aktualizovat → skript“** místo fází, datasetů, skenů, porovnání a plánů zvlášť
- ✅ **Spolehlivé skeny**: jediný background job, zápis jednou transakcí, žádné zaseknuté `running`/`pending`, úklid po restartu, zrušení skenu
- ✅ **Bezpečnost dat**: sken s nečitelnou složkou nebo prázdným zdrojem selže (dřív skončil „dokončeno“ a vedl k mazání na NAS2)
- ✅ **Kapacita disku** zadaná ručně, rozdělená mezi páry; odložené soubory přijdou při dalším přenosu
- ✅ **Skript pro exFAT**: jeden soubor pro `to-disk` i `to-nas`, bezpečné seznamy cest, `rsync -rt --files-from`, kontroly složek, místa a plánu
- ✅ **UI na Jinja2 + HTMX** (bez Reactu a Node buildu), světlý i tmavý režim, mobil
- ✅ **SSH heslo se nevrací do prohlížeče**
- ❌ Odstraněno: kopírování z backendu, SAFE MODE, DB na USB, WebSocket, fáze, stránka Debug

Starší historie viz git (`git log`).
