"""Integration tests para detecção proativa de MaxHID — Story 4.29 AC3+AC8.

Verifica que :meth:`ProfitDLL._wait_market_connected_once` levanta
:class:`MaxHIDError` rapidamente (sem esperar timeout completo) quando o
``LogDesktop_YYYY_MM_DD.log`` contém ``ActivationResult=MaxHID``, e que
o fluxo normal (login OK) não é afetado.

Cenários cobertos (AC8 — 2 mínimos):

1. Log com MaxHID + state_queue sem ``MARKET_CONNECTED`` → raise
   ``MaxHIDError`` em <3s (poll a cada 2s; primeiro check 1s pós-start).
2. Log com login OK + state_queue com ``MARKET_CONNECTED`` → fluxo normal,
   sem raise, retorna ``True``.

Tests adicionais (defensivos):

3. Sem LogDesktop (dir vazio) + state com ``MARKET_CONNECTED`` → fluxo
   normal, sem raise. Garante que ausência de log não derruba caminho de
   sucesso.
4. Log com MaxHID escrito tardiamente (DLL flush atrasado) → ainda detectado
   dentro da janela de 30s.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path

import pytest

from data_downloader.dll.types import MARKET_CONNECTED, MARKET_DATA
from data_downloader.dll.wrapper import ProfitDLL
from data_downloader.public_api.exceptions import MaxHIDError

# =====================================================================
# Fixtures de log — formato canônico (LogDesktop_2026_05_17.log)
# =====================================================================

_MAX_HID_LOG = """\
17/05 11:40:19.197 : #Con#Info  TInfoClientProcessor.ProcessLoginResult:
                                  ActivationResult=MaxHID
                                  Mensagem="Todos os seus logins estão em uso"
                                  HardLogout=True
                                  LoginResult=MaxHID
"""

_OK_LOG = """\
17/05 09:30:01.001 : #Con#Info  TInfoClientProcessor.ProcessLoginResult:
                                  ActivationResult=OK
                                  Mensagem="Login realizado com sucesso"
                                  HardLogout=False
                                  LoginResult=OK
"""


# =====================================================================
# Helpers
# =====================================================================


def _build_dll_for_logs(tmp_path: Path) -> ProfitDLL:
    """Instancia ProfitDLL com ``dll_path`` apontando para ``tmp_path``.

    Não chama ``initialize_market_only`` (não carrega DLL nativa — testes
    rodam sem Windows). ``_wait_market_connected_once`` só consome
    ``self._state_queue`` e ``self._dll_path.parent / "Logs"`` — basta
    isso para o teste exercer o path de detecção.
    """
    # Aceita Path inexistente — ProfitDLL.__init__ não valida no constructor;
    # só ``initialize_market_only`` chama ``WinDLL(...)``. Path fictício é
    # suficiente porque o teste exerce só ``_wait_market_connected_once``.
    fake_dll = tmp_path / "FakeProfitDLL.dll"
    fake_dll.touch()
    return ProfitDLL(dll_path=fake_dll)


def _write_logdesktop(tmp_path: Path, content: str) -> Path:
    """Cria ``<tmp_path>/Logs/LogDesktop_2026_05_17.log`` com ``content``."""
    logs_dir = tmp_path / "Logs"
    logs_dir.mkdir(exist_ok=True)
    log_path = logs_dir / "LogDesktop_2026_05_17.log"
    log_path.write_text(content, encoding="utf-8")
    return log_path


# =====================================================================
# AC8 — 2 cenários mínimos
# =====================================================================


def test_maxhid_log_raises_quickly_without_market_connected(tmp_path: Path) -> None:
    """AC8 #1 — log com MaxHID + sem ``MARKET_CONNECTED`` no queue →
    ``MaxHIDError`` em <3s (poll inicial 1s + 2s interval).
    """
    dll = _build_dll_for_logs(tmp_path)
    _write_logdesktop(tmp_path, _MAX_HID_LOG)

    # Timeout 10s — mais que suficiente para o poll detectar (<3s real);
    # mas pequeno o bastante para falhar rápido se a detecção quebrar.
    start = time.monotonic()
    with pytest.raises(MaxHIDError) as exc_info:
        dll._wait_market_connected_once(timeout=10)
    elapsed = time.monotonic() - start

    # Detecção deve ser rápida — primeiro poll é em 1s, segundo em 3s.
    # Conservador: <5s cobre folga para CI lento sem tornar o teste lento.
    assert elapsed < 5.0, (
        f"MaxHID detection took {elapsed:.2f}s, expected <5s (poll grace=1s, interval=2s)"
    )

    # Atributos da exception preservam evidência do servidor.
    exc = exc_info.value
    assert exc.activation_result == "MaxHID"
    assert exc.server_message == "Todos os seus logins estão em uso"
    assert exc.timestamp is not None
    assert exc.humanized_message == "ERR_DLL_MAX_HID"


def test_login_ok_does_not_trigger_maxhid_detection(tmp_path: Path) -> None:
    """AC8 #2 — log com OK + ``MARKET_CONNECTED`` no queue → fluxo normal,
    retorna ``True`` sem raise (não-regressão para usuários sem MaxHID).
    """
    dll = _build_dll_for_logs(tmp_path)
    _write_logdesktop(tmp_path, _OK_LOG)

    # Empurra o estado autoritativo logo após start — wait deve detectar
    # antes de o primeiro poll de MaxHID acontecer (poll começa em 1s).
    dll._state_queue.put((MARKET_DATA, MARKET_CONNECTED))

    connected = dll._wait_market_connected_once(timeout=10)

    assert connected is True


# =====================================================================
# Cobertura defensiva — bordas do fluxo
# =====================================================================


def test_no_logdesktop_does_not_break_normal_flow(tmp_path: Path) -> None:
    """Pasta Logs ausente (primeiro run, dev sem DLL) — caminho de sucesso
    não é quebrado: parse retorna None, wait segue normal.
    """
    dll = _build_dll_for_logs(tmp_path)
    # Sem _write_logdesktop — Logs/ dir não existe.
    dll._state_queue.put((MARKET_DATA, MARKET_CONNECTED))

    connected = dll._wait_market_connected_once(timeout=10)

    assert connected is True


def test_maxhid_log_written_late_still_detected(tmp_path: Path) -> None:
    """DLL pode flushar o log com atraso (~5s pós-login). O loop de polling
    cobre janela de 30s — log escrito em t+3s ainda é detectado.
    """
    dll = _build_dll_for_logs(tmp_path)

    # Thread que escreve o log com delay simulando flush atrasado da DLL.
    def _write_late() -> None:
        time.sleep(3.0)
        _write_logdesktop(tmp_path, _MAX_HID_LOG)

    t = threading.Thread(target=_write_late, daemon=True)
    t.start()
    try:
        start = time.monotonic()
        with pytest.raises(MaxHIDError):
            dll._wait_market_connected_once(timeout=15)
        elapsed = time.monotonic() - start
        # Deve detectar dentro de ~3-7s (write em t+3, próximo poll até +2s).
        assert elapsed < 10.0, f"Late-write MaxHID detection took {elapsed:.2f}s, expected <10s"
    finally:
        t.join(timeout=5)


def test_maxhid_error_timestamp_carries_log_metadata(tmp_path: Path) -> None:
    """Smoke da estrutura da MaxHIDError raised — atributos refletem o log."""
    dll = _build_dll_for_logs(tmp_path)
    _write_logdesktop(tmp_path, _MAX_HID_LOG)

    with pytest.raises(MaxHIDError) as exc_info:
        dll._wait_market_connected_once(timeout=10)

    exc = exc_info.value
    # ``timestamp`` é populado com ano corrente (não 2026 hardcoded — o parser
    # usa ``datetime.now().year`` como default; o ano específico não importa,
    # apenas mês/dia/hora do bloco).
    assert isinstance(exc.timestamp, datetime)
    assert exc.timestamp.month == 5
    assert exc.timestamp.day == 17
    assert exc.timestamp.hour == 11
    assert exc.timestamp.minute == 40
    assert exc.timestamp.second == 19
