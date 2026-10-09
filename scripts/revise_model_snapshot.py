"""Explicit, local-only pre-match revision. No implicit training or revision on reruns."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import pandas as pd
from bs4 import BeautifulSoup
import model_prediction_stats as stats
import model_snapshot_revisions as revisions
import update_officials as officials
import train_count_models as training
import score_round
from count_common import DATA_PATH, MODELS_DIR
from snapshot_model_predictions import valid_referee
from import_publication import import_lock

LOCK_PATH = DATA_PATH.parent.parent / "pl_analytika.sqlite"


def utc_now():
    return datetime.now(timezone.utc)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def live_context(season, round_no):
    """Fresh official match status, UK-zone kickoff, identity and appointments; no cache writes."""
    if season != officials.SEASON:
        raise ValueError("Unsupported official season")
    expected = officials._round_fixtures(round_no)
    url = officials.KNOWN_URLS.get(round_no) or officials._discover_url(round_no)
    if not url:
        raise ValueError("Official article unavailable")
    html = officials._get(url).text
    article = BeautifulSoup(html, "html.parser").find("article")
    if article is None:
        raise ValueError("Official article body unavailable")
    refs = [node["data-match-reference"] for node in article.select("[data-match-reference]")]
    if len(refs) != 10 or len(set(refs)) != 10:
        raise ValueError("Expected exactly ten official match identities")
    appointments = officials._parse_article(html, round_no)
    rows = []
    for reference in refs:
        match = officials._get(officials.MATCH_API + reference).json()
        if (str(match.get("matchId")) != reference or str(match.get("seasonId")) != season[:4]
                or str(match.get("competitionId")) != "8" or match.get("matchWeek") != round_no
                or match.get("period") != "PreMatch"
                or match.get("kickoffTimezoneString") != "Europe/London"):
            raise ValueError("Official match identity/status/timezone cannot be verified")
        dt = datetime.strptime(match["kickoff"], "%Y-%m-%d %H:%M:%S")
        kickoff = pd.Timestamp(dt).tz_localize("Europe/London", ambiguous="raise", nonexistent="raise")
        rows.append(dict(season=season, match_round=round_no,
                         home_team=officials.canonical(match["homeTeam"]["name"]),
                         away_team=officials.canonical(match["awayTeam"]["name"]),
                         match_date=dt.strftime("%Y-%m-%d"), kickoff_utc=kickoff.tz_convert("UTC").isoformat()))
    schedule = pd.DataFrame(rows)
    if set(zip(schedule.home_team, schedule.away_team)) != set(zip(expected.home_team, expected.away_team)):
        raise ValueError("Live schedule differs from expected round")
    return schedule, appointments


def preflight(schedule, appointments, now):
    keys = set(zip(schedule.home_team, schedule.away_team))
    if len(schedule) != 10 or len(keys) != 10:
        raise ValueError("Expected ten unique matches")
    dates = pd.to_datetime(schedule.kickoff_utc, utc=True, errors="raise")
    if dates.isna().any() or now >= dates.min():
        raise ValueError("First kickoff reached or unknown")
    if (len(appointments) != 10 or appointments.duplicated(["home_team", "away_team"]).any()
            or set(zip(appointments.home_team, appointments.away_team)) != keys
            or not appointments.referee.map(valid_referee).all()):
        raise ValueError("Officials incomplete/ambiguous: require 10/10")
    result = schedule.merge(appointments[["home_team", "away_team", "referee"]],
                            on=["home_team", "away_team"], validate="one_to_one")
    result["referee"] = result.referee.map(officials.canonical_referee)
    return result, dates.min().isoformat()


def create(season="2026-27", round_no=6):
    if stats.github_enabled():
        raise RuntimeError("Explicit revision is local-only; disable GitHub persistence")
    # Reuse the import lock: exclude both data publication and other revision attempts.
    with import_lock(LOCK_PATH):
        raw_hash = sha256(stats.LOG_PATH)
        base = pd.read_csv(stats.LOG_PATH)
        existing = revisions.read(stats.LOG_PATH)
        revisions.validate(base, existing)
        old = base[base.season.astype(str).eq(season) &
                   pd.to_numeric(base.match_round).eq(round_no)].copy()
        if not existing.empty and ((existing.season.astype(str) == season) &
                                  (pd.to_numeric(existing.match_round) == round_no)).any():
            return existing, False  # No training, scoring, or third revision.
        if len(old) != 90 or old.model_prediction_id.duplicated().any() or not old.status.eq("pending").all():
            raise ValueError("Expected ninety unique pending original predictions")
        schedule, appointments = live_context(season, round_no)
        fixtures, kickoff = preflight(schedule, appointments, utc_now())
        if set(zip(old.home_team, old.away_team)) != set(zip(fixtures.home_team, fixtures.away_team)):
            raise ValueError("Original snapshot and live fixtures differ")
        training_hash = sha256(DATA_PATH)
        data = pd.read_csv(DATA_PATH)
        dates = pd.to_datetime(data.match_date, errors="raise")
        if dates.isna().any() or dates.max().date() >= pd.Timestamp(kickoff).tz_convert("Europe/London").date():
            raise ValueError("Training data not strictly before target round day")
        training.main()  # Unmodified production training algorithm and configuration.
        model_hashes = {m: sha256(MODELS_DIR / f"{m}_model.joblib") for m in training.MARKETS}
        metadata = {m: json.loads((MODELS_DIR / f"{m}_model_metadata.json").read_text()) for m in training.MARKETS}
        if utc_now() >= pd.Timestamp(kickoff):
            raise ValueError("First kickoff reached during training")
        scored = score_round.score_fixtures(fixtures.to_dict("records"))
        # Fresh status/schedule/appointments again immediately before publication.
        final_schedule, final_appointments = live_context(season, round_no)
        final_fixtures, final_kickoff = preflight(final_schedule, final_appointments, utc_now())
        fields = ["home_team", "away_team", "match_date", "kickoff_utc", "referee"]
        if fixtures[fields].sort_values(fields).to_json() != final_fixtures[fields].sort_values(fields).to_json():
            raise ValueError("Schedule/officials changed during scoring; refusing publication")
        verified = utc_now().isoformat()
        created = utc_now().isoformat()
        unique = scored.sort_values("line").groupby(
            ["season", "home_team", "away_team", "team", "market"], as_index=False).first()
        lookup = old.set_index("model_prediction_id")
        rows = []
        for _, item in unique.iterrows():
            identity = stats._id(item)
            if identity not in lookup.index:
                raise ValueError("Scoring produced unexpected prediction identity")
            row = lookup.loc[identity].to_dict()
            market = str(item.market).removesuffix("_total")
            row.update(model_prediction_id=identity, prediction=float(item.prediction),
                       test_line=stats.prediction_test_line(item.prediction), referee=item.referee,
                       match_date=item.match_date, created_at=created,
                       range_low=float("nan"), range_high=float("nan"), range_probability=float("nan"),
                       revision=2, revision_reason="officials_available_before_kickoff", supersedes=identity,
                       original_created_at=lookup.loc[identity].created_at,
                       model_sha256=model_hashes[market], training_data_sha256=training_hash,
                       trained_at=metadata[market]["trained_at"], trained_rows=metadata[market]["trained_rows"],
                       first_kickoff_utc=final_kickoff, verified_at=verified, original_archive_sha256=raw_hash)
            rows.append(row)
        revised, _ = stats.enrich_prediction_ranges(pd.DataFrame(rows))
        combined = pd.concat([existing, revised], ignore_index=True)
        revisions.validate(base, combined)
        if sha256(stats.LOG_PATH) != raw_hash or sha256(DATA_PATH) != training_hash:
            raise ValueError("Archive/training data changed during revision")
        if any(sha256(MODELS_DIR / f"{m}_model.joblib") != model_hashes[m] for m in training.MARKETS):
            raise ValueError("Model changed during revision")
        if utc_now() >= pd.Timestamp(final_kickoff):
            raise ValueError("First kickoff reached before publication")
        revisions.atomic_write(revisions.path_for(stats.LOG_PATH), combined)
        return revised, True


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", default="2026-27")
    parser.add_argument("--round", type=int, default=6)
    args = parser.parse_args()
    rows, created = create(args.season, args.round)
    print(f"Revision 2: {len(rows)} rows; created={created}")
