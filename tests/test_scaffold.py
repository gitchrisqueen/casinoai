"""Smoke tests for the Phase 0 scaffold."""

import casinoai
from casinoai.cli import main


def test_version():
    assert casinoai.__version__


def test_cli_no_args_prints_help(capsys):
    assert main([]) == 1
    assert "casinoai" in capsys.readouterr().out
