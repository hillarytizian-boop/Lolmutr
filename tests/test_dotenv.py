from pathlib import Path

import app.config as cfg


def test_load_env_reads_file(tmp_path: Path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("FOO_TEST_KEY=bar\n# c\nEMPTY=\nQUOTED=\"x y\"\n", encoding="utf-8")
    monkeypatch.setattr(cfg, "ROOT", tmp_path)
    monkeypatch.delenv("FOO_TEST_KEY", raising=False)
    monkeypatch.delenv("QUOTED", raising=False)
    cfg.load_env(override=True)
    assert cfg.os.environ.get("FOO_TEST_KEY") == "bar"
    assert cfg.os.environ.get("QUOTED") == "x y"
