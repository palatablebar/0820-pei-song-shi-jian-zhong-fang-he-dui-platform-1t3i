from collections import defaultdict

from app.business import DomainIssue, by_kind, prepared, single


def source_ref(row, reason, against=None):
    """Source-level handle for one event, used by scope and pending readback."""
    item = {
        "case": row["case"],
        "record": row["record"],
        "line": row.get("line"),
        "partition": row["partition"],
        "entity": row["entity"],
        "seq": row["seq"],
        "kind": row["kind"],
        "quantity": row["quantity"],
        "reason": reason,
    }
    if against is not None:
        item["against"] = against
    return item


def plan(rows):
    """Classify every event without raising, so the workbench can read back
    what is signed, deferred and pending even when a group is blocked."""
    ceilings = {}
    watermark_conflict = []
    for row in by_kind(rows, "watermark"):
        p = row["partition"]
        if p in ceilings:
            watermark_conflict.append(source_ref(row, "WATERMARK_CONFLICT"))
        else:
            ceilings[p] = row["seq"]
    batch = {}
    first_record = {}
    signed = []
    deferred = []
    conflicts = []
    missing = []
    for row in rows:
        if row["kind"] not in ("upsert", "delete"):
            continue
        p, key, seq = row["partition"], row["entity"], row["seq"]
        if p not in ceilings:
            missing.append(source_ref(row, "WATERMARK_MISSING"))
            continue
        if seq > ceilings[p]:
            # Beyond the partition watermark: carried to the next batch and
            # excluded from this sign-off.
            deferred.append(source_ref(row, "DEFERRED"))
            continue
        ident = (p, key, seq)
        value = (row["kind"], row["quantity"])
        if ident in batch and batch[ident] != value:
            # Same key and sequence with a different event: isolate only this
            # record, block the group, let other complete groups keep checking.
            conflicts.append(
                source_ref(row, "SOURCE_CONFLICT", first_record.get(ident))
            )
            continue
        if ident not in batch:
            signed.append(source_ref(row, "SIGNED"))
            first_record[ident] = row["record"]
        batch[ident] = value
    return dict(
        ceilings=ceilings,
        batch=batch,
        signed=signed,
        deferred=deferred,
        conflicts=conflicts,
        missing=missing,
        watermark_conflict=watermark_conflict,
    )


def prepare(rows, verdict=None):
    verdict = verdict or plan(rows)
    for code, found in (
        ("WATERMARK_CONFLICT", verdict["watermark_conflict"]),
        ("WATERMARK_MISSING", verdict["missing"]),
        ("SOURCE_CONFLICT", verdict["conflicts"]),
    ):
        if found:
            raise DomainIssue(code, found)
    ceilings = verdict["ceilings"]
    batch = verdict["batch"]
    seqs = defaultdict(set)
    signed = defaultdict(int)
    for p, _, seq in batch:
        seqs[p].add(seq)
        signed[p] += 1
    return prepared(
        len(batch),
        {
            "deferred_events": len(verdict["deferred"]),
            "partitions": len(ceilings),
            "ceilings": {str(p): c for p, c in sorted(ceilings.items())},
            "seqs": {str(p): sorted(seqs[p]) for p in sorted(ceilings)},
            "signed": {str(p): signed[p] for p in sorted(ceilings)},
            "deferred": verdict["deferred"],
        },
        (batch, single(rows, "expected")["quantity"]),
    )
