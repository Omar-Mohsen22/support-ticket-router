"""Step 29 -- deploy the ZeroGPU demo Space Omar-Mohsen22/support-ticket-router-demo,
then smoke-test it.

1. Assemble the Space bundle:
   - deploy/demo/app.py, requirements.txt and README.md;
   - the project modules the demo reuses, copied as they are with their src/ layout
     (see SRC_MODULES);
   - the files those modules read: label_map.json, train/config.yaml and the committed
     TF-IDF artifact;
   - examples.json, generated here from test.parquet and the published predictions:
     three known label-noise tickets from reports/error_analysis.md, plus the first three
     test tickets (distinct queues) where both published models match the gold label on
     every field.
2. Upload with HfApi().upload_folder(repo_type="space"). delete_patterns removes stale files.
3. Wait for a build stage, then RUNNING (reuses deploy/space/deploy_space.py).
4. Smoke-test with gradio_client and the token: the "classify" endpoint on one example ticket
   must return valid labels for both models. It logs latency and the GPU time the call used.
   Every GPU call counts toward the account's ZeroGPU quota.

The token comes from the HF_SPACE_TOKEN environment variable (or .env locally) and is never
printed. The Space's own HF_TOKEN secret (read access to the adapter repo) is set
separately, once, with --set-secret.

Run from the repo root:
    python deploy/demo/deploy_demo.py --dry-run      (list the bundle and examples only)
    python deploy/demo/deploy_demo.py --set-secret   (set the Space secret HF_TOKEN from .env)
    python deploy/demo/deploy_demo.py                (upload, wait, smoke-test)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "deploy" / "space"))

from deploy_space import commit_sha, get_token, wait_for_running  # noqa: E402

SPACE_ID = "Omar-Mohsen22/support-ticket-router-demo"
DEMO_DIR = REPO_ROOT / "deploy" / "demo"
DEMO_FILES = {"app.py": "app.py", "ui.py": "ui.py", "requirements.txt": "requirements.txt", "README.md": "README.md"}
SRC_MODULES = [
    "src/ticket_router/__init__.py",
    "src/ticket_router/hf_auth.py",
    "src/ticket_router/ticket_text.py",
    "src/ticket_router/schema.py",
    "src/ticket_router/metrics.py",
    "src/ticket_router/run_meta.py",
    "src/ticket_router/evaluate.py",
    "src/ticket_router/make_sft_dataset.py",
    "src/ticket_router/predictors/__init__.py",
    "src/ticket_router/predictors/adapter_predictor.py",
    "src/ticket_router/predictors/tfidf_baseline.py",
]
DATA_FILES = [
    "data/processed/label_map.json",
    "train/config.yaml",
    "models/tfidf/model.joblib",
    "models/tfidf/meta.json",
]
FIELDS = ["queue", "priority", "type"]
# From reports/error_analysis.md's samples: ticket text that contradicts the gold label.
LABEL_NOISE_IDS = ["tkt_011979", "tkt_023949", "tkt_024807"]
N_AGREEMENT = 3
# Step 30: three tickets Omar wrote. They are not in the dataset, have no gold label and no stored
# gpt-4o-mini result. They are listed after the test tickets, and TF-IDF and the adapter run live.
CUSTOM_TICKETS = [
    ("custom-1", "Charged twice for annual plan",
     "I renewed my annual subscription yesterday and my credit card was charged twice for the same "
     "amount. Please refund the extra payment and confirm when it is done."),
    ("custom-2", "Dashboard down for all users",
     "Since 9 AM none of our team can log in to the dashboard. We get a 503 error on every page. "
     "This is blocking our whole support team. Is there an outage?"),
    ("custom-3", "Pricing for 50 seats",
     "We are evaluating your platform for our company. Could you send pricing for 50 user seats and "
     "tell us if there is a discount for annual billing?"),
]


def load_predictions(name: str) -> dict:
    with open(REPO_ROOT / "results" / f"{name}.predictions.jsonl", encoding="utf-8") as f:
        return {r["id"]: r for r in map(json.loads, f)}


def build_examples() -> list[dict]:
    import pandas as pd

    test = pd.read_parquet(REPO_ROOT / "data" / "processed" / "test.parquet")
    tfidf, adapter = load_predictions("tfidf-baseline"), load_predictions("qlora-adapter-ckpt1500")
    # Step 30: the stored zero-shot gpt-4o-mini predictions, copied into examples.json for the
    # example tickets only (the full predictions file is not bundled into the Space).
    gpt = load_predictions("api-gpt4o-mini-full-test")

    def entry(row, why: str, noisy: bool = False) -> dict:
        return {
            "id": row.id,
            "subject": row.subject if isinstance(row.subject, str) else None,
            "body": row.body,
            "gold": " / ".join(getattr(row, f) for f in FIELDS),
            "why": why,
            "gold_labels": {f: getattr(row, f) for f in FIELDS},
            "noisy": noisy,
            "gpt4o_mini": {f: gpt[row.id][f] for f in FIELDS},
        }

    agreement, queues = [], set()
    for row in test.itertuples():
        both_right = all(tfidf[row.id].get(f) == getattr(row, f) == adapter[row.id].get(f) for f in FIELDS)
        if both_right and row.queue not in queues:
            agreement.append(entry(row, "both published models match the gold label on every field"))
            queues.add(row.queue)
        if len(agreement) == N_AGREEMENT:
            break
    by_id = test.set_index("id")
    noise = []
    for tid in LABEL_NOISE_IDS:
        r = by_id.loc[tid]
        row = type("Row", (), {"id": tid, "subject": r["subject"], "body": r["body"],
                               **{f: r[f] for f in FIELDS}})
        noise.append(entry(row, "label-noise case from the error analysis: the text contradicts the gold label",
                           noisy=True))
    custom = [{"id": cid, "subject": subject, "body": body, "gold": None,
               "why": "a ticket I wrote; not in the dataset, no gold label",
               "gold_labels": None, "noisy": False, "custom": True, "gpt4o_mini": None}
              for cid, subject, body in CUSTOM_TICKETS]
    return agreement + noise + custom


def bundle_files() -> dict[str, Path]:
    files = {dest: DEMO_DIR / src for src, dest in DEMO_FILES.items()}
    files.update({f: REPO_ROOT / f for f in SRC_MODULES + DATA_FILES})
    for dest, src in files.items():
        if not src.is_file():
            raise SystemExit(f"STOP: {src} is needed by the demo but missing.")
    return files


def set_secret() -> None:
    from huggingface_hub import HfApi

    try:
        from dotenv import load_dotenv
        load_dotenv(REPO_ROOT / ".env", override=True)
    except ImportError:
        pass
    adapter_token = os.environ.get("HF_TOKEN")
    if not adapter_token:
        raise SystemExit("STOP: HF_TOKEN (read access to the adapter repo) is not set.")
    HfApi(token=get_token()).add_space_secret(
        SPACE_ID, "HF_TOKEN", adapter_token,
        description="Read-only token for the adapter repo",
    )
    print(f"Set Space secret HF_TOKEN on {SPACE_ID} (value not printed).")


def smoke_test(token: str, example: dict) -> list[str]:
    from gradio_client import Client

    t0 = time.perf_counter()
    client = Client(SPACE_ID, token=token, verbose=False)
    connect_ms = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter()
    table, timing = client.predict(example["subject"] or "", example["body"], api_name="/classify")
    call_ms = (time.perf_counter() - t0) * 1000

    rows = table["data"] if isinstance(table, dict) else table
    label_map = json.loads((REPO_ROOT / "data" / "processed" / "label_map.json").read_text(encoding="utf-8"))
    problems = []
    for field, tfidf_label, adapter_label in rows:
        for model_name, label in (("TF-IDF", tfidf_label), ("fine-tuned", adapter_label)):
            if label not in label_map[field]:
                problems.append(f"{model_name} {field}={label!r}")
    gpu_ms = timing.split("GPU time inside the call: ")[1].split(" ms")[0]
    lines = [
        f"| client connect | - | {connect_ms:.0f} | Space API loaded |",
        f"| classify `{example['id']}` | {'OK' if not problems else 'INVALID'} | {call_ms:.0f} | "
        f"{', '.join(f'{r[0]}: {r[1]} / {r[2]}' for r in rows)} |",
        f"| server timing | - | - | {timing.splitlines()[0]} |",
        f"| GPU time used by this smoke test | - | {gpu_ms} | counts toward the ZeroGPU quota |",
    ]
    if problems:
        print("\n".join(lines))
        raise SystemExit(f"STOP: invalid labels from the Space: {problems}")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--set-secret", action="store_true")
    args = parser.parse_args()

    if args.set_secret:
        set_secret()
        return

    files = bundle_files()
    examples = build_examples()
    print(f"{len(files)} files + examples.json:")
    for dest in sorted(files):
        print(f"  {dest}")
    print("examples:")
    for e in examples:
        print(f"  {e['id']}: {e['gold']} -- {e['why']}")
    if args.dry_run:
        return

    from huggingface_hub import HfApi

    token = get_token()
    api = HfApi(token=token)
    info = api.space_info(SPACE_ID)
    runtime = api.get_space_runtime(SPACE_ID)
    if info.private:
        raise SystemExit("STOP: the demo Space is private; since step 31 this deploy expects it public.")
    if runtime.requested_hardware != "zero-a10g":
        raise SystemExit(f"STOP: requested hardware is {runtime.requested_hardware}, not ZeroGPU.")
    previous_sha = info.sha

    sha = commit_sha()
    with tempfile.TemporaryDirectory() as tmp:
        for dest, src in files.items():
            (Path(tmp) / dest).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, Path(tmp) / dest)
        (Path(tmp) / "examples.json").write_text(json.dumps(examples, indent=2), encoding="utf-8")
        commit = api.upload_folder(
            repo_id=SPACE_ID, repo_type="space", folder_path=tmp,
            delete_patterns=["*", "**/*"],
            commit_message=f"Deploy {sha} from github.com/Omar-Mohsen22/support-ticket-router",
        )
    new_sha = api.space_info(SPACE_ID).sha
    created = new_sha != previous_sha
    print(f"Upload: {'new commit ' + new_sha if created else 'no changes, no new commit'} ({commit.commit_url})")

    stage = wait_for_running(api, created, space_id=SPACE_ID)
    print(f"Space {SPACE_ID} is {stage}")

    lines = smoke_test(token, examples[0])
    table = ("## Demo Space smoke test\n\n"
             f"Space: `{SPACE_ID}`, stage {stage}, deployed from `{sha}`.\n\n"
             "| check | result | ms | detail |\n| --- | --- | --- | --- |\n" + "\n".join(lines) + "\n")
    print(table)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(table)


if __name__ == "__main__":
    main()
