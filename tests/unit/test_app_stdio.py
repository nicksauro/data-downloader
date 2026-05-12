"""Tests for ``data_downloader.ui.app._ensure_valid_stdio`` (task #21, RCA-B).

Em frozen windowed (``console=False``) ``sys.stdout``/``stderr`` são ``None``
e os std fds OS ficam inválidos — a ProfitDLL Delphi crasha ao tocá-los.
``_ensure_valid_stdio`` reabre os fds e garante ``sys.std*`` não-``None``.
"""

from __future__ import annotations

import os
import sys

from data_downloader.ui.app import _ensure_valid_stdio


def test_ensure_valid_stdio_replaces_none_stdout(monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdout", None, raising=False)
    monkeypatch.setattr(sys, "stderr", None, raising=False)
    monkeypatch.setattr(sys, "stdin", None, raising=False)
    _ensure_valid_stdio()
    assert sys.stdout is not None
    assert sys.stderr is not None
    assert sys.stdin is not None
    # Devem ser escrevíveis/legíveis sem explodir.
    sys.stdout.write("")
    sys.stderr.write("")


def test_ensure_valid_stdio_noop_when_valid() -> None:
    # fds 0/1/2 válidos no pytest runner — função deve ser no-op silenciosa.
    before_out, before_err = sys.stdout, sys.stderr
    _ensure_valid_stdio()
    # Não substitui streams já válidos.
    assert sys.stdout is before_out
    assert sys.stderr is before_err
    # E os fds continuam válidos.
    os.fstat(1)
    os.fstat(2)


def test_ensure_valid_stdio_idempotent(monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdout", None, raising=False)
    _ensure_valid_stdio()
    first = sys.stdout
    _ensure_valid_stdio()
    # Segunda chamada não troca de novo (já não-None).
    assert sys.stdout is first
