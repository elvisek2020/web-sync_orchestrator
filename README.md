# Sync Orchestrator

Plánovač přenosu velkých objemů dat z NAS1 na NAS2 přes fyzicky přenášený disk (exFAT), bez přímé síťové synchronizace.

## 📋 Popis

Složky na NAS1 a NAS2 tvoří **páry** (Filmy, Seriály, Pohádky…). Tlačítkem **Aktualizovat** aplikace přeskenuje obě strany, sama je porovná a spočítá plán. Přenos pak probíhá ve třech krocích:

1. chybějící a změněné soubory se zkopírují na disk — **tlačítkem Přenos na disk** v aplikaci (disk připojený k NAS1), nebo skriptem (`to-disk`),
2. disk se fyzicky přenese k NAS2,
3. na NAS2 **bash skript** (aplikace ho uloží i na disk) soubory z disku nahraje a po potvrzení smaže soubory, které na NAS1 už nejsou (`to-nas`).

Aplikace běží jednou, u NAS1 (NAS1 je v kontejneru připojený pro čtení, NAS2 čte přes SSH/SFTP). Velké objemy jdou přes disk; menší věci (drobné soubory, konflikty, mazání přebývajících) umí aplikace přenést **přímo na NAS2** přes SFTP — ručně, nebo naplánovaně v nočním časovém okně.

## ✨ Funkce

- **Páry** — stálá dvojice složek NAS1 ↔ NAS2; pořadí párů určuje, v jakém pořadí se plní disk.
- **Aktualizovat / Aktualizovat vše** — sken obou stran na pozadí, živý průběh, možnost zrušit.
- **Jen poslední stav** — nový úspěšný sken nahradí starý; neúspěšný sken nechá platná předchozí data.
- **Porovnání** — `chybí` (jen na NAS1), `konflikt` (liší se velikost), `přebývá` (jen na NAS2), `shodné`.
  Názvy se párují po normalizaci Unicode (NFC/NFD), čas změny se nepoužívá.
- **Kapacita disku** — plán rozdělí zadanou kapacitu mezi páry s volbou *Zahrnout do přenosu* (detail páru → Volby páru); co se nevejde, je *odloženo* a po dalším přenosu a novém skenu se objeví samo.
- **Ruční vyřazení souborů** — odškrtnutý soubor zůstane vyřazený i po dalších skenech.
- **Vzory k vynechání** — výchozí (`@eaDir`, `.DS_Store`, `@Recycle`, `*.tmp`…) i vlastní pro pár; platí na obou stranách.
- **Problémy** — názvy, které exFAT neuloží (`: * ? " < > |`, koncová tečka), kolize názvů a neplatné kódování se nepřenáší ani nemažou, jen se ukážou.
- **Přenos na disk** — aplikace zkopíruje plán páru na připojený disk sama (průběh, zrušení, navázání) a uloží tam i skript pro `to-nas`.
- **Na disku** — zkopírované soubory se přesunou do záložky *Na disku* a Kopírovat se přepočítá na další várku; disky jde
  střídat a plnit postupně bez duplicit. Záložku vyprázdní Aktualizovat (nový sken NAS2), případně ručně tlačítko.
- **Vyčistit disk** — smaže celý obsah disku před dalším kolem, volitelně rovnou přeskenuje páry s daty k přenosu.
- **Přímý přenos NAS → NAS** — vybrané soubory přes SFTP rovnou na NAS2 (nahrání i smazání přebývajících), ručně nebo naplánovaně.
- **Plánování** — denní automatická aktualizace všech párů a časové okno pro naplánovaný přímý přenos.
- **Výsledek přenosu po souborech** — karta posledního přenosu (přímého i na disk) s tabulkou čas / soubor / stav; kartu jde odebrat, po novém skenu cíle zmizí sama.
- **Seznamy souborů** — záložky Kopírovat, Odloženo, Na disku, Konflikty, Přebývá, Vyřazené, Přímý přenos, Problémy; hledání, stránkování po 50, řazení podle cesty nebo velikosti; export CSV po povolení v *Nastavení → Další volby*.
- **Skript** — seznamy cest jsou uvnitř jako base64 (bezpečné pro jakékoli znaky v názvu), kopíruje `rsync` po souborech s celkovým průběhem a odhadem konce (přerušený běh naváže), kontroluje volné místo, správnost složek a shodu plánu mezi `to-disk` a `to-nas`.

## 📖 Použití

### Nastavení (jednou)

1. **Nastavení → SSH hosté → Přidat hosta**: adresa, port, uživatel a heslo NAS2 (heslo se už nikdy nezobrazí). Tlačítko *Otestovat spojení*.
2. **Nastavení → Páry → Přidat pár**: název, zdroj (lokálně, cesta relativně k `/mnt/nas1`, např. `NAS-FILMY`) a cíl (SSH host + absolutní cesta, např. `/share/Filmy`). Složku lze vybrat tlačítkem *Procházet*, pak *Ověřit složky*.
3. **Nastavení → Disk pro přenos**: *Načíst volné místo* (je-li disk připojený do kontejneru přes `DISK_PATH`), nebo kapacitu v GB zadat ručně (1 TB = 1000 GB).
4. Volitelně **Nastavení → Plánování**: čas automatické aktualizace a okno pro naplánovaný přímý přenos (viz níže).

### Každý přenos

1. **Přehled → Aktualizovat vše** (nebo *Aktualizovat* u jednoho páru) a počkat na dokončení skenů.
2. Zkontrolovat čísla u párů, případně v **detailu páru** odškrtnout, co se přenášet nemá. Ve **Volbách páru** (detail páru) volbou *Zahrnout do přenosu* určit, které páry se tentokrát vezou na disku.
3. V detailu páru **Přenos na disk** (disk připojený k NAS1 a do kontejneru jako `DISK_PATH`, viz Deployment).
   Aplikace zkopíruje soubory ze záložky *Kopírovat* do `<kořen disku>/<pár>/` a do kořene disku uloží skript
   `sync_<pár>.sh` s manifestem `.sync-plan` — obsahují všechny soubory páru, které na tomto disku leží.
   Panel ukazuje průběh jako u přímého přenosu; přenos jde zrušit a příště naváže.

   Zkopírované soubory se přesunou do záložky **Na disku** a *Kopírovat* se přepočítá na další várku (podle
   kapacity v Nastavení). Můžeš tak připojit další disk (upravit kapacitu) a kopírovat dál, nebo přikopírovat na
   tentýž disk — nic se nezkopíruje dvakrát. Záložku *Na disku* vyprázdní až **Aktualizovat** (nový sken NAS2),
   případně ručně tlačítko *Vyprázdnit Na disku*.

   Bez disku v kontejneru: **Stáhnout skript** a na NAS1 spustit

   ```bash
   bash sync_filmy.sh to-disk /share/NAS-FILMY /share/external/USBDisk1
   ```

4. Disk přenést a připojit k NAS2, **skript z disku** spustit tam:

   ```bash
   bash sync_filmy.sh to-nas /share/external/USBDisk1 /share/Filmy
   ```

   Před mazáním přebývajících souborů se skript zeptá (výchozí odpověď je *ne*).
5. Po `to-nas` (klidně až po několika discích) **Aktualizovat** — záložka *Na disku* se vyprázdní a plán odpovídá NAS2.
6. Před dalším kolem **Nastavení → Disk pro přenos → Vyčistit disk**: smaže celý obsah disku. Volba
   Výchozí volba *Jen smazat*; *Smazat a aktualizovat* navíc přeskenuje páry, které měly něco k přenosu (Kopírovat, Odloženo nebo Na disku).

Během kopírování skript před každým souborem vypíše celkový stav, pod ním rsync ukazuje průběh souboru:

```
[7/753 · 1,6 % · 8,2 GB z 512,0 GB · 13,9 MB/s · zbývá ~ 10 h 04 min (kolem 06:12)] Daredevil (2015)/Season 03 (2018)/
S03E07. Nasledky.mkv
      497483776  48%   12,32MB/s   00:00:41
```

Po přerušení (Ctrl+C, odpojení) stačí skript spustit znovu — soubory, které už na cíli celé jsou, přeskočí.
Soubor, který se nepovede zkopírovat, kopírování nezastaví (pět chyb za sebou ano); skript je nakonec vypíše
a přebývající soubory v tom případě nemaže.

Volby skriptu: `--dry-run` (jen ukáže, co by se stalo), `--yes` (na dotazy odpoví „ano“). Skript potřebuje `bash`, `rsync` a `base64`; ověřeno na Linuxu (NAS) i na macOS (bash 3.2, openrsync).

- Pro `to-nas` lze místo kořene disku zadat i přímo složku páru na disku (`<kořen disku>/<pár>`).
- Když se u páru jen maže (není co kopírovat), `to-nas` disk nepotřebuje — pusťte ho přímo na NAS2.
- Mazání spouštějte ideálně **přímo na NAS2** (přes SSH). Přes síťové připojení z Macu se názvy s diakritikou
  nemusí najít (jiný zápis NFC/NFD); skript nenalezené soubory vždy vypíše a skončí nenulovým kódem.

### Přímý přenos (NAS → NAS)

Pro menší objemy — drobné soubory, konflikty, mazání přebývajících — bez disku, přímo přes síť (SFTP):

1. V **detailu páru** označ soubory (záložky Kopírovat, Konflikty, Odloženo, Přebývá) a zvol **Přidat k přímému přenosu**
   (nebo *Hromadně → Vše k přímému přenosu*). Soubory se přesunou do záložky **Přímý přenos** a z plánu na disk vypadnou.
2. Tlačítko **Přímý přenos (N)** v hlavičce detailu přenos po potvrzení spustí na pozadí: soubory z Kopírovat/Konflikty/
   Odloženo se nahrají na NAS2, soubory z Přebývá se na NAS2 smažou.
3. Panel ukazuje celkový průběh, rychlost, uplynulý a odhadovaný čas a průběh aktuálního souboru; přenos jde zrušit.
   V potvrzovacím okně je při nastaveném okně i volba **Naplánovat** (viz Plánování).
4. Po skončení karta **Poslední přímý přenos** ukáže výsledek každého souboru (nahráno, smazáno, už na cíli, chyba s důvodem).
   Stav (*Hotovo ×*) kartu odebere; po dalším skenu NAS2 zmizí sama.

Soubor se nahrává pod dočasným názvem `.jméno.syncpart` a přejmenuje se až celý — na NAS2 nikdy nezůstane napůl
nahraný soubor a přerušený přenos příště **naváže**. Zachová se čas změny. Chyba jednoho souboru přenos nezastaví
(soubor zůstane označený pro další pokus). Výsledek se hned promítne do čísel páru bez nového skenu.
Přenos běží z lokálně připojeného zdroje (NAS1); během přenosu se pár neskenuje.

### Plánování

Obojí se nastavuje v **Nastavení → Plánování**, platí každý den a čas je podle kontejneru (`TZ` v compose).
Plánovač běží v aplikaci, kontroluje každých 30 s a plán přežije restart kontejneru.

#### Automatická aktualizace

Jeden čas (např. `21:30`), kdy se každý den samo spustí *Aktualizovat vše* — ideálně chvíli před oknem pro
naplánovaný přenos. Zmeškaný termín (restart kontejneru) se dožene nejpozději do hodiny; pár, u kterého zrovna
běží přenos, se přeskočí. Na Přehledu je čas vidět pod tlačítkem *Aktualizovat vše*.

#### Naplánovaný přímý přenos

Když je zadané okno pro naplánovaný přenos (např. `22:00`–`06:00`; konec dřív než začátek = přes půlnoc),
má potvrzovací okno přímého přenosu i tlačítko **Naplánovat**.
Naplánovaný pár se spustí sám, jakmile je okno otevřené (víc párů postupně, v pořadí párů). Po konci okna
se rozpracovaný soubor dokončí, další už nezačne a přenos skončí jako *Pozastaveno*; zbytek pokračuje
v dalším okně. Když je přeneseno všechno (nebo přenos zrušíš), plán se sám zruší; zrušit ho jde i tlačítkem
*Zrušit plán* v detailu páru. Ruční *Spustit přenos* okno nerespektuje a běží do konce. Po selhání (třeba
nedostupný NAS2) plánovač v okně zkusí přenos znovu za 15 minut.

## 🚀 Deployment

### Předpoklady

- Docker a Docker Compose na NAS1
- složky NAS1 dostupné na hostiteli (připojí se do kontejneru jen pro čtení)
- volitelně přenosový disk (exFAT) připojený k NAS1 — do kontejneru **pro zápis** (Přenos na disk, Vyčistit disk)
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
      - /volumeUSB1/usbshare:/mnt/disk      # volitelně: přenosový disk (Přenos na disk, volné místo) — bez :ro
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
- **Přenos na disk** a **Vyčistit disk** potřebují disk připojený **pro zápis** (bez `:ro`). Aplikace předem ověří,
  že disk je připojený a zapisovatelný, že to není prázdná složka na systémovém oddílu (méně než 20 GB), že neleží
  na stejném svazku jako NAS1 (ochrana před špatně nastavenou cestou) a u přenosu i že je na disku dost místa.
- `TZ` v compose určuje čas plánování (automatická aktualizace, okno přenosu).

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
| `DISK_PATH` | `/mnt/disk` | přenosový disk v kontejneru (volitelné) — *Přenos na disk* v detailu páru a *Načíst volné místo* v Nastavení |
| `DISK_CHECK_DEVICE` | `1` | `0` vypne kontrolu, že disk není na stejném svazku jako NAS1 (jen pro vývoj na Docker Desktopu) |
| `SCHEDULER` | `1` | `0` vypne plánovač (automatická aktualizace a naplánovaný přenos) — používají testy |
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

- **Skeny** běží ve vláknech, soubory sbírají do paměti a do databáze je zapíšou **jednou krátkou transakcí** (`BEGIN IMMEDIATE`). Neúspěšný nebo zrušený sken nechá platný předchozí; po restartu aplikace se nedokončené skeny označí jako selhané. Nejvýš jeden sken na jednoho hosta najednou.
- **Přenosy** (přímý NAS → NAS a na disk, `app/transfer/`) běží na pozadí se společným průběhem; soubor se zapisuje jako `.jméno.syncpart` a přejmenuje se až celý, přerušený přenos naváže. U jednoho páru nikdy neběží sken a přenos zároveň, na disk kopíruje vždy jen jeden pár.
- **Plánovač** (vlákno, kontrola každých 30 s) spouští automatickou aktualizaci a naplánované přímé přenosy v časovém okně.
- **Sken nikdy nepřeskakuje potichu.** Nečitelná složka, neexistující nebo prázdný zdroj = chyba skenu (jinak by vznikly falešné „přebývající“ soubory a skript by je smazal).
- **Porovnání a plán se nepersistují** — počítají se za běhu čistými funkcemi z posledních skenů (`app/core/plan.py`).
- UI je serverem renderované HTML (Jinja2) s HTMX; průběh skenů a přenosů se obnovuje pollingem, jen když něco běží.
- Nové sloupce v databázi se doplní samy při startu (`ADDED_COLUMNS` v `app/db.py`), stávající data zůstanou.

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
├── transfer/        # přenosy (runner, cíle SFTP/lokální), přenosový disk, časové okno, plánovač
├── apps/
│   ├── overview/    # Přehled
│   ├── pairs/       # detail páru, stav párů, skript, CSV, log skenu
│   └── settings/    # páry, SSH hosté, disk (kapacita, vyčištění), plánování, vzory
├── templates/
└── static/          # css/app.css, js/app.js, js/htmx.min.js, version.json
tests/               # pytest (plán, skenery, runner, skript, přenosy, disk, plánování, stránky)
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
- ✅ **Skript pro exFAT**: jeden soubor pro `to-disk` i `to-nas`, bezpečné seznamy cest, `rsync` po souborech s celkovým průběhem, kontroly složek, místa a plánu
- ✅ **UI na Jinja2 + HTMX** (bez Reactu a Node buildu), světlý i tmavý režim, mobil
- ✅ **SSH heslo se nevrací do prohlížeče**
- ✅ **Automatická aktualizace** všech párů jednou denně v zadaný čas
- ✅ **Naplánovaný přímý přenos** v časovém okně (i přes půlnoc), po konci okna se pozastaví a pokračuje další den
- ✅ **Vyčištění disku** před dalším kolem (celý obsah, volitelně s aktualizací párů)
- ✅ **Záložka Na disku** — disky jde střídat a plnit po várkách bez duplicit, srovná Aktualizovat
- ✅ **Přenos na disk z aplikace** místo kroku `to-disk` — průběh, zrušení, navázání, skript a `.sync-plan` na disku
- ✅ **Přímý přenos NAS → NAS** přes SFTP pro menší objemy a mazání přebývajících (průběh, rychlost, odhad času, navázání)
- ✅ **Výsledky přenosů po souborech**, řazení seznamů podle cesty a velikosti, stránkování po 50
- ❌ Odstraněno: kopírování z backendu, SAFE MODE, DB na USB, WebSocket, fáze, stránka Debug

Starší historie viz git (`git log`).
