# Prompty pro generování obrázků workflow

## Fáze 1 - Plánování (Planning Phase)

**Prompt pro obrázek fáze 1:**

```
Create a technical diagram showing a data synchronization planning workflow. The diagram should show:

1. Two network storage systems (NAS1 and NAS2) connected to a central computer/server
2. The computer/server running a web application interface labeled "Sync Orchestrator"
3. Workflow steps numbered 1-4:
   - Step 1: "Create Dataset NAS1" - scanning NAS1 to create file inventory
   - Step 2: "Create Dataset NAS2" - scanning NAS2 to create file inventory  
   - Step 3: "Create Diff" - comparing NAS1 (source) vs NAS2 (target) to identify differences
   - Step 4: "Create Batch" - planning transfer batch based on diff results

4. Arrows showing data flow:
   - NAS1 → Computer (scan)
   - NAS2 → Computer (scan)
   - Computer processing diff and batch

5. Visual style: Clean, modern technical diagram with blue/green color scheme
6. Text labels in Czech language
7. Icons for NAS devices, computer, and workflow steps
8. Background: Light gray or white
9. Size: 1200x800 pixels, suitable for web display

The diagram should clearly show that this phase requires BOTH NAS1 and NAS2 to be accessible (can be via SSH or local mount).
```

**Název souboru:** `faze1-planovani.png` nebo `faze1-planovani.svg`

---

## Fáze 2a - Kopírování NAS to HDD (Copy Phase: NAS to HDD)

**Prompt pro obrázek fáze 2a:**

```
Create a technical diagram showing data copying from NAS to external HDD. The diagram should show:

1. NAS1 (source) connected to a computer/server
2. External USB HDD connected to the same computer
3. The computer/server running "Sync Orchestrator" application
4. Workflow showing:
   - Batch from Phase 1 is loaded
   - Data copying from NAS1 → USB HDD
   - Progress indicator showing copy operation
   - USB HDD filling up with data

5. Visual elements:
   - NAS1 on the left (source, blue/green)
   - Computer in the middle (processing, yellow/orange)
   - USB HDD on the right (target, gray/silver)
   - Large arrow from NAS1 to USB HDD showing data flow
   - "Batch" label showing it uses the batch created in Phase 1

6. Visual style: Clean, modern technical diagram with blue/orange color scheme
7. Text labels in Czech language
8. Icons for NAS, computer, and USB HDD
9. Background: Light gray or white
10. Size: 1200x800 pixels, suitable for web display

The diagram should clearly show that this phase requires NAS1 and USB HDD to be accessible.
```

**Název souboru:** `faze2a-nas-to-hdd.png` nebo `faze2a-nas-to-hdd.svg`

---

## Fáze 2b - Kopírování HDD to NAS (Copy Phase: HDD to NAS)

**Prompt pro obrázek fáze 2b:**

```
Create a technical diagram showing data copying from external HDD to NAS. The diagram should show:

1. External USB HDD connected to a computer/server (on a different system than Phase 2a)
2. NAS2 (target) connected to the same computer
3. The computer/server running "Sync Orchestrator" application
4. Workflow showing:
   - Same Batch from Phase 1 is loaded (transferred with the HDD)
   - Data copying from USB HDD → NAS2
   - Progress indicator showing copy operation
   - NAS2 receiving data

5. Visual elements:
   - USB HDD on the left (source, gray/silver, with data already on it)
   - Computer in the middle (processing, yellow/orange)
   - NAS2 on the right (target, blue/green)
   - Large arrow from USB HDD to NAS2 showing data flow
   - "Batch" label showing it uses the same batch from Phase 1
   - Note: "Different system" or "Target system" label

6. Visual style: Clean, modern technical diagram with blue/orange color scheme
7. Text labels in Czech language
8. Icons for USB HDD, computer, and NAS
9. Background: Light gray or white
10. Size: 1200x800 pixels, suitable for web display

The diagram should clearly show that this phase requires USB HDD and NAS2 to be accessible, and this happens on a different computer/system than Phase 2a.
```

**Název souboru:** `faze2b-hdd-to-nas.png` nebo `faze2b-hdd-to-nas.svg`

---

## Celkový workflow (Complete Workflow Overview)

**Prompt pro přehledný obrázek celého workflow:**

```
Create a comprehensive technical diagram showing the complete 3-phase data synchronization workflow:

Phase 1 (Planning) - Top section:
- NAS1 and NAS2 both connected to Computer 1
- Steps: Dataset NAS1 → Dataset NAS2 → Diff → Batch
- Label: "Fáze 1: Plánování (na zdrojovém systému)"

Phase 2a (Copy NAS to HDD) - Middle left:
- NAS1 and USB HDD connected to Computer 1
- Arrow: NAS1 → USB HDD
- Label: "Fáze 2a: Kopírování NAS → HDD (na zdrojovém systému)"

Phase 2b (Copy HDD to NAS) - Middle right:
- USB HDD and NAS2 connected to Computer 2 (different system)
- Arrow: USB HDD → NAS2
- Label: "Fáze 2b: Kopírování HDD → NAS (na cílovém systému)"

Visual flow:
- Phase 1 → Phase 2a (same system)
- Phase 2a → Physical transfer of HDD
- Physical transfer → Phase 2b (different system)

6. Visual style: Clean, modern technical diagram
7. Color coding:
   - Phase 1: Blue/Green
   - Phase 2a: Orange/Yellow
   - Phase 2b: Orange/Yellow
   - Different systems clearly distinguished
8. Text labels in Czech language
9. Icons for NAS devices, computers, USB HDD
10. Background: Light gray or white
11. Size: 1600x1000 pixels, suitable for web display

The diagram should clearly show the complete workflow from planning to final copy, including the physical transfer of the HDD between systems.
```

**Název souboru:** `workflow-complete.png` nebo `workflow-complete.svg`

---

## Poznámky

- Všechny obrázky by měly být v konzistentním stylu
- Použijte stejnou barevnou paletu napříč všemi obrázky
- Icons by měly být jednoduché a srozumitelné
- Text by měl být čitelný i při zmenšení
- Formát: PNG (pro web) nebo SVG (pro škálovatelnost)
- Velikost: Minimálně 1200x800px, ideálně větší pro lepší kvalitu

