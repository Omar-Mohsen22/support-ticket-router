"""load_hf_token: HF_TOKEN is optional since the adapter repo went public (step 31)."""

from ticket_router.hf_auth import load_hf_token


def test_unset_returns_none(monkeypatch, tmp_path):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    assert load_hf_token(tmp_path / "missing.env") is None


def test_set_returns_value(monkeypatch, tmp_path):
    monkeypatch.setenv("HF_TOKEN", "dummy-not-a-real-token")
    assert load_hf_token(tmp_path / "missing.env") == "dummy-not-a-real-token"


def test_empty_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("HF_TOKEN", "")
    assert load_hf_token(tmp_path / "missing.env") is None
