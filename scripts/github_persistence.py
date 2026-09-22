from pathlib import Path
import os
import io
import base64
import math
import pandas as pd
import requests

BASE=Path(__file__).resolve().parent.parent

def config():
    token=os.environ.get("PL_ANALYTIKA_GITHUB_TOKEN","").strip()
    repo=os.environ.get("PL_ANALYTIKA_GITHUB_REPO","Multikabel/pl-analytika-2").strip()
    branch=os.environ.get("PL_ANALYTIKA_GITHUB_BRANCH","main").strip()
    return token,repo,branch

def enabled():
    token,repo,branch=config()
    return bool(token and repo and branch)

def _headers(token):
    return {
        "Authorization":f"Bearer {token}",
        "Accept":"application/vnd.github+json",
        "X-GitHub-Api-Version":"2022-11-28",
    }

def read_csv(repo_path, columns=None):
    """Read the latest CSV directly from GitHub. Returns (df, sha)."""
    token,repo,branch=config()
    if not token:
        return None,None
    url=f"https://api.github.com/repos/{repo}/contents/{repo_path}"
    r=requests.get(url,headers=_headers(token),params={"ref":branch},timeout=20)
    if r.status_code==404:
        return pd.DataFrame(columns=columns or []),None
    r.raise_for_status()
    payload=r.json()
    raw=base64.b64decode(payload["content"])
    if not raw.strip():
        df=pd.DataFrame(columns=columns or [])
    else:
        df=pd.read_csv(io.BytesIO(raw))
    if columns:
        for c in columns:
            if c not in df.columns:
                df[c]=pd.NA
        df=df[columns]
    return df,payload.get("sha")

def write_csv(repo_path, df, message, sha=None):
    """Commit a CSV to GitHub via Contents API."""
    token,repo,branch=config()
    if not token:
        raise RuntimeError("GitHub persistence token is not configured.")
    raw=df.to_csv(index=False).encode("utf-8-sig")
    content=base64.b64encode(raw).decode("ascii")
    body={"message":message,"content":content,"branch":branch}
    if sha:
        body["sha"]=sha
    url=f"https://api.github.com/repos/{repo}/contents/{repo_path}"
    r=requests.put(url,headers=_headers(token),json=body,timeout=30)
    if r.status_code in (409,422):
        # Caller can reload/merge and retry once.
        return False,r.text
    r.raise_for_status()
    return True,r.json()

def merge_append_only(remote, candidate, key="prediction_id"):
    """
    For manual tip creation remote rows are authoritative.
    Only genuinely new IDs are appended, so a stale Streamlit instance
    cannot overwrite a WIN/LOSS settlement produced by GitHub Actions.
    """
    if remote is None or remote.empty:
        return candidate.copy()
    if candidate is None or candidate.empty:
        return remote.copy()
    remote_ids=set(remote[key].astype(str))
    add=candidate[~candidate[key].astype(str).isin(remote_ids)].copy()
    return pd.concat([remote,add],ignore_index=True)


class SettlementConflictError(RuntimeError):
    """A tip cannot be settled without choosing between conflicting records."""


def validate_settlement_ids(remote, local, key="prediction_id"):
    """Fail before writing if settlement would discard any local archive ID."""
    if remote is None:
        raise SettlementConflictError("Settlement conflict: remote archive unavailable")
    if local is None or local.empty:
        return
    for name, frame in (("remote", remote), ("local", local)):
        ids = frame[key].astype(str)
        if frame[key].isna().any() or ids.str.strip().eq("").any() or ids.duplicated().any():
            raise SettlementConflictError(f"Settlement conflict: ambiguous {name} IDs")
    missing = set(local[key].astype(str)) - set(remote[key].astype(str))
    if missing:
        raise SettlementConflictError(
            f"Settlement conflict: local IDs missing remotely: {', '.join(sorted(missing))}")


def _same_settlement_number(a, b):
    """Compare numeric inputs, allowing only binary float round-trip noise."""
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError, OverflowError):
        return False
    if not (math.isfinite(a) and math.isfinite(b)):
        return False
    # Four representable float steps, not rounding odds/stakes to decimal places.
    return math.isclose(a, b, rel_tol=0., abs_tol=4 * max(math.ulp(a), math.ulp(b)))


def validate_local_settlements(merged, local, key="prediction_id"):
    """Reject a proposed write that would lose or replace a disk settlement."""
    validate_settlement_ids(merged, local, key)
    if local is None or local.empty:
        return
    by_id = merged.set_index(merged[key].astype(str))
    numeric_fields = ("actual_value", "profit_units")
    fields = numeric_fields + ("result", "settled_at", "match_date")
    for _, saved in local[local["status"].eq("settled")].iterrows():
        identity = str(saved[key])
        proposed = by_id.loc[identity]
        if proposed.get("status") != "settled":
            raise SettlementConflictError(
                f"Settlement conflict for {identity}: local settled state would be lost")
        differences = []
        for field in fields:
            a, b = saved.get(field), proposed.get(field)
            a_empty = pd.isna(a) or (isinstance(a, str) and a == "")
            b_empty = pd.isna(b) or (isinstance(b, str) and b == "")
            if a_empty or b_empty:
                equal = a_empty and b_empty
            else:
                equal = _same_settlement_number(a, b) if field in numeric_fields else a == b
            if not equal:
                differences.append(field)
        if differences:
            raise SettlementConflictError(
                f"Settlement conflict for {identity}: local settlement differs: {', '.join(differences)}")


def merge_settlements(remote, candidate, key="prediction_id"):
    """Update existing pending IDs only; keep the original prediction fields.

    A second, different settled version is an explicit conflict, including on
    retry. Creation of new IDs belongs exclusively to merge_append_only.
    """
    fields = ("status", "actual_value", "result", "profit_units", "settled_at", "match_date")
    validate_settlement_ids(remote, candidate, key)
    out = remote.copy().reset_index(drop=True)
    if candidate is None or candidate.empty:
        return out

    def same(a, b):
        # CSV round trips represent empty text as NaN.
        a_empty = pd.isna(a) or (isinstance(a, str) and a == "")
        b_empty = pd.isna(b) or (isinstance(b, str) and b == "")
        return (a_empty and b_empty) or (not a_empty and not b_empty and a == b)

    indices = {str(value): idx for idx, value in out[key].items()}
    for _, local in candidate.iterrows():
        if local.get("status") != "settled":
            continue
        identity = str(local[key])
        if identity not in indices:
            raise SettlementConflictError(f"Settlement conflict: missing remote ID {identity}")
        idx = indices[identity]
        original = out.loc[idx]
        if original.get("status") == "settled":
            differences = [c for c in set(out.columns) | set(candidate.columns)
                           if not same(original.get(c), local.get(c))]
            if differences:
                raise SettlementConflictError(
                    f"Settlement conflict for {identity}: {', '.join(sorted(differences))}")
        elif original.get("status") == "pending":
            # match_date is intentionally excluded: settlement may correct it.
            identity_fields = ("season", "home_team", "away_team", "team", "venue", "market")
            numeric_fields = ("line", "bookmaker_odds", "stake_units")
            differences = [c for c in identity_fields
                           if not same(original.get(c), local.get(c))]
            differences += [c for c in numeric_fields
                            if not _same_settlement_number(original.get(c), local.get(c))]
            if differences:
                raise SettlementConflictError(
                    f"Settlement conflict for {identity}: immutable inputs differ: {', '.join(differences)}")
            for field in fields:
                out.at[idx, field] = local.get(field)
        else:
            raise SettlementConflictError(f"Settlement conflict: invalid remote status for {identity}")
    return out
