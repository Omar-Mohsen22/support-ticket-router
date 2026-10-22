"""Step 31 -- the optional Hugging Face token, in a module that imports neither torch nor
transformers, so the tests can cover it in the dev venv and in the Docker image.

The adapter repo (train/config.yaml's hub_model_id) is public since step 31, so a token is
optional. load_hf_token() returns HF_TOKEN if it is set (the project's .env wins over the
environment, as elsewhere in this repo), and None otherwise. With None, huggingface_hub uses a
saved `hf auth login` token if there is one, and downloads anonymously otherwise.

python-dotenv is imported lazily and is optional: the Docker image (requirements-serve.txt)
does not install it, and there the token comes from the environment only.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = REPO_ROOT / ".env"


def load_hf_token(env_path: Path = ENV_PATH) -> str | None:
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=env_path, override=True)
    except ImportError:
        pass
    token = os.environ.get("HF_TOKEN") or None
    if token is None:
        print("HF_TOKEN not set: downloading the base model and adapter without it.")
    return token
