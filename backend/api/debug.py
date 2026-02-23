"""
Debug / diagnostics API – helps identify path normalization issues
between datasets, scans, diffs and batches.
"""
from fastapi import APIRouter
from backend.storage_service import storage_service
from backend.database import Dataset, Scan, FileEntry, Diff, DiffItem, Batch, BatchItem
from backend.utils import normalize_path, normalize_root_rel_path, is_ignored_path
from sqlalchemy import func

router = APIRouter()


@router.get("/diagnostics")
async def get_diagnostics():
    session = storage_service.get_session()
    if not session:
        return {"error": "Database not available"}

    try:
        result = {
            "datasets": [],
            "scans": [],
            "diffs": [],
            "batches": [],
        }

        # --- Datasets ---
        for ds in session.query(Dataset).order_by(Dataset.id).all():
            result["datasets"].append({
                "id": ds.id,
                "name": ds.name,
                "location": ds.location,
                "roots": ds.roots,
                "scan_adapter_type": ds.scan_adapter_type,
                "base_path": (ds.scan_adapter_config or {}).get("base_path", "N/A"),
            })

        # --- Scans with sample files & normalization ---
        for scan in session.query(Scan).order_by(Scan.id).all():
            ds = session.query(Dataset).get(scan.dataset_id)
            ds_roots = ds.roots if ds else []

            samples_raw = (
                session.query(FileEntry)
                .filter(FileEntry.scan_id == scan.id)
                .limit(8)
                .all()
            )

            root_rel_values = (
                session.query(FileEntry.root_rel_path, func.count(FileEntry.id))
                .filter(FileEntry.scan_id == scan.id)
                .group_by(FileEntry.root_rel_path)
                .all()
            )

            samples = []
            for f in samples_raw:
                file_root = normalize_root_rel_path(f.root_rel_path) if f.root_rel_path else ""
                if not file_root and ds_roots:
                    file_root = normalize_root_rel_path(ds_roots[0])
                normalized = normalize_path(f.full_rel_path, file_root)
                ignored = is_ignored_path(f.full_rel_path)
                samples.append({
                    "full_rel_path": f.full_rel_path,
                    "root_rel_path": f.root_rel_path,
                    "effective_root": file_root,
                    "normalized": normalized,
                    "ignored": ignored,
                    "size": f.size,
                })

            scan_log = scan.error_message or ""
            log_errors = [l for l in scan_log.split("\n") if l.startswith("ERROR:") or l.startswith("WARNING:") or l.startswith("FATAL:")]
            log_summary_lines = [l for l in scan_log.split("\n") if l.startswith("Scan summary:")]

            result["scans"].append({
                "id": scan.id,
                "dataset_id": scan.dataset_id,
                "dataset_name": ds.name if ds else "?",
                "dataset_location": ds.location if ds else "?",
                "dataset_roots": ds_roots,
                "status": scan.status,
                "total_files": scan.total_files,
                "total_size_gb": round((scan.total_size or 0) / (1024**3), 2),
                "root_rel_path_distribution": [
                    {"root_rel_path": r or "(empty)", "count": c}
                    for r, c in root_rel_values
                ],
                "sample_files": samples,
                "scan_log_summary": log_summary_lines[-1] if log_summary_lines else None,
                "scan_log_errors": log_errors[:50],
                "scan_log_full": scan_log if len(scan_log) < 50000 else scan_log[:50000] + "\n... (truncated)",
            })

        # --- Diffs with normalization comparison ---
        for diff in session.query(Diff).order_by(Diff.id).all():
            category_counts = dict(
                session.query(DiffItem.category, func.count(DiffItem.id))
                .filter(DiffItem.diff_id == diff.id)
                .group_by(DiffItem.category)
                .all()
            )

            src_scan = session.query(Scan).get(diff.source_scan_id)
            tgt_scan = session.query(Scan).get(diff.target_scan_id)
            src_ds = session.query(Dataset).get(src_scan.dataset_id) if src_scan else None
            tgt_ds = session.query(Dataset).get(tgt_scan.dataset_id) if tgt_scan else None

            # Sample normalized paths from source and target to show side-by-side
            src_samples = []
            if src_scan:
                for f in session.query(FileEntry).filter(FileEntry.scan_id == src_scan.id).filter(~FileEntry.full_rel_path.contains(".streams")).limit(5).all():
                    file_root = normalize_root_rel_path(f.root_rel_path) if f.root_rel_path else ""
                    if not file_root and src_ds and src_ds.roots:
                        file_root = normalize_root_rel_path(src_ds.roots[0])
                    src_samples.append({
                        "original": f.full_rel_path,
                        "root": file_root,
                        "normalized": normalize_path(f.full_rel_path, file_root),
                    })

            tgt_samples = []
            if tgt_scan:
                for f in session.query(FileEntry).filter(FileEntry.scan_id == tgt_scan.id).filter(~FileEntry.full_rel_path.contains(".streams")).limit(5).all():
                    file_root = normalize_root_rel_path(f.root_rel_path) if f.root_rel_path else ""
                    if not file_root and tgt_ds and tgt_ds.roots:
                        file_root = normalize_root_rel_path(tgt_ds.roots[0])
                    tgt_samples.append({
                        "original": f.full_rel_path,
                        "root": file_root,
                        "normalized": normalize_path(f.full_rel_path, file_root),
                    })

            # Sample diff items by category
            diff_samples = {}
            for cat in ("missing", "extra", "conflict", "same"):
                items = (
                    session.query(DiffItem)
                    .filter(DiffItem.diff_id == diff.id, DiffItem.category == cat)
                    .limit(5)
                    .all()
                )
                if items:
                    diff_samples[cat] = [
                        {
                            "path": i.full_rel_path,
                            "source_size": i.source_size,
                            "target_size": i.target_size,
                        }
                        for i in items
                    ]

            result["diffs"].append({
                "id": diff.id,
                "source_scan_id": diff.source_scan_id,
                "target_scan_id": diff.target_scan_id,
                "source_dataset": src_ds.name if src_ds else "?",
                "target_dataset": tgt_ds.name if tgt_ds else "?",
                "status": diff.status,
                "error": diff.error_message,
                "category_counts": category_counts,
                "source_normalization_samples": src_samples,
                "target_normalization_samples": tgt_samples,
                "diff_item_samples": diff_samples,
            })

        # --- Batches ---
        for batch in session.query(Batch).order_by(Batch.id).all():
            item_counts = dict(
                session.query(BatchItem.category, func.count(BatchItem.id))
                .filter(BatchItem.batch_id == batch.id)
                .group_by(BatchItem.category)
                .all()
            )
            total_size = session.query(func.sum(BatchItem.size)).filter(BatchItem.batch_id == batch.id, BatchItem.enabled == True).scalar() or 0
            sample_items = (
                session.query(BatchItem)
                .filter(BatchItem.batch_id == batch.id)
                .limit(5)
                .all()
            )

            result["batches"].append({
                "id": batch.id,
                "diff_id": batch.diff_id,
                "status": batch.status,
                "category_counts": item_counts,
                "total_items": sum(item_counts.values()),
                "total_size_gb": round(total_size / (1024**3), 2),
                "sample_items": [
                    {"path": i.full_rel_path, "size": i.size, "category": i.category, "enabled": i.enabled}
                    for i in sample_items
                ],
            })

        return result

    finally:
        session.close()


@router.get("/normalization-test")
async def test_normalization(path: str = "", root: str = ""):
    """Interactive normalization tester – pass ?path=...&root=... to see the result."""
    normalized = normalize_path(path, root)
    ignored = is_ignored_path(path)
    return {
        "input_path": path,
        "input_root": root,
        "normalized": normalized,
        "ignored": ignored,
    }
