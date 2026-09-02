from pathlib import Path
import os
import io
import base64
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
