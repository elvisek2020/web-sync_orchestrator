# Prompty pro generování aktualizovaných obrázků workflow

## Fáze 1 - Plánování (Planning Phase)

**Prompt pro obrázek fáze 1:**

```
Create a technical diagram showing a data synchronization planning workflow. The diagram should show:

1. Two network storage systems (NAS1 and NAS2) connected to a central computer/server
2. The computer/server running a web application interface labeled "Sync Orchestrator"
3. Workflow steps numbered 1-6:
   - Step 1: "Vytvořit Dataset NAS1" - scanning NAS1 to create file inventory
   - Step 2: "Vytvořit Dataset NAS2" - scanning NAS2 to create file inventory  
   - Step 3: "Spustit Scan NAS1" - creating inventory of files on NAS1
   - Step 4: "Spustit Scan NAS2" - creating inventory of files on NAS2
   - Step 5: "Vytvořit Porovnání" - comparing NAS1 (source) vs NAS2 (target) to identify differences
   - Step 6: "Vytvořit Plán" - creating transfer plan based on comparison results

4. Arrows showing data flow:
   - NAS1 → Computer (scan)
   - NAS2 → Computer (scan)
   - Computer processing comparison and plan

5. Visual elements:
   - NAS1 on the left (blue/green)
   - NAS2 on the right (blue/green)
   - Computer in the middle (processing, yellow/orange)
   - Database icon showing plan storage
   - "Plán přenosu" label for the final output

6. Visual style: Clean, modern technical diagram with blue/green color scheme
7. Text labels in Czech language
8. Icons for NAS devices, computer, database, and workflow steps
9. Background: Light gray or white
10. Size: 1200x800 pixels, suitable for web display

The diagram should clearly show that this phase requires BOTH NAS1 and NAS2 to be accessible (can be via SSH or local mount), and USB HDD must be available for database storage.
```

**Název souboru:** `faze1-planovani.png` nebo `faze1-planovani.svg`

---

## Fáze 2 - Kopírování NAS → HDD (Copy Phase: NAS to HDD)

**Prompt pro obrázek fáze 2:**

```
Create a technical diagram showing data copying from NAS to external HDD. The diagram should show:

1. NAS1 (source) connected to a computer/server
2. External USB HDD connected to the same computer
3. The computer/server running "Sync Orchestrator" application
4. Workflow showing:
   - "Plán přenosu" from Phase 1 is loaded (stored in database on USB HDD)
   - Data copying from NAS1 → USB HDD
   - Progress indicator showing copy operation with "Kopírováno: X / Y souborů"
   - USB HDD filling up with data in directory structure: /job-{job_id}/...
   - Real-time file status display (Zkopírováno, Chyba, Čeká)

5. Visual elements:
   - Large title at the top: "Fáze 2: Kopírování NAS → HDD"
   - NAS1 on the left (source, blue/green)
   - Computer in the middle (processing, yellow/orange)
   - USB HDD on the right (target, gray/silver, with database icon)
   - Large arrow from NAS1 to USB HDD showing data flow
   - "Plán přenosu" label showing it uses the plan created in Phase 1
   - Progress bar and file counter
   - Job directory structure visible on HDD

6. Visual style: Clean, modern technical diagram with blue/orange color scheme
7. Text labels in Czech language
8. Icons for NAS, computer, USB HDD, and progress indicators
9. Background: Light gray or white
10. Size: 1200x800 pixels, suitable for web display

The diagram should clearly show that this phase requires NAS1 and USB HDD to be accessible, and creates a job-specific directory on the HDD.
```

**Název souboru:** `faze2-nas-to-hdd.png` nebo `faze2-nas-to-hdd.svg`

---

## Fáze 3 - Kopírování HDD → NAS (Copy Phase: HDD to NAS)

**Prompt pro obrázek fáze 3:**

```
Create a technical diagram showing data copying from external HDD to NAS. The diagram should show:

1. External USB HDD connected to a computer/server (on a different system than Phase 2)
2. NAS2 (target) connected to the same computer (can be via SSH or local mount)
3. The computer/server running "Sync Orchestrator" application
4. Workflow showing:
   - Same "Plán přenosu" from Phase 1 is loaded (from database on USB HDD)
   - Data copying from USB HDD → NAS2
   - Progress indicator showing copy operation with "Kopírováno: X / Y souborů"
   - NAS2 receiving data
   - Real-time file status display (Zkopírováno, Chyba, Čeká)
   - Job directory structure on HDD: /job-{job_id}/...

5. Visual elements:
   - Large title at the top: "Fáze 3: Kopírování HDD → NAS"
   - USB HDD on the left (source, gray/silver, with database icon and data already on it)
   - Computer in the middle (processing, yellow/orange)
   - NAS2 on the right (target, blue/green, can show SSH connection icon)
   - Large arrow from USB HDD to NAS2 showing data flow
   - "Plán přenosu" label showing it uses the same plan from Phase 1
   - Note: "Cílový systém" or "Target system" label
   - Progress bar and file counter
   - SSH connection indicator if applicable

6. Visual style: Clean, modern technical diagram with blue/orange color scheme
7. Text labels in Czech language
8. Icons for USB HDD, computer, NAS, SSH connection, and progress indicators
9. Background: Light gray or white
10. Size: 1200x800 pixels, suitable for web display

The diagram should clearly show that this phase requires USB HDD and NAS2 to be accessible (NAS2 can be via SSH), and this happens on a different computer/system than Phase 2.
```

**Název souboru:** `faze3-hdd-to-nas.png` nebo `faze3-hdd-to-nas.svg`

---

## Celkový workflow (Complete Workflow Overview)

**Prompt pro přehledný obrázek celého workflow:**

```
Create a comprehensive technical diagram showing the complete 3-phase data synchronization workflow:

Main title at the top: "Sync Orchestrator - Kompletní workflow"

Phase 1 (Planning) - Top section:
- NAS1 and NAS2 both connected to Computer 1
- Steps: Dataset NAS1 → Dataset NAS2 → Scan NAS1 → Scan NAS2 → Porovnání → Plán přenosu
- Database on USB HDD storing the plan
- Section title: "Fáze 1: Plánování (na zdrojovém systému)"
- Color: Blue/Green

Phase 2 (Copy NAS to HDD) - Middle left:
- NAS1 and USB HDD connected to Computer 1
- Arrow: NAS1 → USB HDD
- Progress indicator: "Kopírováno: X / Y souborů"
- Job directory: /job-{job_id}/...
- Section title: "Fáze 2: Kopírování NAS → HDD (na zdrojovém systému)"
- Color: Orange/Yellow

Physical Transfer - Middle:
- USB HDD being physically moved (dashed arrow or icon showing physical movement)
- Label: "Fyzický přenos HDD"
- Color: Gray

Phase 3 (Copy HDD to NAS) - Middle right:
- USB HDD and NAS2 connected to Computer 2 (different system)
- NAS2 can show SSH connection icon
- Arrow: USB HDD → NAS2
- Progress indicator: "Kopírováno: X / Y souborů"
- Section title: "Fáze 3: Kopírování HDD → NAS (na cílovém systému)"
- Color: Orange/Yellow

Visual flow:
- Phase 1 → Phase 2 (same system, Computer 1)
- Phase 2 → Physical transfer of HDD
- Physical transfer → Phase 3 (different system, Computer 2)

6. Visual style: Clean, modern technical diagram
7. Color coding:
   - Phase 1: Blue/Green
   - Phase 2: Orange/Yellow
   - Phase 3: Orange/Yellow
   - Physical transfer: Gray
   - Different systems clearly distinguished (Computer 1 vs Computer 2)
8. Text labels in Czech language
9. Icons for NAS devices, computers, USB HDD, database, SSH, progress indicators
10. Background: Light gray or white
11. Size: 1600x1000 pixels, suitable for web display

The diagram should clearly show the complete workflow from planning to final copy, including the physical transfer of the HDD between systems, and emphasize that the plan is stored on the USB HDD database.
```

**Název souboru:** `workflow-complete.png` nebo `workflow-complete.svg`

---

## Klíčové změny oproti starým obrázkům

### Terminologie:
- ✅ "Fáze 2" místo "Fáze 2a"
- ✅ "Fáze 3" místo "Fáze 2b"
- ✅ "Plán přenosu" / "Plán" místo "Batch"
- ✅ "Porovnání" místo "Diff"
- ✅ "Dataset" místo jen "NAS1/NAS2"

### Nové funkce k zobrazení:
- ✅ Databáze na USB HDD (ukládá plán)
- ✅ Job-specifické adresáře na HDD: `/job-{job_id}/...`
- ✅ Progress indikátor: "Kopírováno: X / Y souborů"
- ✅ Real-time file status (Zkopírováno, Chyba, Čeká)
- ✅ SSH připojení pro NAS2 ve fázi 3
- ✅ Scan jako samostatný krok (ne jen dataset)

### Workflow:
- ✅ Fáze 1: Dataset NAS1 → Dataset NAS2 → Scan NAS1 → Scan NAS2 → Porovnání → Plán přenosu
- ✅ Fáze 2: Plán přenosu → Kopírování NAS1 → USB HDD (s job adresářem)
- ✅ Fáze 3: Plán přenosu (z HDD) → Kopírování USB HDD → NAS2 (může být přes SSH)

---

## Poznámky

- Všechny obrázky by měly být v konzistentním stylu
- Použijte stejnou barevnou paletu napříč všemi obrázky
- Icons by měly být jednoduché a srozumitelné
- Text by měl být čitelný i při zmenšení
- Formát: PNG (pro web) nebo SVG (pro škálovatelnost)
- Velikost: Minimálně 1200x800px, ideálně větší pro lepší kvalitu
- Důraz na databázi na USB HDD jako klíčový prvek pro přenositelnost plánu mezi systémy

