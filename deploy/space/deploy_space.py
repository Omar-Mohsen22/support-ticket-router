"""Step 28 -- deploy the TF-IDF API to the Hugging Face Docker Space
Omar-Mohsen22/support-ticket-router, then smoke-test it.

1. Assemble exactly the files the Dockerfile build needs. The list comes from the
   Dockerfile's COPY lines and the .dockerignore allowlist, and uses tracked files only
   (git ls-files). deploy/space/README.md becomes the Space's README.md.
2. Upload with HfApi().upload_folder(repo_type="space"). delete_patterns removes stale
   files; .gitattributes is never deleted.
3. If the upload created a commit, wait until a build stage is seen, then until RUNNING.
   The runtime API reports no commit sha, so seeing the transition is what shows the new
   build is the one running. Fail on an error stage or on timeout.
4. Smoke-test the live Space with an Authorization: Bearer header:
   - /health must return 200 with model_loaded true;
   - /predict on a real test ticket must return 200 and match that ticket's published
     tfidf-baseline prediction exactly;
   - latency is logged for every request.

The token comes from the HF_SPACE_TOKEN environment variable (or .env locally) and is
never printed.

Run from the repo root:
    python deploy/space/deploy_space.py --dry-run   (list the files only; needs no token)
    python deploy/space/deploy_space.py             (upload, wait, smoke-test)
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import shutil
import statistics
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SPACE_ID = "Omar-Mohsen22/support-ticket-router"
SPACE_README = REPO_ROOT / "deploy" / "space" / "README.md"

# From the Dockerfile's COPY lines, filtered by the .dockerignore allowlist.
EXACT_FILES = [
    "Dockerfile",
    ".dockerignore",
    "requirements-serve.txt",
    "pytest.ini",
    "data/processed/label_map.json",
    "data/processed/test.parquet",
    "data/processed/val.parquet",
    "models/tfidf/model.joblib",
    "models/tfidf/meta.json",
]
TRACKED_DIRS = ["src", "tests", "results"]
# Nothing matching these may ever be uploaded (mirrors .dockerignore's explicit denies).
FORBIDDEN = ["*.env", ".env*", "*/.env*", "*.key", "*.pem", "*__pycache__*", "*.pyc", ".venv/*"]

BUILD_STAGES = {"BUILDING", "RUNNING_BUILDING", "APP_STARTING", "RUNNING_APP_STARTING"}
ERROR_STAGES = {"BUILD_ERROR", "RUNTIME_ERROR", "CONFIG_ERROR", "STOPPED", "PAUSED", "DELETING"}
TRANSITION_TIMEOUT_S = 5 * 60   # a real commit starts a build within seconds; 5 min is generous
RUNNING_TIMEOUT_S = 25 * 60     # under HF's default 30-min startup timeout
POLL_S = 15
SMOKE_TICKET_ID = "tkt_009916"  # the README's example ticket
N_WARM = 5


def files_to_upload() -> list[str]:
    tracked = subprocess.run(
        ["git", "ls-files", *TRACKED_DIRS], cwd=REPO_ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.split()
    files = sorted(set(EXACT_FILES) | set(tracked))
    for f in files:
        if not (REPO_ROOT / f).is_file():
            raise SystemExit(f"STOP: {f} is required by the Docker build but missing.")
        if any(fnmatch.fnmatch(f, pat) for pat in FORBIDDEN):
            raise SystemExit(f"STOP: {f} matches a forbidden pattern and must never be uploaded.")
    return files


def get_token() -> str:
    token = os.environ.get("HF_SPACE_TOKEN")
    if not token:
        try:
            from dotenv import load_dotenv
            load_dotenv(REPO_ROOT / ".env", override=True)
            token = os.environ.get("HF_SPACE_TOKEN")
        except ImportError:
            pass
    if not token:
        raise SystemExit("STOP: HF_SPACE_TOKEN is not set.")
    return token


def commit_sha() -> str:
    return os.environ.get("GITHUB_SHA") or subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True, capture_output=True, text=True,
    ).stdout.strip()


def wait_for_running(api, created_commit: bool, space_id: str = SPACE_ID) -> str:
    start = time.monotonic()
    seen_build = not created_commit
    while True:
        stage = str(api.get_space_runtime(space_id).stage)
        elapsed = time.monotonic() - start
        print(f"  [{elapsed:6.0f}s] stage={stage}", flush=True)
        if stage in ERROR_STAGES:
            raise SystemExit(f"STOP: Space entered {stage}.")
        if stage in BUILD_STAGES:
            seen_build = True
        if stage == "RUNNING" and seen_build:
            return stage
        if not seen_build and elapsed > TRANSITION_TIMEOUT_S:
            raise SystemExit("STOP: no build stage seen after the upload commit; cannot confirm "
                             "the running app is the new build.")
        if elapsed > RUNNING_TIMEOUT_S:
            raise SystemExit(f"STOP: Space not RUNNING after {RUNNING_TIMEOUT_S // 60} min.")
        time.sleep(POLL_S)


def request(url: str, token: str, payload: dict | None = None) -> tuple[int, dict | str, float]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    req.add_header("Authorization", f"Bearer {token}")
    if data:
        req.add_header("Content-Type", "application/json")
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            code, body = resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        code, body = e.code, e.read().decode("utf-8", "replace")[:300]
    ms = (time.perf_counter() - t0) * 1000
    try:
        return code, json.loads(body), ms
    except json.JSONDecodeError:
        return code, body, ms


def smoke_test(host: str, token: str) -> list[str]:
    import pandas as pd

    ticket = pd.read_parquet(REPO_ROOT / "data" / "processed" / "test.parquet").set_index("id").loc[SMOKE_TICKET_ID]
    payload = {"subject": ticket["subject"] if isinstance(ticket["subject"], str) else None,
               "body": ticket["body"]}
    with open(REPO_ROOT / "results" / "tfidf-baseline.predictions.jsonl", encoding="utf-8") as f:
        published = next(json.loads(line) for line in f if json.loads(line)["id"] == SMOKE_TICKET_ID)
    expected = {k: published[k] for k in ("queue", "priority", "type")}

    # Right after RUNNING the router can briefly answer 5xx; retry /health for up to 2 min.
    deadline = time.monotonic() + 120
    while True:
        code, body, ms = request(f"{host}/health", token)
        if code == 200 or time.monotonic() > deadline:
            break
        print(f"  /health not ready yet (HTTP {code}); retrying", flush=True)
        time.sleep(5)
    lines = [f"| GET /health (first) | {code} | {ms:.0f} | {body} |"]
    if code != 200 or not (isinstance(body, dict) and body.get("model_loaded") is True):
        raise SystemExit(f"STOP: /health -> HTTP {code}: {body}")

    code, body, ms = request(f"{host}/predict", token, payload)
    lines.append(f"| POST /predict (first) | {code} | {ms:.0f} | {body} |")
    if code != 200:
        raise SystemExit(f"STOP: /predict -> HTTP {code}: {body}")
    got = {k: body[k] for k in ("queue", "priority", "type")}
    match = got == expected
    lines.append(f"| /predict vs published ({SMOKE_TICKET_ID}) | {'MATCH' if match else 'MISMATCH'} | "
                 f"- | got {got}, published {expected} |")

    warm = []
    for i in range(N_WARM):
        code, body, ms = request(f"{host}/predict", token, payload)
        if code != 200:
            raise SystemExit(f"STOP: warm /predict #{i + 1} -> HTTP {code}: {body}")
        warm.append(ms)
        lines.append(f"| POST /predict (warm #{i + 1}) | {code} | {ms:.0f} | server latency_ms={body['latency_ms']:.2f} |")
    lines.append(f"| warm /predict median | - | {statistics.median(warm):.0f} | over {N_WARM} requests |")
    if not match:
        print("\n".join(lines))
        raise SystemExit("STOP: the live /predict output does not match the published prediction.")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="List the files to upload and exit.")
    args = parser.parse_args()

    files = files_to_upload()
    print(f"{len(files)} files (+ deploy/space/README.md as README.md):")
    for f in files:
        print(f"  {f}")
    if args.dry_run:
        return

    from huggingface_hub import HfApi

    token = get_token()
    api = HfApi(token=token)
    info = api.space_info(SPACE_ID)
    if info.private:
        raise SystemExit("STOP: the Space is private; since step 31 this deploy expects it public.")
    runtime = api.get_space_runtime(SPACE_ID)
    if runtime.requested_hardware != "cpu-basic":
        raise SystemExit(f"STOP: requested hardware is {runtime.requested_hardware}, not cpu-basic.")
    previous_sha = info.sha

    sha = commit_sha()
    with tempfile.TemporaryDirectory() as tmp:
        for f in files:
            dest = Path(tmp) / f
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO_ROOT / f, dest)
        shutil.copy2(SPACE_README, Path(tmp) / "README.md")
        commit = api.upload_folder(
            repo_id=SPACE_ID, repo_type="space", folder_path=tmp,
            delete_patterns=["*", "**/*"],
            commit_message=f"Deploy {sha} from github.com/Omar-Mohsen22/support-ticket-router",
        )
    new_sha = api.space_info(SPACE_ID).sha
    created = new_sha != previous_sha
    print(f"Upload: {'new commit ' + new_sha if created else 'no changes, no new commit'} ({commit.commit_url})")

    stage = wait_for_running(api, created)
    host = api.space_info(SPACE_ID).host
    print(f"Space {SPACE_ID} is {stage} at {host}")

    lines = smoke_test(host, token)
    table = ("## Space smoke test\n\n"
             f"Space: `{SPACE_ID}` ({host}), stage {stage}, deployed from `{sha}`.\n\n"
             "| request | HTTP | client latency ms | detail |\n| --- | --- | --- | --- |\n"
             + "\n".join(lines) + "\n")
    print(table)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(table)


if __name__ == "__main__":
    main()
