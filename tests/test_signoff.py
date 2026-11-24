import io

import pytest

from app.review.service import describe, execute, review
from conftest import csv_data

HEADER_ROW = ["record", "case", "kind", "partition", "entity", "seq", "quantity", "note"]


def row(record, kind, partition, entity, seq, quantity=0, case="0001", note="校核"):
    return [record, case, kind, partition, entity, seq, quantity, note]


def watermark(partition, seq, case="0001", record=None):
    return row(record or f"W{partition}", "watermark", partition, 0, seq, 0, case)


def find(report, code):
    return next(c for c in report["cases"] if c["case"] == code)


def test_deferred_event_is_carried_not_signed(clean):
    from app.modules.pipeline import run

    report = run(clean)
    signed = [
        item
        for item in report["scope"]["items"]
        if item["record"] == "000106"
    ]
    pending = [item for item in report["pending"]["items"] if item["record"] == "000106"]
    assert signed == []
    assert pending and pending[0]["reason"] == "DEFERRED"
    assert pending[0]["blocking"] is False
    assert report["handover"]["carried"] == 1
    assert report["handover"]["signable"] is True
    assert report["handover"]["decision"] == "SIGN_NOW_CARRY"


def test_signed_scope_reads_back_counts_and_cutoff(clean):
    from app.modules.pipeline import run

    scope = run(clean)["scope"]
    assert scope["cutoff"] == {"1": 4, "2": 1}
    assert scope["cases"]["0001"]["signed"] == 4
    assert scope["cases"]["0001"]["deferred"] == 1
    assert scope["counts"] == {"signed": 5, "deferred": 1, "conflicts": 0, "blocked": 0}
    assert {item["record"] for item in scope["items"]} == {
        "000102",
        "000103",
        "000104",
        "000105",
        "000202",
    }


def test_retry_same_source_adds_no_pending(store, clean):
    first = execute(store, clean)
    second = execute(store, clean)
    assert first["id"] == second["id"]
    assert len(store.list()) == 1
    assert first["report"]["pending"] == second["report"]["pending"]
    assert first["report"]["pending"]["carried"] == 1


def test_retry_through_http_does_not_accumulate(client):
    a = client.post("/api/runs", data={"sample": "clean"}).json
    b = client.post("/api/runs", data={"sample": "clean"}).json
    assert a["id"] == b["id"]
    assert a["report"]["pending"] == b["report"]["pending"]
    assert len(client.get("/api/runs").json["items"]) == 1


def test_same_key_seq_conflict_isolates_only_that_record(dirty):
    from app.modules.pipeline import run

    report = run(dirty)
    conflict = find(report, "0003")
    assert conflict["status"] == "SOURCE_CONFLICT"
    assert conflict["scope"]["counts"]["conflicts"] == 1
    assert conflict["scope"]["conflicts"][0]["record"] == "000303"
    assert conflict["scope"]["conflicts"][0]["against"] == "000302"
    # Other complete groups keep checking.
    assert find(report, "0001")["status"] == "READY"
    assert find(report, "0002")["status"] == "READY"
    assert not report["balance"]["releasable"]
    assert report["handover"]["signable"] is False
    assert report["handover"]["decision"] == "BLOCKED"
    blocking = [
        item for item in report["pending"]["items"] if item["record"] == "000303"
    ]
    assert blocking and blocking[0]["blocking"] is True


def test_conflict_record_is_the_only_isolated_copy():
    from app.intake.service import inspect

    data = csv_data(
        [
            watermark(1, 4),
            row("A1", "upsert", 1, 1, 2, 9),
            row("A2", "upsert", 1, 1, 2, 8),
            row("E1", "expected", 0, 0, 0, 9),
        ]
    )
    # Intake keeps both rows: the conflict is at the domain layer, not duplicate
    # record keys.
    assert inspect(data)["accepted"] == 4

    from app.modules.pipeline import run

    scope = run(data)["scope"]
    # The conflicting group is blocked as a whole, but only the second copy is
    # reported as the conflict; the first copy is neither dropped nor counted.
    assert scope["counts"]["signed"] == 0
    assert scope["counts"]["conflicts"] == 1
    assert scope["cases"]["0001"]["blocked"] == 1
    assert scope["cases"]["0001"]["status"] == "SOURCE_CONFLICT"


def advance_watermark(base=None):
    """Source with partition 1 watermark raised from 4 to 5.

    The previously carried upsert (000106, entity 2, seq 5) enters the sign-off
    and the expected total moves from 70 to 71.
    """
    text = (
        (base or open("sample_data/ready.csv", "rb").read())
        .decode("utf-8-sig")
        .replace("000101,0001,watermark,1,0,4,0", "000101,0001,watermark,1,0,5,0")
        .replace("000107,0001,expected,0,0,0,70", "000107,0001,expected,0,0,0,71")
    )
    return text.encode()


def test_watermark_advance_matches_one_shot_replay(clean):
    from app.modules.pipeline import run

    before = run(clean)
    after = run(advance_watermark(clean))

    carried = [
        item for item in before["pending"]["items"] if item["record"] == "000106"
    ]
    assert carried and carried[0]["reason"] == "DEFERRED"

    # Before the watermark advances the late event is neither signed nor part of
    # the computed total.
    assert "000106" not in {item["record"] for item in before["scope"]["items"]}
    assert find(before, "0001")["measure"]["value"] == 70

    # After advancing, this batch is equivalent to a one-shot replay of the
    # whole stream: the union of what batch one signed and carried equals the
    # scope of the advanced run, and the calculated total matches.
    union = {item["record"] for item in before["scope"]["items"]} | {
        item["record"] for item in carried
    }
    assert union == {item["record"] for item in after["scope"]["items"]}
    assert after["scope"]["cases"]["0001"]["signed"] == 5
    assert find(after, "0001")["measure"]["value"] == 71
    assert find(after, "0001")["measure"]["evidence"]["live"] == {"1/2": 71}
    assert after["handover"]["carried"] == 0
    assert after["handover"]["complete"] is True
    assert after["handover"]["decision"] == "SIGN_NOW_COMPLETE"

    # And re-running the advanced source is byte-identical, so the second
    # handover starts from the same state the one-shot replay produced.
    assert run(advance_watermark(clean)) == after


def test_prior_signature_reads_back(store, clean):
    old = execute(store, clean)
    review(store, old["id"], dict(revision=0, status="HELD", note="等待迟到事件"))

    # A later source covering the same business groups.
    later_bytes = clean.replace(b"\xe4\xba\xa4\xe6\x8e\xa5\xe6\x98\x8e\xe7\xbb\x86", b"\xe4\xba\xa4\xe6\x8e\xa5\xe5\xa4\x8d\xe6\xa0\xb8")
    assert later_bytes != clean
    later = execute(store, later_bytes)
    assert later["id"] != old["id"]
    current = describe(store, later["id"])
    assert current["prior"]["groups"]["0001"]["note"] == "等待迟到事件"
    assert current["prior"]["groups"]["0001"]["status"] == "HELD"
    assert current["prior"]["runs"][0]["id"] == old["id"]


def test_prior_readback_survives_retry(store, clean):
    old = execute(store, clean)
    review(store, old["id"], dict(revision=0, status="HELD", note="等待迟到事件"))
    current = describe(store, old["id"])
    # The current run is never listed as its own prior.
    assert old["id"] not in {run["id"] for run in current["prior"]["runs"]}
    assert current["prior"]["groups"] == {}


def test_evidence_carries_scope_pending_and_prior(store, clean):
    import json

    from app.evidence.render import artifact

    old = execute(store, clean)
    review(store, old["id"], dict(revision=0, status="HELD", note="等待迟到事件"))
    packet = json.loads(artifact(describe(store, old["id"])))
    assert packet["scope"]["counts"]["signed"] == 5
    assert packet["pending"]["carried"] == 1
    assert packet["handover"]["decision"] == "SIGN_NOW_CARRY"
    # The exported packet is a snapshot of one run and stays deterministic, so
    # prior signatures are read back on the workbench rather than baked in.
    assert packet == json.loads(artifact(store.load(old["id"])))
