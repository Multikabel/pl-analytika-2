"""Separate revision-2 ledger; the original prediction archive remains authoritative v1.

A revision is published as one complete CSV. Missing/corrupt/conflicting ledgers
fail closed. This deliberately does not support automatic revision 3.
"""
from pathlib import Path
import os
import tempfile
import pandas as pd
import numpy as np
import github_persistence as github

NAME = "model_prediction_revisions.csv"
META = ["revision", "revision_reason", "supersedes", "original_created_at",
        "model_sha256", "training_data_sha256", "trained_at", "trained_rows",
        "first_kickoff_utc", "verified_at", "original_archive_sha256"]
SETTLEMENT = ["status", "actual_value", "result", "error", "abs_error",
              "bias_direction", "range_result", "settled_at", "match_date"]


def path_for(archive):
    return Path(archive).with_name(NAME)


def read(archive):
    path = path_for(archive)
    if github.enabled():
        remote, _ = github.read_csv("data/predictions/" + NAME)
        if remote is None:
            raise RuntimeError("Revision ledger unavailable")
        if path.exists() and not pd.read_csv(path).empty and remote.empty:
            raise RuntimeError("Local revision missing remotely; refusing revision rollback")
        return remote
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def validate(base, revisions):
    from model_prediction_stats import COLUMNS, _id, _semantic_key
    if revisions.empty:
        return
    if not set(COLUMNS + META).issubset(revisions.columns):
        raise ValueError("Incomplete revision schema")
    if revisions[["season", "match_round", "model_prediction_id", "supersedes"]].isna().any().any():
        raise ValueError("Missing revision identity")
    if not revisions.status.isin(["pending", "settled"]).all():
        raise ValueError("Invalid revision status")
    if revisions.model_prediction_id.duplicated().any():
        raise ValueError("Duplicate revision identity")
    for (_, _), group in revisions.groupby(["season", "match_round"]):
        if len(group) != 90 or not pd.to_numeric(group.revision).eq(2).all():
            raise ValueError("Revision must contain exactly 90 revision-2 records")
        originals = base[base.model_prediction_id.isin(group.supersedes)]
        if len(originals) != 90 or originals.model_prediction_id.duplicated().any():
            raise ValueError("Revision has missing/ambiguous originals")
        lookup = originals.set_index("model_prediction_id")
        created = pd.to_datetime(group.created_at, utc=True, errors="raise")
        kickoff = pd.to_datetime(group.first_kickoff_utc, utc=True, errors="raise")
        verified = pd.to_datetime(group.verified_at, utc=True, errors="raise")
        if (created.nunique() != 1 or kickoff.nunique() != 1 or
                not (created < kickoff).all() or not (verified < kickoff).all() or
                not (verified <= created).all()):
            raise ValueError("Revision is not a verified pre-match snapshot")
        for col in ["model_sha256", "training_data_sha256", "original_archive_sha256"]:
            if not group[col].astype(str).str.fullmatch(r"[0-9a-f]{64}").all():
                raise ValueError("Invalid provenance hash")
        from snapshot_model_predictions import valid_referee
        for _, row in group.iterrows():
            old = lookup.loc[row.supersedes]
            if (row.model_prediction_id != row.supersedes or row.model_prediction_id != _id(row)
                    or _semantic_key(row) != _semantic_key(old)
                    or str(row.original_created_at) != str(old.created_at)
                    or old.status != "pending"
                    or row.revision_reason != "officials_available_before_kickoff"
                    or not valid_referee(row.referee)):
                raise ValueError("Revision original/identity/officials mismatch")
        expected = {(h, a, t, m + suffix)
                    for h, a in set(zip(group.home_team, group.away_team))
                    for t, suffix in ((h, ""), (a, ""), ("CELKEM", "_total"))
                    for m in ("fouls", "corners", "yellow_cards")}
        actual = set(zip(group.home_team, group.away_team, group.team, group.market))
        if len(expected) != 90 or actual != expected:
            raise ValueError("Incomplete fixture/market coverage")
        if group.groupby(["home_team", "away_team"]).referee.nunique().ne(1).any():
            raise ValueError("Ambiguous referee")
        for col in ("prediction", "test_line", "range_low", "range_high", "range_probability"):
            if not np.isfinite(pd.to_numeric(group[col], errors="coerce")).all():
                raise ValueError("Invalid revision prediction/range")


def active(base, revisions):
    validate(base, revisions)
    if revisions.empty:
        return base
    return pd.concat([base[~base.model_prediction_id.isin(revisions.supersedes)], revisions],
                     ignore_index=True)


def _same(a, b, columns):
    for col in columns:
        x, y = a.get(col), b.get(col)
        if pd.isna(x) and pd.isna(y):
            continue
        if (pd.isna(x) or x == "") and (pd.isna(y) or y == ""):
            continue
        if str(x) == str(y):
            continue
        try:
            if github._same_settlement_number(x, y):
                continue
        except (ValueError, TypeError):
            pass
        return False
    return True


def merge_settlement(existing, candidate):
    """Only settlement fields may change; no rollback or silent settled conflict."""
    from model_prediction_stats import COLUMNS
    out = existing.copy()
    if set(candidate.model_prediction_id) != set(existing.model_prediction_id):
        raise ValueError("Revision settlement would lose an identity")
    incoming = candidate.set_index("model_prediction_id", drop=False)
    for idx, old in existing.iterrows():
        new = incoming.loc[old.model_prediction_id]
        immutable = [c for c in COLUMNS if c not in SETTLEMENT]
        if not _same(old, new, immutable):
            raise ValueError("Immutable revision conflict")
        if old.status == "settled":
            if new.status == "settled" and not _same(old, new, SETTLEMENT):
                raise ValueError("Conflicting revision settlements")
        elif old.status == "pending" and new.status == "settled":
            for col in SETTLEMENT:
                out.at[idx, col] = new[col]
        elif new.status != "pending":
            raise ValueError("Invalid revision status transition")
    return out


def atomic_write(path, frame):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".revision-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as handle:
            frame.to_csv(handle, index=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_settlement(archive, existing, candidate):
    merged = merge_settlement(existing, candidate)
    if github.enabled():
        for attempt in range(2):
            remote, sha = github.read_csv("data/predictions/" + NAME)
            if remote is None or set(remote.model_prediction_id) != set(existing.model_prediction_id):
                raise ValueError("Remote revision identities changed")
            # Compare local immutable provenance too, including retry.
            by_id = existing.set_index("model_prediction_id")
            for _, row in remote.iterrows():
                if not _same(row, by_id.loc[row.model_prediction_id], META):
                    raise ValueError("Revision provenance conflict")
            merged = merge_settlement(remote, merged)
            ok, detail = github.write_csv("data/predictions/" + NAME, merged,
                                          "stats: settle active model revisions", sha=sha)
            if ok:
                break
        else:
            raise RuntimeError(f"Revision settlement persistence failed: {detail}")
    atomic_write(path_for(archive), merged)


def split_save(archive, base, candidate):
    """Route active v2 settlement to its ledger and restore untouched v1 rows."""
    revisions = read(archive)
    validate(base, revisions)
    if revisions.empty:
        return candidate, False
    if not set(base.model_prediction_id).issubset(set(candidate.model_prediction_id)):
        raise ValueError("Revision save would lose an original identity")
    revised = candidate[candidate.model_prediction_id.isin(revisions.supersedes)]
    save_settlement(archive, revisions, revised)
    from model_prediction_stats import COLUMNS
    restored = pd.concat([candidate[~candidate.model_prediction_id.isin(revisions.supersedes)][COLUMNS],
                          base[base.model_prediction_id.isin(revisions.supersedes)][COLUMNS]],
                         ignore_index=True)
    old = base.set_index("model_prediction_id", drop=False)
    unchanged = (len(restored) == len(base) and set(restored.model_prediction_id) == set(old.index)
                 and all(_same(row, old.loc[row.model_prediction_id], COLUMNS)
                         for _, row in restored.iterrows()))
    return restored, unchanged
