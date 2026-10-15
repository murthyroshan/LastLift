"""The repo guard must block secrets, attribution trailers, wrong authors and tool-config files."""
import codecs
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCAN = REPO / "scripts" / "secret_scan.py"
GOOD_NAME, GOOD_EMAIL = "murthyroshan", "mrslvt.dev@gmail.com"


def run(cwd, *args, env=None):
    return subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, env=env)


@pytest.fixture
def repo(tmp_path):
    if not shutil.which("git"):
        pytest.skip("git not available")
    run(tmp_path, "git", "init", "-q")
    run(tmp_path, "git", "config", "user.name", GOOD_NAME)
    run(tmp_path, "git", "config", "user.email", GOOD_EMAIL)
    (tmp_path / "scripts").mkdir()
    shutil.copy(SCAN, tmp_path / "scripts" / "secret_scan.py")
    return tmp_path


def scan(repo, *args):
    env = dict(os.environ, ENV_FILE=str(repo / "no-such.env"), GIT_AUTHOR_NAME=GOOD_NAME,
               GIT_AUTHOR_EMAIL=GOOD_EMAIL, GIT_COMMITTER_NAME=GOOD_NAME, GIT_COMMITTER_EMAIL=GOOD_EMAIL)
    return run(repo, sys.executable, "-I", "scripts/secret_scan.py", *args, env=env)


def stage(repo, name, text):
    (repo / name).write_text(text, encoding="utf-8")
    run(repo, "git", "add", "-f", name)  # -f: bypass any global ignore rules so the guard itself is tested


def test_clean_commit_passes(repo):
    stage(repo, "ok.py", "print('hello')\n")
    assert scan(repo, "--staged").returncode == 0


def test_blocks_fake_groq_key(repo):
    stage(repo, "leak.py", "KEY = 'gsk_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4'\n")
    out = scan(repo, "--staged")
    assert out.returncode == 1 and "groq key" in out.stderr


def test_blocks_env_file(repo):
    stage(repo, ".env", "X=1\n")
    assert scan(repo, "--staged").returncode == 1


def test_blocks_env_value_by_name_only(repo, tmp_path_factory):
    envdir = tmp_path_factory.mktemp("envdir")
    value = "fake-value-for-guard-test-0042"
    (envdir / ".env").write_text(f"MY_SECRET={value}\n", encoding="utf-8")
    stage(repo, "conf.txt", f"value is {value}\n")
    env = dict(os.environ, ENV_FILE=str(envdir / ".env"))
    out = run(repo, sys.executable, "-I", "scripts/secret_scan.py", "--staged", env=env)
    assert out.returncode == 1 and "MY_SECRET" in out.stderr and value not in out.stderr


def test_blocks_coauthor_trailer(repo):
    msg = repo / "MSG"
    msg.write_text("scaffold: repo\n\nCo-authored-by: Someone <a@b.c>\n", encoding="utf-8")
    assert scan(repo, "--msg", str(msg)).returncode == 1


def test_blocks_tool_reference_and_config(repo):
    word = codecs.decode("pynhqr", "rot13")
    stage(repo, "notes.md", f"built with {word.title()}\n")
    assert scan(repo, "--staged").returncode == 1
    run(repo, "git", "rm", "-q", "--cached", "notes.md")
    stage(repo, f"{word.upper()}.md", "instructions\n")
    assert scan(repo, "--staged").returncode == 1


def test_blocks_wrong_author(repo):
    stage(repo, "ok.py", "x = 1\n")
    env = dict(os.environ, ENV_FILE=str(repo / "none"), GIT_AUTHOR_NAME="someone", GIT_AUTHOR_EMAIL="x@y.z",
               GIT_COMMITTER_NAME=GOOD_NAME, GIT_COMMITTER_EMAIL=GOOD_EMAIL)
    out = run(repo, sys.executable, "-I", "scripts/secret_scan.py", "--staged", env=env)
    assert out.returncode == 1 and "author identity" in out.stderr
