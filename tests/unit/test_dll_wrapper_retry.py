"""tests/unit/test_dll_wrapper_retry.py — Story 2.12.

Cobertura de :meth:`data_downloader.dll.wrapper.ProfitDLL.wait_market_connected`
com retry policy (Q-DRIFT-02 flakiness mitigation).

Cenários:

- Test 1: 1ª tentativa PASS — retry_attempts=3 mas só rodou 1 (sem cooldown).
- Test 2: 2ª tentativa PASS — primeira deu timeout, segunda OK (1 cooldown).
- Test 3: 3 tentativas FAIL — esgotou, retorna False.
- Test 4: drain entre tentativas — eventos antigos não confundem retry.
- Test 5: cooldown respeitado entre tentativas (mock time.sleep).
- Test 6: validação de args (retry_attempts >= 1, retry_cooldown >= 0).
- Test 7: retry_attempts=1 → comportamento legado (1 tentativa só, sem sleep).
"""

from __future__ import annotations

from pathlib import Path
from queue import Queue
from typing import Any

import pytest

from data_downloader.dll import callbacks as cb_module
from data_downloader.dll import wrapper as wrapper_module
from data_downloader.dll.types import (
    LOGIN,
    MARKET_CONNECTED,
    MARKET_DATA,
    MARKET_WAITING,
    ROTEAMENTO,
)
from data_downloader.dll.wrapper import ProfitDLL


@pytest.fixture(autouse=True)
def _isolate_cb_refs() -> Any:
    """Isola ``_cb_refs`` entre testes."""
    cb_module.cleanup_cb_refs()
    yield
    cb_module.cleanup_cb_refs()


@pytest.fixture
def captured_sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Captura chamadas a ``time.sleep`` no módulo wrapper.

    Substitui :func:`time.sleep` por um stub que só registra a duração —
    testes determinísticos sem perda de tempo real.
    """
    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(wrapper_module.time, "sleep", fake_sleep)
    return sleeps


def _seed(dll: ProfitDLL, pairs: list[tuple[int, int]]) -> None:
    for p in pairs:
        dll._state_queue.put(p)


# =====================================================================
# Test 1 — primeira tentativa OK (retry_attempts=3 mas só 1 roda)
# =====================================================================


@pytest.mark.unit
def test_first_attempt_succeeds_no_cooldown(
    captured_sleeps: list[float],
) -> None:
    """1ª tentativa PASS — não chama time.sleep, não loga retry."""
    dll = ProfitDLL(dll_path=Path("/fake.dll"))
    _seed(
        dll,
        [
            (LOGIN, 0),
            (ROTEAMENTO, 2),
            (MARKET_DATA, MARKET_CONNECTED),
        ],
    )

    result = dll.wait_market_connected(
        timeout=5,
        retry_attempts=3,
        retry_cooldown=30.0,
    )

    assert result is True
    # Cooldown só ocorre ENTRE tentativas — 1ª passou, sem sleep.
    assert captured_sleeps == []


# =====================================================================
# Test 2 — segunda tentativa OK (1ª timeout, 2ª connected)
# =====================================================================


@pytest.mark.unit
def test_second_attempt_succeeds_one_cooldown(
    captured_sleeps: list[float],
) -> None:
    """1ª tentativa timeout (queue só com states intermediários), 2ª OK.

    Simula flakiness Q-DRIFT-02: 1ª rodada vê apenas LOGIN+ROTEAMENTO sem
    MARKET_CONNECTED → timeout 1s. Drain limpa fila. 2ª rodada (após
    cooldown) recebe (MARKET_DATA, 4) → True.
    """

    class TwoPhaseQueue:
        """Queue que simula 2 fases: 1ª sem MARKET_CONNECTED, 2ª com.

        Após o drain entre tentativas, novos eventos são "enviados" pela
        DLL — implementado via ``_drain_state_queue`` que esvazia, então
        seedamos a fila novamente.
        """

    dll = ProfitDLL(dll_path=Path("/fake.dll"))
    # Primeira tentativa: apenas estados intermediários — não conecta.
    _seed(dll, [(LOGIN, 0), (ROTEAMENTO, 2)])

    # Hook: quando _drain_state_queue for chamado, repopular para 2ª rodada.
    original_drain = dll._drain_state_queue
    rounds: list[int] = [0]

    def drain_and_reseed() -> int:
        n: int = original_drain()
        rounds[0] += 1
        if rounds[0] == 1:
            # Após drain da 1ª falha, simulamos que a DLL agora envia
            # o handshake completo na 2ª tentativa.
            for p in [(LOGIN, 0), (ROTEAMENTO, 2), (MARKET_DATA, MARKET_CONNECTED)]:
                dll._state_queue.put(p)
        return n

    dll._drain_state_queue = drain_and_reseed

    result = dll.wait_market_connected(
        timeout=1,
        retry_attempts=3,
        retry_cooldown=30.0,
    )

    assert result is True
    # 1 cooldown entre 1ª e 2ª tentativas.
    assert captured_sleeps == [30.0]


# =====================================================================
# Test 3 — 3 tentativas FAIL → retorna False
# =====================================================================


@pytest.mark.unit
def test_all_attempts_fail_returns_false(
    captured_sleeps: list[float],
) -> None:
    """Esgotou retry_attempts=3 sem sucesso → retorna False (sem raise).

    2 cooldowns entre as 3 tentativas (cooldown só ENTRE attempts, não
    após a última).
    """
    dll = ProfitDLL(dll_path=Path("/fake.dll"))
    # Queue vazia — todos timeouts.

    result = dll.wait_market_connected(
        timeout=1,
        retry_attempts=3,
        retry_cooldown=15.0,
    )

    assert result is False
    # 2 cooldowns: depois da 1ª falha, depois da 2ª falha. Nenhum após a 3ª.
    assert captured_sleeps == [15.0, 15.0]


# =====================================================================
# Test 4 — drain entre tentativas remove eventos antigos
# =====================================================================


@pytest.mark.unit
def test_drain_state_queue_between_attempts(
    captured_sleeps: list[float],
) -> None:
    """Após 1ª tentativa falhar, eventos antigos são drenados.

    Sem o drain, eventos LOGIN/ROTEAMENTO da 1ª rodada permaneceriam na
    fila, e a 2ª rodada os consumiria sem MARKET_CONNECTED → falha
    espúria. Drain garante reset limpo.
    """
    dll = ProfitDLL(dll_path=Path("/fake.dll"))
    # 1ª rodada vê só MARKET_WAITING (não conecta) — depois nada.
    _seed(
        dll,
        [
            (LOGIN, 0),
            (ROTEAMENTO, 2),
            (MARKET_DATA, MARKET_WAITING),  # =2, NÃO connected
        ],
    )

    result = dll.wait_market_connected(
        timeout=1,
        retry_attempts=2,
        retry_cooldown=5.0,
    )

    assert result is False
    # Após esgotar tentativas, fila DEVE estar vazia (drain entre 1 e 2).
    assert dll._state_queue.empty()
    # 1 cooldown entre 1ª e 2ª.
    assert captured_sleeps == [5.0]


@pytest.mark.unit
def test_drain_state_queue_returns_count() -> None:
    """:meth:`_drain_state_queue` retorna número de eventos descartados."""
    dll = ProfitDLL(dll_path=Path("/fake.dll"))
    _seed(dll, [(LOGIN, 0), (ROTEAMENTO, 2), (MARKET_DATA, MARKET_WAITING)])

    n = dll._drain_state_queue()

    assert n == 3
    assert dll._state_queue.empty()


@pytest.mark.unit
def test_drain_state_queue_empty_returns_zero() -> None:
    """Drain de fila vazia retorna 0 sem bloquear."""
    dll = ProfitDLL(dll_path=Path("/fake.dll"))
    n = dll._drain_state_queue()
    assert n == 0


# =====================================================================
# Test 5 — cooldown respeitado entre tentativas
# =====================================================================


@pytest.mark.unit
def test_cooldown_respected_between_attempts(
    captured_sleeps: list[float],
) -> None:
    """Cooldown configurado é passado a time.sleep entre tentativas."""
    dll = ProfitDLL(dll_path=Path("/fake.dll"))
    # 4 tentativas, todas falham (queue vazia) → 3 cooldowns.

    result = dll.wait_market_connected(
        timeout=1,
        retry_attempts=4,
        retry_cooldown=42.5,
    )

    assert result is False
    # 3 cooldowns iguais entre 4 tentativas.
    assert captured_sleeps == [42.5, 42.5, 42.5]


@pytest.mark.unit
def test_cooldown_zero_skips_sleep(
    captured_sleeps: list[float],
) -> None:
    """``retry_cooldown=0`` não chama time.sleep (otimização)."""
    dll = ProfitDLL(dll_path=Path("/fake.dll"))
    # 2 tentativas, ambas falham. Sem cooldown.

    result = dll.wait_market_connected(
        timeout=1,
        retry_attempts=2,
        retry_cooldown=0.0,
    )

    assert result is False
    assert captured_sleeps == []


# =====================================================================
# Test 6 — validação de args
# =====================================================================


@pytest.mark.unit
def test_retry_attempts_must_be_positive() -> None:
    """retry_attempts < 1 → ValueError (defesa contra config absurda)."""
    dll = ProfitDLL(dll_path=Path("/fake.dll"))
    with pytest.raises(ValueError, match="retry_attempts must be >= 1"):
        dll.wait_market_connected(timeout=1, retry_attempts=0)


@pytest.mark.unit
def test_retry_cooldown_must_be_non_negative() -> None:
    """retry_cooldown < 0 → ValueError."""
    dll = ProfitDLL(dll_path=Path("/fake.dll"))
    with pytest.raises(ValueError, match="retry_cooldown must be >= 0"):
        dll.wait_market_connected(timeout=1, retry_cooldown=-1.0)


# =====================================================================
# Test 7 — retry_attempts=1 (comportamento legado)
# =====================================================================


@pytest.mark.unit
def test_retry_attempts_one_legacy_behavior(
    captured_sleeps: list[float],
) -> None:
    """retry_attempts=1 → 1 tentativa só, sem sleep, mesmo comportamento
    pré-Story 2.12."""
    dll = ProfitDLL(dll_path=Path("/fake.dll"))
    _seed(dll, [(MARKET_DATA, MARKET_CONNECTED)])

    result = dll.wait_market_connected(
        timeout=5,
        retry_attempts=1,
        retry_cooldown=30.0,
    )

    assert result is True
    assert captured_sleeps == []


@pytest.mark.unit
def test_retry_attempts_one_failure_no_cooldown(
    captured_sleeps: list[float],
) -> None:
    """retry_attempts=1 + falha → retorna False sem cooldown (não há próxima)."""
    dll = ProfitDLL(dll_path=Path("/fake.dll"))
    # Queue vazia → timeout.

    result = dll.wait_market_connected(
        timeout=1,
        retry_attempts=1,
        retry_cooldown=30.0,
    )

    assert result is False
    # Última tentativa nunca dorme.
    assert captured_sleeps == []


# =====================================================================
# Smoke test do default kwargs (sanity)
# =====================================================================


@pytest.mark.unit
def test_default_retry_attempts_and_cooldown() -> None:
    """Defaults Story 2.12: retry_attempts=3, retry_cooldown=30.0.

    Confirma que assinatura pública não regrediu — kwargs com defaults
    documentados na docstring.
    """
    import inspect

    sig = inspect.signature(ProfitDLL.wait_market_connected)
    assert sig.parameters["retry_attempts"].default == 3
    assert sig.parameters["retry_cooldown"].default == 30.0
    assert sig.parameters["timeout"].default == 300


# =====================================================================
# Test 8 — explicit drain via Queue helper test
# =====================================================================


@pytest.mark.unit
def test_drain_uses_state_queue_directly() -> None:
    """Drain usa apenas a Queue interna — não interfere em _cb_refs."""
    dll = ProfitDLL(dll_path=Path("/fake.dll"))
    initial_refs = list(dll._cb_refs)
    dll._state_queue = Queue(maxsize=10)
    dll._state_queue.put((LOGIN, 0))

    n = dll._drain_state_queue()

    assert n == 1
    # _cb_refs intocado (anti-GC preservation, R3).
    assert dll._cb_refs == initial_refs
