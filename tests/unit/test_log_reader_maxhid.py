"""Tests for ``data_downloader.dll.log_reader`` — Story 4.29 AC1+AC7.

Story 4.29 — MaxHID UX fix. Verifica que o parser do LogDesktop:

1. Reconhece bloco ``ProcessLoginResult`` com ``ActivationResult=MaxHID``.
2. Retorna o bloco mais recente quando há múltiplas entradas no log.
3. Retorna ``None`` em log inexistente.
4. Tolerante a logs truncados (linha incompleta no final).
5. Reconhece login OK (``ActivationResult=OK``) — fluxo normal não-MaxHID.

A evidência canônica vem de ``LogDesktop_2026_05_17.log`` (reportado por
Pichau 2026-05-17). Os fixtures replicam o formato exato observado.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from data_downloader.dll.log_reader import (
    LoginResultSnapshot,
    find_latest_log_desktop,
    parse_login_result_from_log,
)

# =====================================================================
# Fixtures de log — formato canônico observado
# =====================================================================

_MAX_HID_BLOCK = """\
17/05 11:40:19.197 : #Con#Info  TInfoClientProcessor.ProcessLoginResult:
                                  ActivationResult=MaxHID
                                  Mensagem="Todos os seus logins estão em uso"
                                  HardLogout=True
                                  LoginResult=MaxHID
17/05 11:40:19.198 : #Con#Info  TInfoClientProcessor.NextStep
"""

_OK_BLOCK = """\
17/05 09:30:01.001 : #Con#Info  TInfoClientProcessor.ProcessLoginResult:
                                  ActivationResult=OK
                                  Mensagem="Login realizado com sucesso"
                                  HardLogout=False
                                  LoginResult=OK
17/05 09:30:01.002 : #Con#Info  TInfoClientProcessor.NextStep
"""


def _write_log(tmp_path: Path, content: str, *, name: str = "LogDesktop_2026_05_17.log") -> Path:
    """Helper — escreve um log fictício em ``tmp_path``."""
    log_path = tmp_path / name
    log_path.write_text(content, encoding="utf-8")
    return log_path


# =====================================================================
# AC7 — 5 tests
# =====================================================================


def test_parse_max_hid_block_returns_populated_snapshot(tmp_path: Path) -> None:
    """AC7 #1 — bloco MaxHID isolado é parseado nos 4 campos canônicos."""
    _write_log(tmp_path, _MAX_HID_BLOCK)

    snapshot = parse_login_result_from_log(tmp_path, year_hint=2026)

    assert snapshot is not None
    assert isinstance(snapshot, LoginResultSnapshot)
    assert snapshot.activation_result == "MaxHID"
    assert snapshot.message == "Todos os seus logins estão em uso"
    assert snapshot.hard_logout is True
    assert snapshot.login_result == "MaxHID"
    assert snapshot.timestamp == datetime(2026, 5, 17, 11, 40, 19, 197_000)


def test_parse_multiple_blocks_returns_most_recent(tmp_path: Path) -> None:
    """AC7 #2 — log com múltiplos blocos retorna o último (autoritativo)."""
    # OK primeiro (login da sessão prévia), depois MaxHID (sessão atual).
    content = _OK_BLOCK + _MAX_HID_BLOCK
    _write_log(tmp_path, content)

    snapshot = parse_login_result_from_log(tmp_path, year_hint=2026)

    assert snapshot is not None
    # O último (MaxHID) deve vencer — sessão atual é a única que importa.
    assert snapshot.activation_result == "MaxHID"
    assert snapshot.timestamp == datetime(2026, 5, 17, 11, 40, 19, 197_000)


def test_missing_log_directory_returns_none(tmp_path: Path) -> None:
    """AC7 #3 — pasta inexistente retorna ``None`` sem levantar."""
    nonexistent = tmp_path / "no-such-dir"
    assert not nonexistent.exists()

    snapshot = parse_login_result_from_log(nonexistent)

    assert snapshot is None


def test_truncated_log_returns_none_or_graceful_partial(tmp_path: Path) -> None:
    """AC7 #4 — log com bloco truncado (sem atributos) retorna ``None``.

    Cenário: DLL crashou no meio da escrita; cabeçalho presente mas atributos
    não foram flushados ainda. Caller cai no path legacy (timeout genérico).
    """
    truncated = "17/05 11:40:19.197 : #Con#Info  TInfoClientProcessor.ProcessLoginResult:\n"
    _write_log(tmp_path, truncated)

    snapshot = parse_login_result_from_log(tmp_path, year_hint=2026)

    # Sem atributos válidos após o cabeçalho → tratamos como log inválido.
    assert snapshot is None


def test_parse_ok_block_returns_non_maxhid_snapshot(tmp_path: Path) -> None:
    """AC7 #5 — bloco com ``ActivationResult=OK`` retorna snapshot válido.

    Caller compara ``snapshot.activation_result == "MaxHID"`` antes de
    raise; ``OK`` passa direto (fluxo normal de login bem-sucedido).
    """
    _write_log(tmp_path, _OK_BLOCK)

    snapshot = parse_login_result_from_log(tmp_path, year_hint=2026)

    assert snapshot is not None
    assert snapshot.activation_result == "OK"
    assert snapshot.message == "Login realizado com sucesso"
    assert snapshot.hard_logout is False
    assert snapshot.login_result == "OK"


# =====================================================================
# Cobertura extra — bordas defensivas (R3 amended Story 4.29)
# =====================================================================


def test_empty_logs_dir_returns_none(tmp_path: Path) -> None:
    """Pasta existe mas sem nenhum ``LogDesktop_*.log``."""
    # tmp_path existe (criado pelo pytest fixture) mas sem arquivos.
    snapshot = parse_login_result_from_log(tmp_path)
    assert snapshot is None


def test_logs_dir_with_unrelated_files_returns_none(tmp_path: Path) -> None:
    """Arquivos com nomes não-canônicos são ignorados pelo localizador."""
    (tmp_path / "Some.txt").write_text("not a log", encoding="utf-8")
    (tmp_path / "LogDesktop-old.log").write_text("malformed name", encoding="utf-8")

    snapshot = parse_login_result_from_log(tmp_path)
    assert snapshot is None


def test_find_latest_log_desktop_picks_most_recent_date(tmp_path: Path) -> None:
    """Múltiplos LogDesktop com datas diferentes → mais recente vence."""
    older = tmp_path / "LogDesktop_2026_05_16.log"
    newer = tmp_path / "LogDesktop_2026_05_17.log"
    older.write_text("placeholder", encoding="utf-8")
    newer.write_text("placeholder", encoding="utf-8")

    found = find_latest_log_desktop(tmp_path)

    assert found == newer


def test_parse_handles_invalid_utf8_bytes(tmp_path: Path) -> None:
    """Race com DLL escrevendo bytes parciais — encoding errors='ignore' garante
    que o parser não levanta ``UnicodeDecodeError`` em meio a corrupção."""
    log_path = tmp_path / "LogDesktop_2026_05_17.log"
    # Bytes inválidos seguidos do bloco MaxHID — simula write-mid-buffer da DLL.
    payload = b"\xff\xfe\x80\x81" + _MAX_HID_BLOCK.encode("utf-8")
    log_path.write_bytes(payload)

    snapshot = parse_login_result_from_log(tmp_path, year_hint=2026)

    assert snapshot is not None
    assert snapshot.activation_result == "MaxHID"


def test_parse_skips_blocks_before_unrelated_events(tmp_path: Path) -> None:
    """Eventos não-``ProcessLoginResult`` entre cabeçalho e atributos quebram
    o parse de atributos no ponto exato — defensivo para releases futuras."""
    # Linha 2 não bate atributo indentado (próximo evento iniciou) — sem
    # atributos capturados após o cabeçalho → snapshot inválido.
    content = (
        "17/05 11:40:19.197 : #Con#Info  TInfoClientProcessor.ProcessLoginResult:\n"
        "17/05 11:40:19.198 : #Con#Info  TInfoClientProcessor.NextStep\n"
    )
    _write_log(tmp_path, content)

    snapshot = parse_login_result_from_log(tmp_path, year_hint=2026)

    # Cabeçalho presente mas sem atributos válidos → None.
    assert snapshot is None


@pytest.mark.parametrize(
    ("hard_logout_raw", "expected"),
    [
        ("True", True),
        ("true", True),
        ("False", False),
        ("false", False),
        ("", False),
    ],
)
def test_hard_logout_parses_truthy_and_falsy_variants(
    tmp_path: Path,
    hard_logout_raw: str,
    expected: bool,
) -> None:
    """``HardLogout`` aceita ``True``/``true``/``False``/``false``/ausente."""
    content = (
        "17/05 11:40:19.197 : #Con#Info  TInfoClientProcessor.ProcessLoginResult:\n"
        "                                  ActivationResult=MaxHID\n"
        f"                                  HardLogout={hard_logout_raw}\n"
    )
    _write_log(tmp_path, content)

    snapshot = parse_login_result_from_log(tmp_path, year_hint=2026)

    assert snapshot is not None
    assert snapshot.hard_logout is expected
