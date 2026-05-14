"""Unit tests — catalog partition observer pattern (v1.3.0 Wave 2B).

Owner: Dex (@dev) | Squad: data-downloader.

Cobertura:

- register/unregister são idempotentes.
- ``register_partition`` notifica observers com (symbol, year, month).
- ``record_chunk`` notifica observers (granularidade diária — year/month
  derivados do chunk_date).
- Observer que levanta exceção NÃO derruba o write (best-effort dispatch).
- Múltiplos observers recebem a mesma notificação.
- Unregister durante notificação é seguro (snapshot list).
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from data_downloader.storage.catalog import (
    Catalog,
    register_partition_observer,
    unregister_partition_observer,
)
from data_downloader.storage.parquet_writer import WriteResult
from data_downloader.storage.partition import PartitionKey


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def db_path(data_dir: Path) -> Path:
    return data_dir / "history" / "catalog.db"


@pytest.fixture
def catalog(db_path: Path, data_dir: Path) -> Catalog:
    return Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)


def _fake_partition_file(data_dir: Path, partition: PartitionKey) -> Path:
    p = (
        data_dir
        / "history"
        / partition.exchange
        / partition.symbol
        / f"{partition.year:04d}"
        / f"{partition.month:02d}.parquet"
    )
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"PAR1stub" + b"\x00" * 100)
    return p


def _make_write_result(path: Path, *, row_count: int = 100) -> WriteResult:
    return WriteResult(
        path=path,
        row_count=row_count,
        first_ts_ns=1_700_000_000_000_000_000,
        last_ts_ns=1_700_000_001_000_000_000,
        checksum_sha256="b" * 64,
        file_size_bytes=path.stat().st_size,
    )


@pytest.mark.unit
def test_register_partition_observer_idempotent() -> None:
    """Registrar o mesmo callback 2x = 1 entrada (sem duplicata)."""
    events: list = []

    def cb(symbol: str, year: int, month: int) -> None:
        events.append((symbol, year, month))

    register_partition_observer(cb)
    register_partition_observer(cb)  # re-register = no-op.
    try:
        # Importa lista interna apenas para a asserção.
        from data_downloader.storage import catalog as catmod

        assert catmod._PARTITION_OBSERVERS.count(cb) == 1
    finally:
        unregister_partition_observer(cb)


@pytest.mark.unit
def test_unregister_partition_observer_idempotent() -> None:
    """Unregister de cb não-registrado = no-op silencioso."""

    def cb(symbol: str, year: int, month: int) -> None:
        pass

    # Não está registrado — não deve levantar.
    unregister_partition_observer(cb)

    # Registrar + unregister 2x = limpa, não levanta.
    register_partition_observer(cb)
    unregister_partition_observer(cb)
    unregister_partition_observer(cb)


@pytest.mark.unit
def test_register_partition_notifies_observers(catalog: Catalog, data_dir: Path) -> None:
    """register_partition emite (symbol, year, month) para observers."""
    events: list[tuple[str, int, int]] = []

    def cb(symbol: str, year: int, month: int) -> None:
        events.append((symbol, year, month))

    register_partition_observer(cb)
    try:
        partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=3)
        path = _fake_partition_file(data_dir, partition)
        wr = _make_write_result(path)
        catalog.register_partition(wr, partition)
        assert events == [("WDOJ26", 2026, 3)]
    finally:
        unregister_partition_observer(cb)
        catalog.close()


@pytest.mark.unit
def test_record_chunk_notifies_observers(catalog: Catalog) -> None:
    """record_chunk emite (symbol, year, month) derivados de chunk_date."""
    events: list[tuple[str, int, int]] = []

    def cb(symbol: str, year: int, month: int) -> None:
        events.append((symbol, year, month))

    register_partition_observer(cb)
    try:
        catalog.record_chunk(
            symbol="WDOJ26",
            exchange="F",
            chunk_date=date(2026, 3, 15),
            job_id=None,
            status="completed",
            trades_count=42,
        )
        assert events == [("WDOJ26", 2026, 3)]
    finally:
        unregister_partition_observer(cb)
        catalog.close()


@pytest.mark.unit
def test_observer_exception_does_not_break_write(catalog: Catalog, data_dir: Path) -> None:
    """Observer que levanta exceção NÃO derruba register_partition."""

    def bad_cb(symbol: str, year: int, month: int) -> None:
        raise RuntimeError("observer boom")

    good_events: list = []

    def good_cb(symbol: str, year: int, month: int) -> None:
        good_events.append((symbol, year, month))

    register_partition_observer(bad_cb)
    register_partition_observer(good_cb)
    try:
        partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=4)
        path = _fake_partition_file(data_dir, partition)
        wr = _make_write_result(path)
        # Não deve levantar — observer falho é absorvido.
        catalog.register_partition(wr, partition)
        # Partition foi gravada com sucesso.
        got = catalog.get_completed_partitions("WDOJ26", "F")
        assert len(got) == 1
        # Observer "good" foi chamado mesmo com "bad" falhando.
        assert good_events == [("WDOJ26", 2026, 4)]
    finally:
        unregister_partition_observer(bad_cb)
        unregister_partition_observer(good_cb)
        catalog.close()


@pytest.mark.unit
def test_multiple_observers_all_notified(catalog: Catalog, data_dir: Path) -> None:
    """Todos os observers registrados recebem a notificação."""
    a_events: list = []
    b_events: list = []

    def cb_a(symbol: str, year: int, month: int) -> None:
        a_events.append((symbol, year, month))

    def cb_b(symbol: str, year: int, month: int) -> None:
        b_events.append((symbol, year, month))

    register_partition_observer(cb_a)
    register_partition_observer(cb_b)
    try:
        partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=5)
        path = _fake_partition_file(data_dir, partition)
        wr = _make_write_result(path)
        catalog.register_partition(wr, partition)
        assert a_events == [("WDOJ26", 2026, 5)]
        assert b_events == [("WDOJ26", 2026, 5)]
    finally:
        unregister_partition_observer(cb_a)
        unregister_partition_observer(cb_b)
        catalog.close()


@pytest.mark.unit
def test_unregister_during_notification_is_safe(catalog: Catalog, data_dir: Path) -> None:
    """Observer pode chamar unregister durante notificação sem corromper a lista."""
    events: list = []

    def self_unregistering(symbol: str, year: int, month: int) -> None:
        events.append((symbol, year, month))
        unregister_partition_observer(self_unregistering)

    register_partition_observer(self_unregistering)
    try:
        partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=6)
        path = _fake_partition_file(data_dir, partition)
        wr = _make_write_result(path)
        # Primeira chamada — recebe + se remove.
        catalog.register_partition(wr, partition)
        assert events == [("WDOJ26", 2026, 6)]

        # Segunda chamada — não está mais registrado, não recebe.
        partition2 = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=7)
        path2 = _fake_partition_file(data_dir, partition2)
        wr2 = _make_write_result(path2)
        catalog.register_partition(wr2, partition2)
        assert events == [("WDOJ26", 2026, 6)]  # mesmo conteúdo, não cresceu.
    finally:
        # Defensive cleanup (já removeu mas idempotent).
        unregister_partition_observer(self_unregistering)
        catalog.close()


@pytest.mark.unit
def test_observer_receives_for_each_partition(catalog: Catalog, data_dir: Path) -> None:
    """Observer recebe N notificações para N partições distintas."""
    events: list = []

    def cb(symbol: str, year: int, month: int) -> None:
        events.append((symbol, year, month))

    register_partition_observer(cb)
    try:
        for month in (3, 4, 5):
            partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=month)
            path = _fake_partition_file(data_dir, partition)
            wr = _make_write_result(path)
            catalog.register_partition(wr, partition)
        assert events == [
            ("WDOJ26", 2026, 3),
            ("WDOJ26", 2026, 4),
            ("WDOJ26", 2026, 5),
        ]
    finally:
        unregister_partition_observer(cb)
        catalog.close()


@pytest.mark.unit
def test_record_chunk_no_trades_still_notifies(catalog: Catalog) -> None:
    """record_chunk com status='no_trades' também notifica (Wave 2B)."""
    events: list = []

    def cb(symbol: str, year: int, month: int) -> None:
        events.append((symbol, year, month))

    register_partition_observer(cb)
    try:
        catalog.record_chunk(
            symbol="WDOJ26",
            exchange="F",
            chunk_date=date(2026, 3, 21),
            job_id=None,
            status="no_trades",
        )
        # Granularidade diária — month derivado do chunk_date.
        assert events == [("WDOJ26", 2026, 3)]
    finally:
        unregister_partition_observer(cb)
        catalog.close()


@pytest.mark.unit
def test_observer_is_called_with_correct_types() -> None:
    """Tipos do callback: (str, int, int) — nada de datetime/Path."""
    captured: list = []

    def cb(symbol: str, year: int, month: int) -> None:
        captured.append((type(symbol), type(year), type(month)))

    register_partition_observer(cb)
    try:
        # Notificação direta via API interna — não precisa de Catalog.
        from data_downloader.storage.catalog import _notify_partition_observers

        _notify_partition_observers("WDOJ26", 2026, 3)
        assert captured == [(str, int, int)]
    finally:
        unregister_partition_observer(cb)


# Guarda contra polução cross-test: limpa lista módulo no fim de cada teste
# se algum teste falhar antes do `unregister`.
@pytest.fixture(autouse=True)
def _cleanup_observers():
    from data_downloader.storage import catalog as catmod

    snapshot = list(catmod._PARTITION_OBSERVERS)
    yield
    # Restaura snapshot (remove tudo que foi adicionado durante o teste).
    catmod._PARTITION_OBSERVERS[:] = snapshot


# Mantém referência a datetime para satisfazer ruff (import implícito acima).
_ = datetime
