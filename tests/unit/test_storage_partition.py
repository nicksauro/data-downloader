"""Unit tests — storage.partition (Story 1.4).

Cobertura:

- ``PartitionKey`` valida exchange, year, month no ``__post_init__``.
- ``resolve_partition_path`` produz path correto (ADR-004).
- ``parse_partition_path`` é inverso de ``resolve_partition_path``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from data_downloader.storage.partition import (
    PartitionKey,
    parse_partition_path,
    resolve_partition_path,
)


@pytest.mark.unit
def test_partition_key_accepts_valid() -> None:
    """Construção válida não levanta."""
    key = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=3)
    assert key.exchange == "F"
    assert key.symbol == "WDOJ26"
    assert key.year == 2026
    assert key.month == 3


@pytest.mark.unit
@pytest.mark.parametrize("bad_exchange", ["X", "", "FF", "f", "BB", "1"])
def test_partition_key_rejects_invalid_exchange(bad_exchange: str) -> None:
    with pytest.raises(ValueError, match="exchange"):
        PartitionKey(exchange=bad_exchange, symbol="WDOJ26", year=2026, month=3)


@pytest.mark.unit
def test_partition_key_rejects_empty_symbol() -> None:
    with pytest.raises(ValueError, match="symbol"):
        PartitionKey(exchange="F", symbol="", year=2026, month=3)


@pytest.mark.unit
@pytest.mark.parametrize("bad_year", [1999, 1900, 0, -1])
def test_partition_key_rejects_old_year(bad_year: int) -> None:
    with pytest.raises(ValueError, match="year"):
        PartitionKey(exchange="F", symbol="WDOJ26", year=bad_year, month=3)


@pytest.mark.unit
@pytest.mark.parametrize("bad_month", [0, 13, -1, 100])
def test_partition_key_rejects_invalid_month(bad_month: int) -> None:
    with pytest.raises(ValueError, match="month"):
        PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=bad_month)


@pytest.mark.unit
def test_partition_key_is_hashable() -> None:
    """``frozen=True`` garante hashable -> uso direto em dict."""
    a = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=3)
    b = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=3)
    assert hash(a) == hash(b)
    d = {a: "x"}
    assert d[b] == "x"


@pytest.mark.unit
def test_resolve_partition_path_canonical() -> None:
    """ADR-004: ``data/history/{exchange}/{symbol}/{year}/{month:02d}.parquet``."""
    key = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=3)
    path = resolve_partition_path(key, Path("data"))
    expected = Path("data") / "history" / "F" / "WDOJ26" / "2026" / "03.parquet"
    assert path == expected


@pytest.mark.unit
def test_resolve_partition_path_pads_month() -> None:
    """Mês de 1 dígito é zero-padded."""
    key = PartitionKey(exchange="B", symbol="PETR4", year=2025, month=1)
    path = resolve_partition_path(key, Path("data"))
    assert path.name == "01.parquet"
    assert "PETR4" in path.parts
    assert "2025" in path.parts
    assert "B" in path.parts


@pytest.mark.unit
def test_parse_partition_path_round_trip() -> None:
    """``parse(resolve(k)) == k`` para todas as chaves canônicas."""
    cases = [
        PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=3),
        PartitionKey(exchange="F", symbol="WDOH26", year=2025, month=12),
        PartitionKey(exchange="B", symbol="PETR4", year=2024, month=1),
    ]
    for key in cases:
        path = resolve_partition_path(key, Path("data"))
        parsed = parse_partition_path(path)
        assert parsed == key, f"round-trip failed for {key}"


@pytest.mark.unit
def test_parse_partition_path_returns_none_on_invalid() -> None:
    """Paths que não batem com layout retornam None (não levantam)."""
    assert parse_partition_path(Path("foo/bar.parquet")) is None
    assert parse_partition_path(Path("data/other/F/WDO/2026/03.parquet")) is None
    assert parse_partition_path(Path("data/history/F/WDO/2026/03.csv")) is None


@pytest.mark.unit
def test_parse_partition_path_returns_none_on_invalid_exchange() -> None:
    """Path bem formado mas exchange inválido -> None (validação PartitionKey)."""
    assert parse_partition_path(Path("data/history/X/WDO/2026/03.parquet")) is None
