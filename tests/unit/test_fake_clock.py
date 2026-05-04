"""tests/unit/test_fake_clock.py — Meta-test de :class:`FakeClock`.

Story 2.10 / ADR-014. Garante que o relógio:

- É monotônico (advance(s>=0)) — INV-time-monotonic.
- É exato em ns (sem drift float — 1M advances de 0.000001 → 1.0s).
- Suporta freeze/thaw idempotente.
- Patcheia ``time.time`` + ``time.perf_counter`` quando ativo no
  context manager — 100% determinístico (Aria).
- Suporta uso paralelo: 2 instâncias isoladas, sem state compartilhado.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest

from data_downloader.testing.fake_clock import FakeClock, freeze_at, make_clock_at


@pytest.mark.unit
def test_fake_clock_starts_at_zero_by_default() -> None:
    """Construtor sem args → tempo 0.0 (delta-only mode)."""
    clock = FakeClock()
    assert clock.now() == 0.0
    assert clock.now_ns() == 0


@pytest.mark.unit
def test_fake_clock_starts_at_seconds() -> None:
    """start_seconds preserva valor exato."""
    clock = FakeClock(start_seconds=1_700_000_000.5)
    assert clock.now() == pytest.approx(1_700_000_000.5)


@pytest.mark.unit
def test_fake_clock_starts_at_datetime_aware() -> None:
    """start_datetime aceita datetime aware (UTC)."""
    when = datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC)
    clock = FakeClock(start_datetime=when)
    assert clock.now() == pytest.approx(when.timestamp())


@pytest.mark.unit
def test_fake_clock_naive_datetime_raises() -> None:
    """Naive datetime sem tzinfo → ValueError (R5/no surprises)."""
    with pytest.raises(ValueError, match="timezone-aware"):
        FakeClock(start_datetime=datetime(2026, 5, 3, 12, 0, 0))


@pytest.mark.unit
def test_advance_one_hundred_seconds_exact() -> None:
    """100 advance(1.0) → start + 100 exato (sem float drift)."""
    clock = FakeClock(start_seconds=10.0)
    for _ in range(100):
        clock.advance(1.0)
    assert clock.now() == 110.0


@pytest.mark.unit
def test_advance_million_microseconds_exact_one_second() -> None:
    """1M advance(0.000001) deve totalizar 1s exato (sem drift)."""
    clock = FakeClock(start_seconds=0.0)
    for _ in range(1_000_000):
        clock.advance_ns(1_000)  # 1us em ns
    assert clock.now_ns() == 1_000_000_000  # 1s
    assert clock.now() == 1.0


@pytest.mark.unit
def test_advance_negative_raises() -> None:
    """advance(s < 0) → ValueError (relógio é monotônico)."""
    clock = FakeClock()
    with pytest.raises(ValueError, match="seconds >= 0"):
        clock.advance(-0.001)
    with pytest.raises(ValueError, match="nanoseconds >= 0"):
        clock.advance_ns(-1)


@pytest.mark.unit
def test_advance_zero_is_idempotent() -> None:
    """advance(0) é no-op (idempotente)."""
    clock = FakeClock(start_seconds=5.0)
    before = clock.now()
    clock.advance(0)
    clock.advance(0)
    assert clock.now() == before


@pytest.mark.unit
def test_freeze_blocks_advance() -> None:
    """advance() vira no-op enquanto frozen; thaw reativa."""
    clock = FakeClock()
    clock.advance(1.0)
    clock.freeze()
    assert clock.frozen
    clock.advance(10.0)
    clock.advance(100.0)
    assert clock.now() == 1.0
    clock.thaw()
    assert not clock.frozen
    clock.advance(2.0)
    assert clock.now() == 3.0


@pytest.mark.unit
def test_now_datetime_returns_aware_utc_default() -> None:
    """now_datetime() default → datetime UTC aware."""
    clock = FakeClock(start_datetime=datetime(2026, 1, 1, tzinfo=UTC))
    dt = clock.now_datetime()
    assert dt.tzinfo == UTC
    assert dt.year == 2026


@pytest.mark.unit
def test_sleep_advances_without_blocking() -> None:
    """sleep(N) avança o relógio sem bloquear o thread real."""
    clock = FakeClock()
    real_start = time.perf_counter()
    clock.sleep(60.0)  # 60s "virtual"
    real_elapsed = time.perf_counter() - real_start
    assert clock.now() == 60.0
    # Tempo real gasto deve ser <<< 1s (sem time.sleep real).
    assert real_elapsed < 0.5


@pytest.mark.unit
def test_patch_time_intercepts_time_module() -> None:
    """patch_time patcheia time.time e time.perf_counter dentro do with."""
    clock = FakeClock(start_seconds=42.0)
    with clock.patch_time():
        assert time.time() == 42.0
        assert time.perf_counter() == 42.0
        clock.advance(8.0)
        assert time.time() == 50.0
        assert time.perf_counter() == 50.0
    # Fora do with, time.time é o real → certamente != 50.0.
    assert time.time() != 50.0


@pytest.mark.unit
def test_patched_factory_creates_and_patches() -> None:
    """FakeClock.patched(...) é açúcar para criar + patch_time."""
    with FakeClock.patched(start_seconds=100.0) as clock:
        assert isinstance(clock, FakeClock)
        assert time.time() == 100.0
        clock.advance(5.0)
        assert time.time() == 105.0


@pytest.mark.unit
def test_two_clocks_isolated() -> None:
    """2 FakeClocks em paralelo: avanço em um não afeta o outro."""
    a = FakeClock(start_seconds=0.0)
    b = FakeClock(start_seconds=100.0)
    a.advance(50.0)
    assert a.now() == 50.0
    assert b.now() == 100.0
    b.advance(7.0)
    assert b.now() == 107.0
    assert a.now() == 50.0  # inalterado


@pytest.mark.unit
def test_freeze_at_helper_returns_frozen_clock() -> None:
    """freeze_at(when) retorna clock frozen no instante dado."""
    when = datetime(2026, 5, 3, tzinfo=UTC)
    clock = freeze_at(when)
    assert clock.frozen
    snapshot = clock.now()
    clock.advance(1000.0)  # ignorado — frozen
    assert clock.now() == snapshot


@pytest.mark.unit
def test_make_clock_at_helper() -> None:
    """make_clock_at(YYYY, MM, DD) retorna clock em meia-noite UTC."""
    clock = make_clock_at(2026, 5, 3)
    dt = clock.now_datetime()
    assert dt.year == 2026
    assert dt.month == 5
    assert dt.day == 3
    assert dt.hour == 0
    assert dt.tzinfo == UTC


@pytest.mark.unit
def test_perf_counter_and_now_match_for_deterministic_clock() -> None:
    """Para FakeClock, perf_counter() == now() (testes determinísticos)."""
    clock = FakeClock(start_seconds=10.0)
    assert clock.perf_counter() == clock.now()
    clock.advance(3.0)
    assert clock.perf_counter() == clock.now() == 13.0


@pytest.mark.unit
def test_thread_safety_concurrent_advances() -> None:
    """Múltiplas threads avançando concorrentemente — total exato."""
    import threading

    clock = FakeClock()
    n_threads = 4
    advances_per_thread = 250

    def worker() -> None:
        for _ in range(advances_per_thread):
            clock.advance_ns(1_000_000)  # 1ms em ns

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    expected_ns = n_threads * advances_per_thread * 1_000_000
    assert clock.now_ns() == expected_ns
