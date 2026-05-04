"""tests/unit/test_agent_resolver.py — Story 1.7b-followup.

Cobertura de :class:`data_downloader.dll.agent_resolver.AgentResolver`:

- resolve(): cache hit não chama DLL.
- resolve(): cache miss chama GetAgentNameLength + GetAgentName 1x e popula.
- resolve(): length<=0 → fallback ``"Agent#{id}"``.
- resolve(): short=True usa flag 1 na chamada da DLL.
- resolve_all(): batch resolve unique IDs.
- clear_cache() esvazia cache (testes only).
- DLL não inicializada → fallback graceful.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from data_downloader.dll.agent_resolver import AgentResolver
from data_downloader.dll.wrapper import ProfitDLL


def _make_dll(tmp_path: Path, *, mock_dll: MagicMock | None = None) -> ProfitDLL:
    """Helper: cria ProfitDLL com mock_dll injetado (sem init real)."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    dll._dll = mock_dll if mock_dll is not None else MagicMock()
    return dll


def _stub_agent_name(
    mock_dll: MagicMock,
    agent_id: int,
    name: str,
    *,
    short: bool = False,
) -> None:
    """Configura mock_dll.GetAgentNameLength + GetAgentName para retornar `name`.

    Buffer (c_wchar * length) tem ``.value`` = name após chamada — simulamos
    via side_effect que escreve no buffer.
    """

    short_flag = 1 if short else 0
    length = len(name) + 1  # +1 para terminador wide-char

    def _length_side_effect(aid: int, sf: int) -> int:
        if aid == agent_id and sf == short_flag:
            return length
        return 0  # outros IDs → desconhecido

    def _name_side_effect(_length: int, aid: int, buffer: object, sf: int) -> int:
        if aid == agent_id and sf == short_flag:
            # Escreve o nome no buffer (c_wchar array). `buffer.value =` é
            # ctypes-friendly: trunca após o terminador automático.
            for i, ch in enumerate(name):
                buffer[i] = ch
            buffer[len(name)] = "\0"
        return 0

    mock_dll.GetAgentNameLength = MagicMock(side_effect=_length_side_effect)
    mock_dll.GetAgentName = MagicMock(side_effect=_name_side_effect)


# =====================================================================
# Cache hit / miss
# =====================================================================


@pytest.mark.unit
def test_resolve_cache_miss_calls_dll_once(tmp_path: Path) -> None:
    """Primeira chamada chama GetAgentNameLength + GetAgentName 1x cada."""
    mock_dll = MagicMock()
    _stub_agent_name(mock_dll, 308, "XP Inv. CCTVM")
    dll = _make_dll(tmp_path, mock_dll=mock_dll)

    resolver = AgentResolver(dll)
    name = resolver.resolve(308)

    assert name == "XP Inv. CCTVM"
    mock_dll.GetAgentNameLength.assert_called_once_with(308, 0)
    mock_dll.GetAgentName.assert_called_once()


@pytest.mark.unit
def test_resolve_cache_hit_does_not_call_dll(tmp_path: Path) -> None:
    """Segunda chamada com mesmo ID não chama DLL novamente (cache hit)."""
    mock_dll = MagicMock()
    _stub_agent_name(mock_dll, 308, "XP Inv. CCTVM")
    dll = _make_dll(tmp_path, mock_dll=mock_dll)

    resolver = AgentResolver(dll)
    resolver.resolve(308)
    # Reset call counts.
    mock_dll.GetAgentNameLength.reset_mock()
    mock_dll.GetAgentName.reset_mock()

    name2 = resolver.resolve(308)

    assert name2 == "XP Inv. CCTVM"
    assert mock_dll.GetAgentNameLength.call_count == 0
    assert mock_dll.GetAgentName.call_count == 0


@pytest.mark.unit
def test_resolve_different_ids_call_dll_each_time(tmp_path: Path) -> None:
    """IDs distintos viram chamadas separadas à DLL (mas cada um cacheia)."""
    mock_dll = MagicMock()
    _stub_agent_name(mock_dll, 308, "XP")
    _stub_agent_name(mock_dll, 110, "BTG")
    dll = _make_dll(tmp_path, mock_dll=mock_dll)

    # Como cada _stub_agent_name reescreve os side_effects, fazemos uma
    # versão combinada manual.
    name_map = {308: "XP", 110: "BTG"}

    def _len_se(aid: int, sf: int) -> int:
        return len(name_map[aid]) + 1 if aid in name_map and sf == 0 else 0

    def _name_se(_length: int, aid: int, buffer: object, sf: int) -> int:
        if aid in name_map and sf == 0:
            n = name_map[aid]
            for i, ch in enumerate(n):
                buffer[i] = ch
            buffer[len(n)] = "\0"
        return 0

    mock_dll.GetAgentNameLength = MagicMock(side_effect=_len_se)
    mock_dll.GetAgentName = MagicMock(side_effect=_name_se)

    resolver = AgentResolver(dll)
    assert resolver.resolve(308) == "XP"
    assert resolver.resolve(110) == "BTG"
    assert mock_dll.GetAgentNameLength.call_count == 2


# =====================================================================
# Fallback paths
# =====================================================================


@pytest.mark.unit
def test_resolve_unknown_id_returns_fallback(tmp_path: Path) -> None:
    """ID desconhecido (length<=0) → ``Agent#{id}`` fallback."""
    mock_dll = MagicMock()
    mock_dll.GetAgentNameLength = MagicMock(return_value=0)  # desconhecido
    dll = _make_dll(tmp_path, mock_dll=mock_dll)

    resolver = AgentResolver(dll)
    name = resolver.resolve(99999)

    assert name == "Agent#99999"
    # GetAgentName NÃO deve ser chamado (length<=0 short-circuita).
    assert mock_dll.GetAgentName.call_count == 0


@pytest.mark.unit
def test_resolve_negative_length_returns_fallback(tmp_path: Path) -> None:
    """length negativo (alguns drivers retornam -1) → fallback."""
    mock_dll = MagicMock()
    mock_dll.GetAgentNameLength = MagicMock(return_value=-1)
    dll = _make_dll(tmp_path, mock_dll=mock_dll)

    resolver = AgentResolver(dll)
    assert resolver.resolve(42) == "Agent#42"


@pytest.mark.unit
def test_resolve_get_length_oserror_returns_fallback(tmp_path: Path) -> None:
    """GetAgentNameLength lança OSError → fallback graceful (não propaga)."""
    mock_dll = MagicMock()
    mock_dll.GetAgentNameLength = MagicMock(side_effect=OSError("boom"))
    dll = _make_dll(tmp_path, mock_dll=mock_dll)

    resolver = AgentResolver(dll)
    assert resolver.resolve(7) == "Agent#7"


@pytest.mark.unit
def test_resolve_get_length_attribute_error_returns_fallback(tmp_path: Path) -> None:
    """GetAgentNameLength não exportada (DLL antiga) → fallback graceful."""
    mock_dll = MagicMock(spec=[])  # spec vazio = sem nenhum atributo
    dll = _make_dll(tmp_path, mock_dll=mock_dll)

    resolver = AgentResolver(dll)
    assert resolver.resolve(7) == "Agent#7"


@pytest.mark.unit
def test_resolve_dll_not_initialized_returns_fallback(tmp_path: Path) -> None:
    """DLL não inicializada (._dll is None) → fallback (não levanta)."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    assert dll._dll is None

    resolver = AgentResolver(dll)
    assert resolver.resolve(308) == "Agent#308"


# =====================================================================
# short flag
# =====================================================================


@pytest.mark.unit
def test_resolve_short_flag_passed_to_dll(tmp_path: Path) -> None:
    """short=True usa flag=1 na DLL; cache distinto de short=False."""
    mock_dll = MagicMock()
    _stub_agent_name(mock_dll, 308, "XP", short=True)
    dll = _make_dll(tmp_path, mock_dll=mock_dll)

    resolver = AgentResolver(dll)
    name = resolver.resolve(308, short=True)

    assert name == "XP"
    mock_dll.GetAgentNameLength.assert_called_with(308, 1)


@pytest.mark.unit
def test_resolve_short_and_long_have_independent_cache(tmp_path: Path) -> None:
    """short=True e short=False são cache keys distintas."""
    mock_dll = MagicMock()

    def _len_se(_aid: int, sf: int) -> int:
        # long → 14 chars (XP Inv. CCTVM + \0), short → 3 chars (XP + \0)
        return 14 if sf == 0 else 3

    def _name_se(_length: int, _aid: int, buffer: object, sf: int) -> int:
        text = "XP Inv. CCTVM" if sf == 0 else "XP"
        for i, ch in enumerate(text):
            buffer[i] = ch
        buffer[len(text)] = "\0"
        return 0

    mock_dll.GetAgentNameLength = MagicMock(side_effect=_len_se)
    mock_dll.GetAgentName = MagicMock(side_effect=_name_se)
    dll = _make_dll(tmp_path, mock_dll=mock_dll)

    resolver = AgentResolver(dll)
    long_name = resolver.resolve(308, short=False)
    short_name = resolver.resolve(308, short=True)

    assert long_name == "XP Inv. CCTVM"
    assert short_name == "XP"
    # Ambos chamaram a DLL (cache miss separado).
    assert mock_dll.GetAgentNameLength.call_count == 2


# =====================================================================
# Batch resolve_all
# =====================================================================


@pytest.mark.unit
def test_resolve_all_returns_dict_for_unique_ids(tmp_path: Path) -> None:
    """resolve_all retorna dict[id, name] cobrindo todos os IDs únicos."""
    mock_dll = MagicMock()
    name_map = {308: "XP", 110: "BTG", 33: "Genial"}

    def _len_se(aid: int, sf: int) -> int:
        return len(name_map[aid]) + 1 if aid in name_map and sf == 0 else 0

    def _name_se(_length: int, aid: int, buffer: object, sf: int) -> int:
        if aid in name_map and sf == 0:
            n = name_map[aid]
            for i, ch in enumerate(n):
                buffer[i] = ch
            buffer[len(n)] = "\0"
        return 0

    mock_dll.GetAgentNameLength = MagicMock(side_effect=_len_se)
    mock_dll.GetAgentName = MagicMock(side_effect=_name_se)
    dll = _make_dll(tmp_path, mock_dll=mock_dll)

    resolver = AgentResolver(dll)
    result = resolver.resolve_all([308, 110, 33])

    assert result == {308: "XP", 110: "BTG", 33: "Genial"}


@pytest.mark.unit
def test_resolve_all_dedupes_repeated_ids(tmp_path: Path) -> None:
    """resolve_all deduplica IDs repetidos antes de chamar resolve()."""
    mock_dll = MagicMock()
    _stub_agent_name(mock_dll, 308, "XP")
    dll = _make_dll(tmp_path, mock_dll=mock_dll)

    resolver = AgentResolver(dll)
    result = resolver.resolve_all([308, 308, 308, 308])

    assert result == {308: "XP"}
    # Chamada 1x à DLL apesar de 4 IDs no input.
    assert mock_dll.GetAgentNameLength.call_count == 1


# =====================================================================
# clear_cache
# =====================================================================


@pytest.mark.unit
def test_clear_cache_empties_cache(tmp_path: Path) -> None:
    """clear_cache esvazia cache (próxima chamada vira miss)."""
    mock_dll = MagicMock()
    _stub_agent_name(mock_dll, 308, "XP")
    dll = _make_dll(tmp_path, mock_dll=mock_dll)

    resolver = AgentResolver(dll)
    resolver.resolve(308)
    assert resolver.cache_size == 1

    resolver.clear_cache()
    assert resolver.cache_size == 0

    # Próxima chamada vira miss.
    mock_dll.GetAgentNameLength.reset_mock()
    resolver.resolve(308)
    assert mock_dll.GetAgentNameLength.call_count == 1


# =====================================================================
# Empty buffer edge case
# =====================================================================


@pytest.mark.unit
def test_resolve_empty_buffer_returns_fallback(tmp_path: Path) -> None:
    """Buffer vazio (DLL retornou length>0 mas não escreveu) → fallback."""
    mock_dll = MagicMock()
    mock_dll.GetAgentNameLength = MagicMock(return_value=5)

    def _name_se(_length: int, _aid: int, buffer: object, _sf: int) -> int:
        # Não escreve nada (buffer permanece zerado, .value = "").
        buffer[0] = "\0"
        return 0

    mock_dll.GetAgentName = MagicMock(side_effect=_name_se)
    dll = _make_dll(tmp_path, mock_dll=mock_dll)

    resolver = AgentResolver(dll)
    assert resolver.resolve(99) == "Agent#99"
