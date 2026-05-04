"""data_downloader.orchestrator.timestamp — Parser BRT naive de timestamps.

Owner: Dex (impl) | Consult: Nelo (DLL semantics) + Sol (schema timestamp_ns).
Story 1.3.

Parsing/format de timestamps BRT NAIVE (lei R7 / Q04-E) usados pela DLL:

- Formato MANUAL (canônico §3.2): ``"DD/MM/YYYY HH:mm:SS.ZZZ"`` (ponto antes ms).
- Formato QUIRK (Q03-AMB — whale-detector v2): ``"DD/MM/YYYY HH:mm:SS:ZZZ"``
  (dois-pontos antes ms — observado em algumas versões/contratos).

Aceitar AMBOS no parse; sempre formatar no canônico (`.ZZZ`).

CRÍTICO (R7/Q04-E):
    Timestamps são preservados em **BRT naive** — NÃO convertemos para UTC.
    DLL emite no fuso de pregão B3 (BRT, sem DST desde 2019); converter destrói
    semântica de fase de pregão / leilões. ``timestamp_ns`` é nanosegundos
    desde ``1970-01-01 00:00:00`` interpretados como BRT naive (epoch fictício).

Funções públicas:
    parse_brt_timestamp(s) -> int — string → timestamp_ns BRT naive.
    format_brt_timestamp(ns) -> str — timestamp_ns → string canônica `.ZZZ`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

__all__ = [
    "MANUAL_FORMAT_DOT",
    "QUIRK_FORMAT_COLON",
    "format_brt_timestamp",
    "parse_brt_timestamp",
]


MANUAL_FORMAT_DOT: Final[str] = "%d/%m/%Y %H:%M:%S.%f"
"""Formato canônico do manual ProfitDLL §3.2 (ponto antes dos ms)."""

QUIRK_FORMAT_COLON: Final[str] = "%d/%m/%Y %H:%M:%S:%f"
"""Formato observado empiricamente por whale-detector v2 (Q03-AMB)."""


# Timezone fictício UTC apenas para converter datetime naive em epoch sem
# que a stdlib aplique offset local (lei R7 — preservar BRT naive). Isto
# é apenas truque de cálculo; o timestamp_ns resultante representa BRT
# naive, NÃO UTC.
_EPOCH_NAIVE: Final[datetime] = datetime(1970, 1, 1, tzinfo=UTC)


def parse_brt_timestamp(s: str) -> int:
    """Parse string de timestamp da DLL para nanosegundos BRT NAIVE.

    Aceita AMBOS os formatos (Q03-AMB):

    - ``"DD/MM/YYYY HH:mm:SS.ZZZ"`` — manual canônico (ponto).
    - ``"DD/MM/YYYY HH:mm:SS:ZZZ"`` — quirk whale-detector (dois-pontos).

    Retorna nanosegundos desde ``1970-01-01 00:00:00`` interpretado como
    BRT naive — lei R7 / Q04-E. **NÃO converte para UTC**.

    Args:
        s: String de timestamp da DLL.

    Returns:
        ``timestamp_ns`` (int) — nanosegundos desde 1970-01-01 BRT naive.
        Compatível com schema v1.0.0 (SCHEMA.md §1.2 — campo
        ``timestamp_ns: int64``).

    Raises:
        ValueError: Formato inválido (não casa com nenhum dos 2 padrões).

    Examples:
        >>> parse_brt_timestamp("15/04/2026 09:00:00.000")
        1776243600000000000
        >>> # Quirk com dois-pontos:
        >>> parse_brt_timestamp("15/04/2026 09:00:00:000")
        1776243600000000000
        >>> # Erro:
        >>> parse_brt_timestamp("invalid")
        Traceback (most recent call last):
        ...
        ValueError: ...
    """
    if not isinstance(s, str) or not s:
        raise ValueError(f"timestamp must be non-empty string; got {s!r}")

    # Tenta formato MANUAL primeiro (mais comum).
    dt: datetime | None = None
    last_err: ValueError | None = None
    for fmt in (MANUAL_FORMAT_DOT, QUIRK_FORMAT_COLON):
        try:
            dt = datetime.strptime(s, fmt)
            break
        except ValueError as exc:
            last_err = exc
            continue

    if dt is None:
        # Mensagem inclui ambos os padrões aceitos para debug fácil.
        raise ValueError(
            f"timestamp {s!r} does not match accepted formats: "
            f"{MANUAL_FORMAT_DOT!r} (manual) or {QUIRK_FORMAT_COLON!r} "
            f"(quirk Q03-AMB). Underlying error: {last_err}"
        )

    # R7 — preservar BRT naive. Truque: anexar tzinfo=UTC apenas para usar
    # ``timestamp()`` sem que a stdlib converta de local time. Como o
    # datetime é naive (representando BRT), o ``replace(tzinfo=utc)`` apenas
    # diz "trate este wall clock como UTC" — o número de segundos retornado
    # é o número de segundos entre 1970-01-01T00:00:00 e o wall clock.
    # Nanos: multiplicar por 10**9 e adicionar microssegundos (% 10**6).
    aware = dt.replace(tzinfo=UTC)
    delta = aware - _EPOCH_NAIVE
    # delta.days, delta.seconds, delta.microseconds são ints exatos.
    total_seconds = delta.days * 86_400 + delta.seconds
    return total_seconds * 1_000_000_000 + delta.microseconds * 1_000


def format_brt_timestamp(ns: int) -> str:
    """Formata ``timestamp_ns`` BRT naive na string canônica do manual.

    Sempre emite no formato ``"DD/MM/YYYY HH:mm:SS.ZZZ"`` (ponto antes ms).

    Args:
        ns: Nanosegundos desde 1970-01-01 BRT naive.

    Returns:
        String formato canônico (manual §3.2). Precisão: milissegundos
        (3 casas após o ponto). Sub-ms é truncado (não arredondado) para
        manter compatibilidade com sequence_within_ns na storage layer.

    Raises:
        ValueError: Se ``ns`` é negativo.

    Examples:
        >>> format_brt_timestamp(1776243600000000000)
        '15/04/2026 09:00:00.000'
    """
    if ns < 0:
        raise ValueError(f"timestamp_ns must be >= 0; got {ns}")
    # Reconverter para datetime naive: usar ``fromtimestamp(s, tz=UTC)`` (não
    # deprecated em Python 3.14+) e dropar tzinfo para obter wall clock
    # que representa BRT naive (interpretação fictícia).
    seconds, sub_ns = divmod(ns, 1_000_000_000)
    micros = sub_ns // 1_000  # truncate sub-ms
    from datetime import UTC

    dt_aware = datetime.fromtimestamp(seconds, tz=UTC)
    dt_naive = dt_aware.replace(microsecond=micros, tzinfo=None)
    # %f imprime 6 casas; cortar para 3 (ms) para casar com formato manual.
    formatted = dt_naive.strftime("%d/%m/%Y %H:%M:%S.%f")
    return formatted[:-3]  # remove últimos 3 dígitos (us → ms)
