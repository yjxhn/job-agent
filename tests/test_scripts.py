"""Minimal regression tests for the helper scripts under scripts/."""

import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"


def _load_script(name: str):
    path = SCRIPTS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def import_cookies_mod():
    return _load_script("import_cookies")


@pytest.fixture
def check_llm_naming_mod():
    return _load_script("check_llm_naming")


def test_import_cookies_missing_args(import_cookies_mod, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["import_cookies.py"])
    with pytest.raises(SystemExit) as exc:
        import_cookies_mod.main()
    assert exc.value.code == 1


def test_import_cookies_domain_missing_value(import_cookies_mod, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["import_cookies.py", "x.json", "boss", "--domain"])
    with pytest.raises(SystemExit) as exc:
        import_cookies_mod.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "--domain 后缺少域名参数" in out


def test_import_cookies_success(import_cookies_mod, monkeypatch, capsys):
    monkeypatch.setattr(
        import_cookies_mod,
        "convert_and_save",
        lambda *a, **k: {
            "count": 3,
            "out_path": "data/cookies/boss_zhipin.json",
            "session_found": ["wt2"],
        },
    )
    monkeypatch.setattr(
        sys, "argv", ["import_cookies.py", "x.json", "boss_zhipin", "--domain", "zhipin.com"]
    )
    import_cookies_mod.main()
    out = capsys.readouterr().out
    assert "[OK] 3 cookies" in out
    assert "[OK] 登录态 cookie 存在" in out


def test_check_llm_naming_load_declared_provider(check_llm_naming_mod, tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("llm:\n  provider: deepseek\n", encoding="utf-8")
    assert check_llm_naming_mod.load_declared_provider(cfg) == "deepseek"


def test_check_llm_naming_scan_finds_banned(check_llm_naming_mod, tmp_path):
    pkg = tmp_path / "llm"
    pkg.mkdir()
    (pkg / "providers.py").write_text('x = "claude"\n', encoding="utf-8")
    offenders = check_llm_naming_mod.scan(pkg)
    assert len(offenders) == 1
    assert "claude" in offenders[0][3]


def test_check_llm_naming_main_clean(check_llm_naming_mod, tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("llm:\n  provider: deepseek\n", encoding="utf-8")
    pkg = tmp_path / "llm"
    pkg.mkdir()
    (pkg / "providers.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["check_llm_naming.py", "--config", str(cfg), "--pkg", str(pkg)],
    )
    assert check_llm_naming_mod.main() == 0


def test_check_llm_naming_main_banned(check_llm_naming_mod, tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("llm:\n  provider: deepseek\n", encoding="utf-8")
    pkg = tmp_path / "llm"
    pkg.mkdir()
    (pkg / "providers.py").write_text("model = 'gpt-4'\n", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["check_llm_naming.py", "--config", str(cfg), "--pkg", str(pkg)],
    )
    assert check_llm_naming_mod.main() == 1
