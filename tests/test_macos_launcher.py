from pathlib import Path
from scripts import macos_launcher as launcher


def test_rebuild_preserves_broken_environment(tmp_path, monkeypatch):
    environment = tmp_path / '.venv'
    (environment / 'bin').mkdir(parents=True)
    (environment / 'bin/python').symlink_to('/missing/temporary/python')
    (environment / 'old-marker').write_text('preserve')
    monkeypatch.setattr(launcher, 'ROOT', tmp_path)
    monkeypatch.setattr(launcher.sys, 'prefix', '/system-python')
    calls = []

    def create_environment(args, **kwargs):
        calls.append(args)
        assert not environment.exists()
        (environment / 'bin').mkdir(parents=True)
        (environment / 'bin/python').write_text('new-python')

    monkeypatch.setattr(launcher.subprocess, 'run', create_environment)
    python = launcher.prepare_environment()
    assert python.read_text() == 'new-python'
    assert len(calls) == 1
    backups = list(tmp_path.glob('.venv.backup-*'))
    assert len(backups) == 1
    assert (backups[0] / 'old-marker').read_text() == 'preserve'


def test_existing_environment_skips_install(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, 'ROOT', tmp_path)
    monkeypatch.setattr(launcher.sys, 'prefix', str(tmp_path / '.venv'))
    monkeypatch.setattr(launcher.importlib.util, 'find_spec', lambda module: object())
    def unexpected(*args, **kwargs):
        raise AssertionError('已有依赖时不应安装')
    monkeypatch.setattr(launcher.subprocess, 'run', unexpected)
    assert launcher.prepare_environment() == tmp_path / '.venv/bin/python'
