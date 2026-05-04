"""data_downloader.dll.agent_resolver — Resolve broker agent IDs to names.

Owner: Dex (impl) | Audit: Nelo. Story 1.7b-followup (TranslateTrade complete).

Mapeia IDs numéricos de corretora (``BuyAgent`` / ``SellAgent`` em
``TConnectorTrade``) para nomes legíveis (e.g. ``308`` -> ``"XP Inv. CCTVM"``)
via ``GetAgentNameLength`` + ``GetAgentName`` da ProfitDLL (manual §3.1
L1707-1729).

LEIS RESPEITADAS:

- **R3 / manual §4 L4382**: ``resolve()`` JAMAIS deve ser chamado de dentro
  de um callback (DLL forbid). Caller (IngestorThread) chama em loop após
  ``put_nowait`` ter enfileirado o handle. Resolver explícito é design — não
  faz lookup automático ao receber callback.
- **Cache por (agent_id, short)**: GetAgentName é I/O para a DLL (alocação
  + cópia wide-string); resolver mesma corretora milhares de vezes por
  download seria desperdício. Cache local por instância elimina re-fetches.
- **Fallback determinístico**: agent_id desconhecido (length<=0) retorna
  ``"Agent#{id}"`` em vez de raise — degradação graciosa para manter
  pipeline rodando.

Uso típico (em IngestorThread):

    >>> resolver = AgentResolver(dll)
    >>> for handle, flags in trade_queue:
    ...     fields = dll.translate_trade(handle)
    ...     buyer = resolver.resolve(fields.buy_agent_id)
    ...     seller = resolver.resolve(fields.sell_agent_id)
    ...     # ... build TradeRecord with buyer/seller names
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from data_downloader.dll.wrapper import ProfitDLL

__all__ = ["AgentResolver"]


log: structlog.stdlib.BoundLogger = structlog.get_logger("data_downloader.dll.agent_resolver")


# Sentinela para length inválido (<= 0). Manual §3.1 L1707: GetAgentNameLength
# retorna comprimento do nome (incluindo terminador) ou 0/negativo se ID
# desconhecido.
_INVALID_LENGTH_THRESHOLD: int = 0


class AgentResolver:
    """Resolve broker agent IDs to human-readable names com cache local.

    Uma instância é criada por download (ou compartilhada entre downloads
    do mesmo processo — ID -> nome é estável dentro da sessão da DLL).

    Cache: ``dict[(agent_id, short), str]``. Mesmo ID com flag short=True
    e short=False são entradas distintas — manual §3.1 L1707-1729 expõe
    ambos via mesmo ``GetAgentName`` com 4º arg short.

    Thread-safety: ``dict.setdefault`` em CPython é atomico para chaves
    hashable; sob GIL isso é seguro para múltiplos consumidores chamando
    :meth:`resolve` em paralelo (e.g. múltiplos IngestorThreads). NÃO usar
    fora de CPython sem revisitar.
    """

    def __init__(self, dll: ProfitDLL) -> None:
        """Cria resolver vinculado a uma instância ProfitDLL inicializada.

        Args:
            dll: Instância de :class:`data_downloader.dll.wrapper.ProfitDLL`
                JÁ inicializada (após ``initialize_market_only``). Resolver
                NÃO chama init — apenas usa ``GetAgentNameLength`` e
                ``GetAgentName`` da DLL viva.
        """
        self._dll = dll
        # Key: (agent_id, short_flag). Bool é separado de int para evitar
        # confusão entre ``True`` e ``1`` em logs.
        self._cache: dict[tuple[int, bool], str] = {}

    def resolve(self, agent_id: int, *, short: bool = False) -> str:
        """Resolve um único agent_id em nome legível.

        Args:
            agent_id: ID numérico da corretora (``TConnectorTrade.BuyAgent``
                ou ``SellAgent``). 0 é geralmente "desconhecido" — DLL ainda
                pode retornar nome canônico via length>0; tratamos uniforme.
            short: ``True`` retorna nome curto (e.g. ``"XP"``); ``False``
                retorna nome longo (e.g. ``"XP Inv. CCTVM"``). Manual §3.1
                L1707-1729 (Nelogica).

        Returns:
            Nome resolvido (string non-empty) ou ``"Agent#{id}"`` se DLL
            não conhece o ID (length<=0). NUNCA retorna empty string.

        Raises:
            Não levanta — degradação graciosa (fallback ``Agent#{id}``).
            Internamente captura ``OSError`` da chamada DLL e degrada.
        """
        key = (agent_id, short)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        name = self._lookup_uncached(agent_id, short)
        # ``setdefault`` evita race entre múltiplas threads chamando
        # resolve() para o mesmo ID concorrentemente — primeiro vence.
        return self._cache.setdefault(key, name)

    def resolve_all(
        self,
        agent_ids: Iterable[int],
        *,
        short: bool = False,
    ) -> dict[int, str]:
        """Batch resolve — resolve N IDs de uma vez (todos com mesmo ``short``).

        Cada ID passa por :meth:`resolve` (cache hit / miss individual).
        Útil para preencher dicionário antes de iterar trades — hot path
        (per-trade) faz apenas dict-lookup local.

        Args:
            agent_ids: Iterable de IDs (duplicatas são deduplicadas via set
                interno antes do lookup — chamadas extras à DLL evitadas).
            short: Mesmo significado que :meth:`resolve`.

        Returns:
            ``dict[agent_id, name]`` cobrindo todos os IDs únicos passados.
        """
        # Deduplica via set — caller pode passar lista com IDs repetidos,
        # não queremos lookup redundante mesmo cacheado (overhead de hash).
        unique_ids = set(agent_ids)
        return {aid: self.resolve(aid, short=short) for aid in unique_ids}

    def clear_cache(self) -> None:
        """Limpa o cache local — ÚTIL APENAS PARA TESTES.

        Em produção o cache é correto pela vida toda do processo (ID->nome
        é estável dentro de uma sessão DLL). Limpar = lookup redundante.
        """
        self._cache.clear()

    @property
    def cache_size(self) -> int:
        """Número de entradas no cache (debug/observability)."""
        return len(self._cache)

    # =================================================================
    # Internal — chamada bruta à DLL
    # =================================================================

    def _lookup_uncached(self, agent_id: int, short: bool) -> str:
        """Faz lookup direto na DLL (sem cache).

        Manual §3.1 L1707-1729 (Nelogica):

        - ``GetAgentNameLength(agent_id, short_flag) -> length``: tamanho
          do nome incluindo terminador (ou 0/<0 se ID desconhecido).
        - ``GetAgentName(length, agent_id, buffer, short_flag) -> result``:
          preenche ``buffer`` (c_wchar * length) com o nome.

        Em caso de length <= 0 ou erro do GetAgentName, retorna fallback
        ``"Agent#{id}"``. NUNCA levanta.
        """
        # Acesso ao dll bruto (módulo-private "_dll"). Resolver é uma extensão
        # legítima do wrapper — manipula a DLL via API que o wrapper expõe
        # (mesma vibe que set_history_trade_callback_v2). ``getattr`` tolera
        # mocks/fakes que não expõem ``_dll`` (testes integration que usam
        # FakeProfitDLL sem _dll attribute).
        raw_dll = getattr(self._dll, "_dll", None)
        if raw_dll is None:
            log.warning(
                "agent_resolver.dll_not_initialized",
                agent_id=agent_id,
                short=short,
            )
            return _fallback_name(agent_id)

        short_flag = 1 if short else 0
        try:
            length = int(raw_dll.GetAgentNameLength(agent_id, short_flag))
        except (AttributeError, OSError) as exc:
            # AttributeError: DLL antiga sem essa função (drift Q-DRIFT).
            # OSError: chamada falhou (rara).
            log.warning(
                "agent_resolver.get_length_failed",
                agent_id=agent_id,
                short=short,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return _fallback_name(agent_id)

        if length <= _INVALID_LENGTH_THRESHOLD:
            # ID desconhecido pela DLL — fallback determinístico.
            log.debug(
                "agent_resolver.unknown_id",
                agent_id=agent_id,
                short=short,
                length=length,
            )
            return _fallback_name(agent_id)

        # Aloca buffer wide-char com `length` posições. Manual §3.1 L1721:
        # length retornado JÁ inclui terminador, então criar exatamente
        # ``c_wchar * length`` é correto.
        from ctypes import c_wchar

        buf_type = c_wchar * length
        buffer = buf_type()

        try:
            raw_dll.GetAgentName(length, agent_id, buffer, short_flag)
        except OSError as exc:
            log.warning(
                "agent_resolver.get_name_failed",
                agent_id=agent_id,
                short=short,
                error=str(exc),
            )
            return _fallback_name(agent_id)

        # ``buffer.value`` decodifica até o primeiro \0 (semântica c_wchar
        # array). Se vier empty, ainda usamos fallback para evitar string
        # vazia em downstream.
        name = buffer.value
        if not name:
            return _fallback_name(agent_id)
        return name


def _fallback_name(agent_id: int) -> str:
    """Nome canônico de fallback para IDs não resolvidos.

    Usado quando ``GetAgentNameLength`` retorna length<=0 ou quando
    qualquer chamada à DLL falha. Forma estável: ``"Agent#{id}"``.
    """
    return f"Agent#{agent_id}"
