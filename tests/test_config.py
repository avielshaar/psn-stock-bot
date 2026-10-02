import os

from psnbot.config import load_env_file


def test_env_inline_comments_and_empty(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("A_X=\nB_X=   # just a comment\nC_X=abc   # trailing\nD_X=\"q # keep\"\nE_X=-1001,-1002\n", encoding="utf-8")
    for k in ("A_X", "B_X", "C_X", "D_X", "E_X"):
        monkeypatch.delenv(k, raising=False)
    load_env_file(str(f))
    assert os.environ["A_X"] == "" and os.environ["B_X"] == ""
    assert os.environ["C_X"] == "abc"
    assert os.environ["D_X"] == "q # keep"
    assert os.environ["E_X"] == "-1001,-1002"
