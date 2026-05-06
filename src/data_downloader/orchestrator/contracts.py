"""data_downloader.orchestrator.contracts — Resolver de contrato vigente.

Owner: Dex (impl) | Consult: Sol (CONTRACTS.md seed) + Nelo (DLL probe).
Story 1.6 — AC2..AC5, AC8, AC9.

Lookup, NÃO cálculo (ADR-006 + Sol):

- ``vigent_contract(catalog, root, on_date)`` consulta a tabela
  ``contracts`` no SQLite catalog e retorna o ``contract_code`` cuja
  janela ``[vigent_from, vigent_until]`` cobre ``on_date``.
- Levanta :class:`~data_downloader.public_api.exceptions.InvalidContract`
  se nenhum contrato vigente — caller decide tratamento (UI / CLI).
- ``populate_contracts_from_seed`` faz UPSERT idempotente do seed YAML
  embutido em ``docs/storage/CONTRACTS.md`` (Sol é dono do seed).

Convenção CME/B3 para letras de mês está mapeada em :data:`MONTH_LETTERS`
e :data:`LETTER_TO_MONTH` — funções :func:`month_letter` /
:func:`month_from_letter` apenas aplicam essas tabelas.

LEIS RESPEITADAS:
- R9 (não chutar contratos): este módulo apenas LE; quem POVOA é o seed
  (Sol) ou o CLI ``contracts add`` (operador) com validação posterior
  via :func:`~data_downloader.orchestrator.contracts_probe.probe_contract`.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

from data_downloader.public_api.exceptions import InvalidContract

if TYPE_CHECKING:
    from data_downloader.storage.catalog import Catalog

__all__ = [
    "DEFAULT_SEED_PATH",
    "LETTER_TO_MONTH",
    "MONTH_LETTERS",
    "Contract",
    "list_contracts",
    "month_from_letter",
    "month_letter",
    "populate_contracts_from_seed",
    "vigent_contract",
]


# =====================================================================
# Letras de mês (CME/B3 convention — CONTRACTS.md §1)
# =====================================================================

MONTH_LETTERS: Final[tuple[str, ...]] = (
    "F",  # 1  Jan
    "G",  # 2  Fev
    "H",  # 3  Mar
    "J",  # 4  Abr
    "K",  # 5  Mai
    "M",  # 6  Jun
    "N",  # 7  Jul
    "Q",  # 8  Ago
    "U",  # 9  Set
    "V",  # 10 Out
    "X",  # 11 Nov
    "Z",  # 12 Dez
)
"""Tupla 1-indexada (via offset -1) das 12 letras de mês CME/B3.

Letras ``I`` e ``L`` são deliberadamente puladas (ambíguas com
algarismos), seguindo convenção CME — ver CONTRACTS.md §1.
"""

LETTER_TO_MONTH: Final[dict[str, int]] = {
    letter: idx + 1 for idx, letter in enumerate(MONTH_LETTERS)
}
"""Mapa inverso: letra → mês (1..12). Construído de :data:`MONTH_LETTERS`."""


def month_letter(month: int) -> str:
    """Letra CME/B3 do mês (1=F, 2=G, ..., 12=Z).

    Args:
        month: Mês no intervalo ``[1, 12]``.

    Returns:
        Letra CME/B3 correspondente — ex.: ``month_letter(4) == "J"``.

    Raises:
        ValueError: ``month`` fora de ``[1, 12]``.

    Ver :data:`MONTH_LETTERS` para a tabela canônica.
    """
    if not 1 <= month <= 12:
        raise ValueError(f"month must be in [1, 12]; got {month}")
    return MONTH_LETTERS[month - 1]


def month_from_letter(letter: str) -> int:
    """Mês (1..12) da letra CME/B3 (inverso de :func:`month_letter`).

    Args:
        letter: Letra CME/B3 (case-insensitive aceito; armazenada como
            uppercase no mapa).

    Returns:
        Mês no intervalo ``[1, 12]``.

    Raises:
        ValueError: ``letter`` não pertence ao alfabeto CME/B3 (incluindo
            ``"I"`` e ``"L"`` que são deliberadamente puladas).
    """
    if not isinstance(letter, str) or len(letter) != 1:
        raise ValueError(f"letter must be single char; got {letter!r}")
    upper = letter.upper()
    if upper not in LETTER_TO_MONTH:
        raise ValueError(
            f"letter {letter!r} is not a valid CME/B3 month letter "
            f"(valid: {sorted(LETTER_TO_MONTH)})"
        )
    return LETTER_TO_MONTH[upper]


# =====================================================================
# Modelo público — Contract dataclass
# =====================================================================


@dataclass(frozen=True)
class Contract:
    """Linha lógica de ``contracts`` (SCHEMA.md §5.5 / CONTRACTS.md §3).

    ``vigent_from`` e ``vigent_until`` são datetimes naive. ``validated_at``
    é ``None`` enquanto o contrato não passou por probe DLL (Story 1.6
    Task 3) ou por validação manual.
    """

    symbol_root: str
    contract_code: str
    vigent_from: datetime
    vigent_until: datetime
    validated_at: datetime | None
    validation_source: str
    notes: str | None = None


# =====================================================================
# Vigência — lookup canônico (AC2..AC4)
# =====================================================================


def vigent_contract(
    catalog: Catalog,
    symbol_root: str,
    on_date: date,
    *,
    exchange: str = "F",
) -> str:
    """Resolve ``(symbol_root, on_date)`` para ``contract_code`` via catalog.

    Lookup determinístico em ``contracts`` (R9 — não chutar):
    ``WHERE symbol_root = :root AND vigent_from <= :date <= vigent_until``.

    O parâmetro ``exchange`` é aceito para alinhar com a fronteira
    pública (``download(symbol, ..., exchange=...)``) e para facilitar
    futuras versões com tabela ``contracts`` indexada por bolsa — na
    schema atual, ``contracts`` não tem coluna ``exchange`` (a bolsa é
    propriedade do uso, não do contrato em si — WDOJ26 é sempre BMF/F).
    Validamos que ``exchange`` está em ``{"F", "B"}`` para consistência
    com R8 / Q05-V (ver wrapper DLL).

    Args:
        catalog: Instância já inicializada de ``Catalog``.
        symbol_root: Raiz do contrato (ex.: ``"WDO"``, ``"WIN"``,
            ``"PETR4"``). Para equities a raiz costuma ser o próprio
            ticker.
        on_date: Data de referência. Usar ``datetime.date`` (ou subclasses
            como ``datetime``) — o lookup compara com ``vigent_from`` e
            ``vigent_until`` no formato canônico SQLite.
        exchange: ``"F"`` (BMF) ou ``"B"`` (Bovespa). Default ``"F"``.

    Returns:
        ``contract_code`` (ex.: ``"WDOJ26"``).

    Raises:
        InvalidContract: Nenhum contrato vigente para ``(root, date)``.
        ValueError: ``exchange`` fora de ``{"F", "B"}``.
        sqlite3.Error: Falha de catálogo (propagada — caller decide).
    """
    if exchange not in ("F", "B"):
        raise ValueError(
            f"exchange must be 'F' (BMF) or 'B' (Bovespa); got {exchange!r}. "
            "R8/Q05-V — alinhar com fronteira pública."
        )

    on_dt = _coerce_to_datetime(on_date)
    iso_ts = on_dt.strftime("%Y-%m-%d %H:%M:%S")

    conn = catalog._conn_or_raise()
    row = conn.execute(
        """
        SELECT contract_code
          FROM contracts
         WHERE symbol_root = ?
           AND vigent_from <= ?
           AND vigent_until >= ?
         ORDER BY vigent_from DESC
         LIMIT 1
        """,
        (symbol_root, iso_ts, iso_ts),
    ).fetchone()

    if row is None:
        raise InvalidContract(symbol_root, on_dt.date(), exchange=exchange)

    return str(row["contract_code"])


def list_contracts(
    catalog: Catalog,
    *,
    root: str | None = None,
    exchange: str = "F",
) -> list[Contract]:
    """Lista contratos cadastrados, opcionalmente filtrados por raiz.

    Ordenação: por ``symbol_root`` ASC, depois ``vigent_from`` ASC.

    Args:
        catalog: Catálogo SQLite.
        root: Se passado, filtra por ``symbol_root = root``. Default ``None``
            (lista tudo).
        exchange: Reservado para versão futura com coluna ``exchange``.
            Hoje a tabela não armazena bolsa por contrato; aceita o
            parâmetro para manter assinatura estável.

    Returns:
        Lista de :class:`Contract` (vazia se nada cadastrado).
    """
    conn = catalog._conn_or_raise()
    if root is None:
        rows = conn.execute(
            "SELECT * FROM contracts ORDER BY symbol_root ASC, vigent_from ASC"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM contracts WHERE symbol_root = ? " "ORDER BY vigent_from ASC",
            (root,),
        ).fetchall()
    return [_row_to_contract(r) for r in rows]


# =====================================================================
# Seed loader — populate_contracts_from_seed (AC5)
# =====================================================================


# CONTRACTS.md vive em ``docs/storage/CONTRACTS.md`` no repo root.
# Resolvido relativo a este arquivo: src/data_downloader/orchestrator/contracts.py
#  parents[0] = orchestrator/
#  parents[1] = data_downloader/
#  parents[2] = src/
#  parents[3] = repo root
#
# Story v1.0.2 (Pichau smoke 2026-05-06): em frozen mode (PyInstaller),
# CONTRACTS.md é bundled em ``sys._MEIPASS/docs/storage/CONTRACTS.md``
# via spec template ``datas`` tuple. Sem este branch, ``populate_contracts_
# from_seed`` falhava silenciosamente em first-run do .exe distribuído.
def _resolve_default_seed_path() -> Path:
    import sys

    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            candidate = Path(meipass) / "docs" / "storage" / "CONTRACTS.md"
            if candidate.is_file():
                return candidate
    return Path(__file__).resolve().parents[3] / "docs" / "storage" / "CONTRACTS.md"


DEFAULT_SEED_PATH: Final[Path] = _resolve_default_seed_path()
"""Caminho default do seed YAML embutido (CONTRACTS.md §3)."""


# Aceita campo opcional ``notes`` e detecta entradas indented por dois
# espaços. Schema esperado por entry:
#   - symbol_root, contract_code, vigent_from, vigent_until,
#     validation_source [, validated_at, notes]
_SEED_REQUIRED_KEYS: Final[frozenset[str]] = frozenset(
    {
        "symbol_root",
        "contract_code",
        "vigent_from",
        "vigent_until",
        "validation_source",
    }
)


def populate_contracts_from_seed(
    catalog: Catalog,
    seed_path: Path | None = None,
) -> int:
    """Carrega seed de contratos a partir de ``CONTRACTS.md`` (UPSERT idempotente).

    Lê o bloco YAML (delimitado por triple-backticks ``` ```yaml`` /
    ``` ``` ``) sob a chave ``contracts:`` e faz UPSERT em ``contracts``.
    Idempotência por chave primária ``(symbol_root, contract_code)`` — re-
    executar com o mesmo seed não duplica linhas (AC5).

    Args:
        catalog: Catálogo SQLite já inicializado.
        seed_path: Caminho para ``CONTRACTS.md``. Default
            :data:`DEFAULT_SEED_PATH` (resolvido contra o repo root).

    Returns:
        Número de linhas tocadas (inseridas + atualizadas) — usado por
        ``contracts seed`` (CLI futuro) e por testes para diff visual.

    Raises:
        FileNotFoundError: ``seed_path`` não existe.
        ValueError: Formato YAML mal-formado ou entrada sem campos
            obrigatórios.
    """
    path = Path(seed_path) if seed_path is not None else DEFAULT_SEED_PATH
    if not path.exists():
        raise FileNotFoundError(f"Seed not found: {path}")

    entries = _parse_seed_yaml(path.read_text(encoding="utf-8"))

    count = 0
    conn = catalog._conn_or_raise()
    with catalog._transaction():
        for entry in entries:
            missing = _SEED_REQUIRED_KEYS - entry.keys()
            if missing:
                raise ValueError(f"Seed entry missing required keys {sorted(missing)}: {entry}")
            vigent_from = _coerce_to_datetime(entry["vigent_from"])
            vigent_until = _coerce_to_datetime(entry["vigent_until"])
            validated_at_raw = entry.get("validated_at")
            validated_at = (
                _coerce_to_datetime(validated_at_raw)
                if validated_at_raw not in (None, "null", "~", "")
                else None
            )
            conn.execute(
                """
                INSERT INTO contracts(
                    symbol_root, contract_code, vigent_from, vigent_until,
                    validated_at, validation_source, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol_root, contract_code) DO UPDATE SET
                    vigent_from       = excluded.vigent_from,
                    vigent_until      = excluded.vigent_until,
                    validated_at      = excluded.validated_at,
                    validation_source = excluded.validation_source,
                    notes             = excluded.notes
                """,
                (
                    str(entry["symbol_root"]),
                    str(entry["contract_code"]),
                    _format_ts(vigent_from),
                    _format_ts(vigent_until),
                    _format_ts(validated_at) if validated_at else None,
                    str(entry["validation_source"]),
                    str(entry.get("notes", "")) or None,
                ),
            )
            count += 1
    return count


# =====================================================================
# Helpers internos
# =====================================================================


_TS_FORMATS: Final[tuple[str, ...]] = (
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%Y-%m-%dT%H:%M:%S",
)


def _coerce_to_datetime(value: object) -> datetime:
    """Converte ``value`` (str | date | datetime) → datetime naive.

    ``date`` é promovido para ``datetime`` à meia-noite. Strings são
    parseadas por formatos canônicos do SQLite (data ou data+hora).
    """
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, str):
        for fmt in _TS_FORMATS:
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        # Última tentativa — ISO format completo.
        return datetime.fromisoformat(value)
    raise ValueError(f"Cannot coerce {value!r} (type {type(value).__name__}) to datetime")


def _format_ts(value: datetime) -> str:
    """Formata datetime → string SQLite TIMESTAMP canônico (matches Catalog)."""
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _row_to_contract(row: sqlite3.Row) -> Contract:
    """Adapta ``sqlite3.Row`` → :class:`Contract`."""
    return Contract(
        symbol_root=str(row["symbol_root"]),
        contract_code=str(row["contract_code"]),
        vigent_from=_coerce_to_datetime(row["vigent_from"]),
        vigent_until=_coerce_to_datetime(row["vigent_until"]),
        validated_at=_coerce_to_datetime(row["validated_at"]) if row["validated_at"] else None,
        validation_source=str(row["validation_source"]),
        notes=row["notes"] if row["notes"] else None,
    )


# Regex defensiva: extrai o primeiro bloco ```yaml ... ``` que contém a
# chave ``contracts:`` no topo. Permite múltiplos exemplos no MD futuro.
_YAML_BLOCK_RE: Final[re.Pattern[str]] = re.compile(
    r"```yaml\s*\n(.*?)\n```",
    re.DOTALL,
)


def _parse_seed_yaml(markdown: str) -> list[dict[str, object]]:
    """Parser leve de seed YAML embutido em CONTRACTS.md.

    Não usamos PyYAML para evitar nova dependência (consultar Aria); o
    formato do seed é simples (lista de mappings com escalares string,
    sem nesting), e implementamos um parser tolerante apenas para o
    subset usado.

    Args:
        markdown: Conteúdo bruto de ``CONTRACTS.md``.

    Returns:
        Lista de mappings ``{key: value}`` — uma entry por contrato.

    Raises:
        ValueError: Nenhum bloco YAML com ``contracts:`` foi encontrado.
    """
    block: str | None = None
    for match in _YAML_BLOCK_RE.finditer(markdown):
        body = match.group(1)
        if "contracts:" in body:
            block = body
            break
    if block is None:
        raise ValueError(
            "No YAML block with 'contracts:' key found in seed markdown. "
            "Expected fenced ```yaml ... ``` containing top-level 'contracts:' list."
        )

    entries: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    in_contracts = False

    for raw_line in block.splitlines():
        # Strip inline comments (``# ...``) preservando ``#`` em strings — o
        # seed atual não usa ``#`` em valores; corte simples é suficiente.
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        stripped = line.lstrip()

        if stripped == "contracts:":
            in_contracts = True
            continue
        if not in_contracts:
            continue

        # Início de uma nova entry: ``  - key: value``
        if stripped.startswith("- "):
            if current is not None:
                entries.append(current)
            current = {}
            after_dash = stripped[2:].strip()
            if after_dash:
                key, value = _split_kv(after_dash)
                current[key] = value
            continue

        # Continuação: ``    key: value``
        if ":" in stripped and current is not None:
            key, value = _split_kv(stripped)
            current[key] = value

    if current is not None:
        entries.append(current)

    if not entries:
        raise ValueError("YAML block found but contains no contract entries.")
    return entries


def _split_kv(text: str) -> tuple[str, str]:
    """Quebra ``key: value`` removendo aspas externas do valor.

    Tolera ``"value"`` ou ``'value'`` ou bare. Não suporta listas/maps
    aninhados (intencional — parser leve).
    """
    key, _, value = text.partition(":")
    key = key.strip()
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    return key, value
