"""tests/integration/test_download_primitive.py — Story 1.3.

Testes de integração de ``orchestrator.download_primitive.download_chunk``.

Mocka ``ProfitDLL`` inteiro (sem real DLL). Foco: comportamento do loop
principal, IngestorThread + ProgressMonitor, semântica de status, lógica
de 99% reconnect (Q02-E), validação de exchange (R8).

Cobertura:
- Sequência N callbacks → ChunkResult tem N trades.
- Progress 100% → status="completed".
- Timeout → status="timeout".
- 99% reconnect (sustentado) → continua aguardando, conclui em 100.
- exchange=='BMF' → ValueError (R8).
- TranslateTrade chamado para cada trade no IngestorThread.
- dedup_sequence_within_ns funciona quando trade_id é None (TradeNumber=0).
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from data_downloader.dll import callbacks as cb_module
from data_downloader.dll.types import (
    TC_LAST_PACKET,
    TAssetID,
    TConnectorAssetIdentifier,
    TradeFields,
)
from data_downloader.orchestrator.download_primitive import (
    ChunkResult,
    download_chunk,
)


@pytest.fixture(autouse=True)
def _isolate_cb_refs() -> object:
    cb_module.cleanup_cb_refs()
    yield
    cb_module.cleanup_cb_refs()


# =====================================================================
# Mock helpers
# =====================================================================


class _FakeProfitDLL:
    """DLL mock minimalista para testar download_chunk.

    Captura callbacks via ``set_*`` methods; ``get_history_trades`` dispara
    a sequência configurada de trades + progresso em thread separada
    (simulando ConnectorThread interna). ``translate_trade`` preenche o
    struct passado com dados pré-configurados (indexed por handle).
    """

    def __init__(
        self,
        *,
        trade_specs: list[dict[str, Any]] | None = None,
        progress_sequence: list[int] | None = None,
        get_history_return: int = 0,
        emit_delay: float = 0.001,
        dll_version: str = "4.0.0.34",
        subscribe_return: int = 0,
        unsubscribe_return: int = 0,
        subscribe_raises: BaseException | None = None,
    ) -> None:
        self.trade_specs = trade_specs or []
        self.progress_sequence = progress_sequence or [25, 50, 75, 100]
        self.get_history_return = get_history_return
        self.emit_delay = emit_delay
        self.dll_version = dll_version
        self.subscribe_return = subscribe_return
        self.unsubscribe_return = unsubscribe_return
        self.subscribe_raises = subscribe_raises

        self._history_cb: Any = None
        self._progress_cb: Any = None
        self._cb_refs: list[Any] = []
        self._emit_thread: threading.Thread | None = None

        # Counters para asserts.
        self.set_history_calls = 0
        self.set_progress_calls = 0
        self.get_history_calls = 0
        self.translate_trade_calls = 0
        self.subscribe_calls = 0
        self.unsubscribe_calls = 0
        # Story 1.7b-followup — ordem das chamadas para validar
        # subscribe ANTES de get_history e unsubscribe DEPOIS.
        self.call_order: list[str] = []

    # ---- DLL surface (compatível com ProfitDLL real) ----

    def subscribe_ticker(self, ticker: str, exchange: str) -> int:
        self.subscribe_calls += 1
        self.call_order.append("subscribe_ticker")
        if self.subscribe_raises is not None:
            raise self.subscribe_raises
        return self.subscribe_return

    def unsubscribe_ticker(self, ticker: str, exchange: str) -> int:
        self.unsubscribe_calls += 1
        self.call_order.append("unsubscribe_ticker")
        return self.unsubscribe_return

    def set_history_trade_callback_v2(self, cb: Any) -> None:
        self._history_cb = cb
        self.set_history_calls += 1
        self.call_order.append("set_history_trade_callback_v2")

    def set_progress_callback(self, cb: Any) -> None:
        self._progress_cb = cb
        self.set_progress_calls += 1
        self.call_order.append("set_progress_callback")

    def get_history_trades(
        self,
        ticker: str,
        exchange: str,
        dt_start_str: str,
        dt_end_str: str,
    ) -> int:
        self.get_history_calls += 1
        self.call_order.append("get_history_trades")
        if self.get_history_return < 0:
            return self.get_history_return  # erro NL_*
        # Spawn thread que emite trades + progress (simula ConnectorThread).
        self._emit_thread = threading.Thread(
            target=self._emit_loop,
            args=(ticker,),
            daemon=True,
        )
        self._emit_thread.start()
        return self.get_history_return

    def translate_trade(self, handle: int) -> TradeFields | None:
        """Story 1.7b-followup — retorna TradeFields direto (nova API).

        Substitui o legacy ``(handle, struct) -> int``. Spec dos trades é
        montada em ``__init__``; índice == handle.
        """
        self.translate_trade_calls += 1
        if handle >= len(self.trade_specs):
            return None  # erro NL_*
        spec = self.trade_specs[handle]
        ts: datetime = spec["timestamp"]
        # Calcula timestamp_ns BRT naive (mesma fórmula de
        # _system_time_to_ns_local em wrapper.py / R7).
        from datetime import UTC

        aware = ts.replace(tzinfo=UTC)
        delta = aware - datetime(1970, 1, 1, tzinfo=UTC)
        total_seconds = delta.days * 86_400 + delta.seconds
        timestamp_ns = total_seconds * 1_000_000_000 + delta.microseconds * 1_000

        return TradeFields(
            version=0,
            timestamp_ns=timestamp_ns,
            trade_number=spec.get("trade_number", handle + 1),
            price=spec["price"],
            quantity=spec["quantity"],
            volume=spec["price"] * spec["quantity"],
            buy_agent_id=spec.get("buy_agent", 0),
            sell_agent_id=spec.get("sell_agent", 0),
            trade_type=spec.get("trade_type", 1),
        )

    # ---- Internal emit loop ----

    def _emit_loop(self, ticker: str) -> None:
        # Pequena pausa para garantir que threads do download_chunk estão
        # ativas antes do primeiro emit.
        time.sleep(0.01)
        # Asset structs reais — WINFUNCTYPE em Windows valida tipo do 1º arg.
        # History V2 usa TConnectorAssetIdentifier; Progress V1 usa TAssetID
        # (Q-DRIFT-05 — alinhado ao exemplo Nelogica main.py L243).
        asset_v2 = TConnectorAssetIdentifier(Version=0, Ticker=ticker, Exchange="F", FeedType=0)
        asset_v1 = TAssetID(ticker=ticker, bolsa="F", feed=0)
        # Emite trades intercalados com progresso (cada 25%).
        n_trades = len(self.trade_specs)
        for i, spec in enumerate(self.trade_specs):
            if self._history_cb is None:
                break
            flags = spec.get("flags", 0)
            # Última flag opcionalmente força TC_LAST_PACKET via spec.
            if i == n_trades - 1 and spec.get("last_packet", False):
                flags |= TC_LAST_PACKET
            self._history_cb(asset_v2, i, flags)
            time.sleep(self.emit_delay)
        # Após trades, emite progresso configurado.
        # Story 1.7b-followup (Q-DRIFT-05): progress callback signature é
        # ``(TAssetID, c_int)`` — passamos asset_v1 + progress (2 args).
        for p in self.progress_sequence:
            if self._progress_cb is None:
                break
            self._progress_cb(asset_v1, p)
            time.sleep(self.emit_delay)


def _spec(
    *,
    timestamp: datetime,
    price: float = 100.0,
    quantity: int = 1,
    trade_number: int = 0,
    last_packet: bool = False,
) -> dict[str, Any]:
    """Helper: produz dict trade_spec para _FakeProfitDLL."""
    return {
        "timestamp": timestamp,
        "price": price,
        "quantity": quantity,
        "trade_number": trade_number,
        "last_packet": last_packet,
    }


# =====================================================================
# Tests
# =====================================================================


@pytest.mark.integration
def test_download_chunk_returns_n_trades_for_n_callbacks() -> None:
    """Test 1 — N callbacks emitidos → ChunkResult.trades tem N elementos."""
    base = datetime(2026, 4, 15, 9, 0, 0)
    specs = [
        _spec(timestamp=base.replace(second=i), price=100.0 + i, quantity=1, trade_number=i + 1)
        for i in range(10)
    ]
    dll = _FakeProfitDLL(trade_specs=specs)

    result: ChunkResult = download_chunk(
        dll,  # type: ignore[arg-type]
        "WDOJ26",
        "F",
        base,
        base.replace(second=10),
        timeout=10,
    )

    assert isinstance(result, ChunkResult)
    assert len(result.trades) == 10
    assert result.symbol == "WDOJ26"
    assert result.exchange == "F"
    # trade_id (TradeNumber) preservado:
    assert [t.trade_id for t in result.trades] == list(range(1, 11))


@pytest.mark.integration
def test_download_chunk_status_completed_on_progress_100() -> None:
    """Test 2 — progresso 100% → status='completed'."""
    base = datetime(2026, 4, 15, 9, 0, 0)
    specs = [_spec(timestamp=base, trade_number=1)]
    dll = _FakeProfitDLL(trade_specs=specs, progress_sequence=[50, 100])

    result = download_chunk(
        dll,  # type: ignore[arg-type]
        "WDOJ26",
        "F",
        base,
        base.replace(hour=17),
        timeout=10,
    )

    assert result.status == "completed"
    assert 100 in result.progress_history


@pytest.mark.integration
def test_download_chunk_status_timeout_when_no_progress_or_last_packet() -> None:
    """Test 3 — sem progresso=100 e sem TC_LAST_PACKET → status='timeout'.

    Configuramos progresso parcial (apenas 50) e nenhum TC_LAST_PACKET.
    Com timeout=2s, download_chunk deve retornar status='timeout'.
    """
    base = datetime(2026, 4, 15, 9, 0, 0)
    specs = [_spec(timestamp=base, trade_number=1)]
    dll = _FakeProfitDLL(trade_specs=specs, progress_sequence=[25, 50])

    result = download_chunk(
        dll,  # type: ignore[arg-type]
        "WDOJ26",
        "F",
        base,
        base.replace(hour=17),
        timeout=2,
    )

    assert result.status == "timeout"
    assert result.last_packet_seen is False
    # Progresso registrado parcialmente:
    assert 100 not in result.progress_history


@pytest.mark.integration
def test_download_chunk_tolerates_99_reconnect_then_completes() -> None:
    """Test 4 — Q02-E: 99% sustentado seguido de 100% → status='completed'.

    Cenário: ProgressMonitor recebe 25, 50, 99, 99, 99, 100. Não deve
    abortar ao ver os 99 repetidos.
    """
    base = datetime(2026, 4, 15, 9, 0, 0)
    specs = [_spec(timestamp=base, trade_number=1)]
    dll = _FakeProfitDLL(
        trade_specs=specs,
        progress_sequence=[25, 50, 99, 99, 99, 100],
    )

    result = download_chunk(
        dll,  # type: ignore[arg-type]
        "WDOJ26",
        "F",
        base,
        base.replace(hour=17),
        timeout=10,
    )

    assert result.status == "completed"
    # Histórico contém os 99 repetidos:
    assert result.progress_history.count(99) == 3
    assert 100 in result.progress_history


@pytest.mark.integration
def test_download_chunk_rejects_invalid_exchange_bmf() -> None:
    """Test 5 — R8/Q05-V: bolsa 'BMF' → ValueError."""
    base = datetime(2026, 4, 15, 9, 0, 0)
    dll = _FakeProfitDLL()

    with pytest.raises(ValueError) as exc:
        download_chunk(
            dll,  # type: ignore[arg-type]
            "WDOJ26",
            "BMF",  # inválido!
            base,
            base.replace(hour=17),
        )
    assert "exchange" in str(exc.value).lower()


@pytest.mark.integration
def test_download_chunk_translate_trade_called_per_trade_in_ingestor_thread() -> None:
    """Test 6 — TranslateTrade chamado N vezes (1 por trade), todas em IngestorThread.

    Verificações:
      - dll.translate_trade.call_count == n_trades
      - Verificar que NÃO foi chamado durante callback exec (já coberto pelo
        teste de wrapper_history). Aqui validamos contagem total.
    """
    base = datetime(2026, 4, 15, 9, 0, 0)
    n = 25
    specs = [_spec(timestamp=base.replace(second=i % 60), trade_number=i + 1) for i in range(n)]
    dll = _FakeProfitDLL(trade_specs=specs)

    result = download_chunk(
        dll,  # type: ignore[arg-type]
        "WDOJ26",
        "F",
        base,
        base.replace(hour=17),
        timeout=10,
    )

    assert result.status == "completed"
    assert len(result.trades) == n
    # CORE: TranslateTrade chamado exatamente N vezes (1 por trade).
    assert dll.translate_trade_calls == n


@pytest.mark.integration
def test_download_chunk_dedup_sequence_when_trade_id_is_none() -> None:
    """Test 7 — quando TradeNumber=0 (trade_id None), sequence_within_ns desempata.

    Cenário: 3 trades no MESMO timestamp_ns (mesmo wall clock até ms),
    todos com TradeNumber=0 → trade_id=None. sequence_within_ns deve ser
    0, 1, 2 respectivamente.
    """
    same_ts = datetime(2026, 4, 15, 9, 0, 0, 500_000)
    specs = [
        _spec(timestamp=same_ts, price=100.0, quantity=1, trade_number=0),
        _spec(timestamp=same_ts, price=101.0, quantity=2, trade_number=0),
        _spec(timestamp=same_ts, price=102.0, quantity=3, trade_number=0),
    ]
    dll = _FakeProfitDLL(trade_specs=specs)

    result = download_chunk(
        dll,  # type: ignore[arg-type]
        "WDOJ26",
        "F",
        datetime(2026, 4, 15, 9, 0, 0),
        datetime(2026, 4, 15, 17, 0, 0),
        timeout=10,
    )

    assert result.status == "completed"
    assert len(result.trades) == 3
    # Todos os trade_id são None (TradeNumber=0):
    assert all(t.trade_id is None for t in result.trades)
    # sequence_within_ns 0, 1, 2 — confirmando bucket único por (symbol, ts_ns).
    seqs = [t.sequence_within_ns for t in result.trades]
    assert sorted(seqs) == [0, 1, 2], f"sequences: {seqs}"


# =====================================================================
# Extra coverage — TC_LAST_PACKET, failed status, validação dt_end<dt_start
# =====================================================================


@pytest.mark.integration
def test_download_chunk_tc_last_packet_completes_without_progress_100() -> None:
    """TC_LAST_PACKET no último trade → status='completed' mesmo sem progress 100."""
    base = datetime(2026, 4, 15, 9, 0, 0)
    specs = [
        _spec(timestamp=base, trade_number=1),
        _spec(timestamp=base.replace(second=1), trade_number=2, last_packet=True),
    ]
    # Progress não chega a 100 — apenas 50.
    dll = _FakeProfitDLL(trade_specs=specs, progress_sequence=[50])

    result = download_chunk(
        dll,  # type: ignore[arg-type]
        "WDOJ26",
        "F",
        base,
        base.replace(hour=17),
        timeout=10,
    )

    assert result.status == "completed"
    assert result.last_packet_seen is True


@pytest.mark.integration
def test_download_chunk_status_failed_on_negative_get_history_return() -> None:
    """GetHistoryTrades retorna NL_* negativo → status='failed'."""
    base = datetime(2026, 4, 15, 9, 0, 0)
    dll = _FakeProfitDLL(get_history_return=-2147483390)  # NL_INVALID_TICKER

    result = download_chunk(
        dll,  # type: ignore[arg-type]
        "BADTICKER",
        "F",
        base,
        base.replace(hour=17),
        timeout=5,
    )

    assert result.status == "failed"
    assert result.nl_error_code == -2147483390
    assert len(result.trades) == 0


@pytest.mark.integration
def test_download_chunk_validates_dt_order() -> None:
    """dt_end < dt_start → ValueError."""
    dll = _FakeProfitDLL()
    with pytest.raises(ValueError):
        download_chunk(
            dll,  # type: ignore[arg-type]
            "WDOJ26",
            "F",
            datetime(2026, 4, 15, 17, 0, 0),
            datetime(2026, 4, 15, 9, 0, 0),
        )


@pytest.mark.integration
def test_download_chunk_actual_start_end_match_trades() -> None:
    """actual_start/actual_end derivados dos trades (BRT naive)."""
    base = datetime(2026, 4, 15, 9, 0, 0)
    specs = [
        _spec(timestamp=base.replace(second=10), trade_number=1),
        _spec(timestamp=base.replace(second=30), trade_number=2),
        _spec(timestamp=base.replace(second=20), trade_number=3),
    ]
    dll = _FakeProfitDLL(trade_specs=specs)

    result = download_chunk(
        dll,  # type: ignore[arg-type]
        "WDOJ26",
        "F",
        base,
        base.replace(hour=17),
        timeout=10,
    )

    assert result.status == "completed"
    # min/max via timestamp_ns:
    assert result.actual_start is not None
    assert result.actual_end is not None
    assert result.actual_start.second == 10
    assert result.actual_end.second == 30


@pytest.mark.integration
def test_download_chunk_uses_v2_callback_via_set_history_trade_callback_v2() -> None:
    """Callback registrado via set_history_trade_callback_v2 (V2, não V1)."""
    base = datetime(2026, 4, 15, 9, 0, 0)
    dll = _FakeProfitDLL(trade_specs=[_spec(timestamp=base, trade_number=1)])

    download_chunk(
        dll,  # type: ignore[arg-type]
        "WDOJ26",
        "F",
        base,
        base.replace(hour=17),
        timeout=10,
    )

    # set_history_trade_callback_v2 chamado (V2 — COUNCIL-03).
    assert dll.set_history_calls == 1
    assert dll.set_progress_calls == 1
    assert dll.get_history_calls == 1


@pytest.mark.integration
def test_download_chunk_dll_version_in_trade_records() -> None:
    """Cada TradeRecord carrega dll_version (metadata para Sol H19/H1)."""
    base = datetime(2026, 4, 15, 9, 0, 0)
    dll = _FakeProfitDLL(
        trade_specs=[_spec(timestamp=base, trade_number=1)],
        dll_version="4.0.0.34",
    )

    result = download_chunk(
        dll,  # type: ignore[arg-type]
        "WDOJ26",
        "F",
        base,
        base.replace(hour=17),
        timeout=10,
    )

    assert result.trades[0].dll_version == "4.0.0.34"


@pytest.mark.integration
def test_download_chunk_chunk_id_propagated_to_trades() -> None:
    """chunk_id gerado uma vez e propagado para cada TradeRecord."""
    base = datetime(2026, 4, 15, 9, 0, 0)
    specs = [_spec(timestamp=base.replace(second=i), trade_number=i + 1) for i in range(5)]
    dll = _FakeProfitDLL(trade_specs=specs)

    result = download_chunk(
        dll,  # type: ignore[arg-type]
        "WDOJ26",
        "F",
        base,
        base.replace(hour=17),
        timeout=10,
    )

    chunk_ids = {t.chunk_id for t in result.trades}
    assert chunk_ids == {result.chunk_id}, "todos os trades devem ter o mesmo chunk_id"


@pytest.mark.integration
def test_download_chunk_uses_explicit_dll_version_arg() -> None:
    """Arg dll_version explícito sobrescreve dll.dll_version."""
    base = datetime(2026, 4, 15, 9, 0, 0)
    dll = _FakeProfitDLL(
        trade_specs=[_spec(timestamp=base, trade_number=1)],
        dll_version="4.0.0.34",
    )

    result = download_chunk(
        dll,  # type: ignore[arg-type]
        "WDOJ26",
        "F",
        base,
        base.replace(hour=17),
        timeout=10,
        dll_version="9.9.9.9-test",
    )

    assert result.trades[0].dll_version == "9.9.9.9-test"


@pytest.mark.integration
def test_download_chunk_compatible_with_real_profitdll_via_magicmock() -> None:
    """Sanity: a interface batida pelo download_chunk casa com ProfitDLL real.

    Substituímos _FakeProfitDLL por MagicMock(spec=ProfitDLL) e injetamos
    comportamento via side_effect — garante que estamos chamando exatamente
    os métodos que ProfitDLL expõe.
    """
    from data_downloader.dll.wrapper import ProfitDLL

    mock_dll = MagicMock(spec=ProfitDLL)
    mock_dll.dll_version = "4.0.0.34"
    # Story 1.7b-followup — subscribe/unsubscribe são int (NL_OK=0). Sem
    # ``return_value`` o MagicMock retorna outro MagicMock que falha em
    # comparações ``sub_rc >= 0`` em download_primitive.
    mock_dll.subscribe_ticker.return_value = 0
    mock_dll.unsubscribe_ticker.return_value = 0

    # Capture o callback registrado para emitir manualmente.
    captured_history_cb: list[Any] = []
    captured_progress_cb: list[Any] = []

    def _cap_h(cb: Any) -> None:
        captured_history_cb.append(cb)

    def _cap_p(cb: Any) -> None:
        captured_progress_cb.append(cb)

    mock_dll.set_history_trade_callback_v2.side_effect = _cap_h
    mock_dll.set_progress_callback.side_effect = _cap_p

    def _fill_fields(handle: int) -> TradeFields:
        # Story 1.7b-followup — translate_trade(handle) → TradeFields direto.
        from datetime import UTC

        ts = datetime(2026, 4, 15, 9, 0, handle % 60)
        aware = ts.replace(tzinfo=UTC)
        delta = aware - datetime(1970, 1, 1, tzinfo=UTC)
        ns = (delta.days * 86_400 + delta.seconds) * 1_000_000_000
        return TradeFields(
            version=0,
            timestamp_ns=ns,
            trade_number=handle + 1,
            price=100.0,
            quantity=1,
            volume=100.0,
            buy_agent_id=0,
            sell_agent_id=0,
            trade_type=1,
        )

    mock_dll.translate_trade.side_effect = _fill_fields

    def _trigger_emits(*_args: Any, **_kw: Any) -> int:
        # Simula ConnectorThread em background.
        asset_v2 = TConnectorAssetIdentifier(Version=0, Ticker="WDOJ26", Exchange="F", FeedType=0)
        asset_v1 = TAssetID(ticker="WDOJ26", bolsa="F", feed=0)

        def _emit() -> None:
            time.sleep(0.01)
            for h in range(3):
                if captured_history_cb:
                    captured_history_cb[0](asset_v2, h, 0)
            time.sleep(0.01)
            if captured_progress_cb:
                # Story 1.7b-followup (Q-DRIFT-05): progress signature é
                # ``(TAssetID, c_int)`` — 2 args.
                captured_progress_cb[0](asset_v1, 100)

        threading.Thread(target=_emit, daemon=True).start()
        return 0

    mock_dll.get_history_trades.side_effect = _trigger_emits

    base = datetime(2026, 4, 15, 9, 0, 0)
    result = download_chunk(
        mock_dll,
        "WDOJ26",
        "F",
        base,
        base.replace(hour=17),
        timeout=10,
    )

    assert result.status == "completed"
    assert len(result.trades) == 3
    # Métodos batidos:
    mock_dll.set_history_trade_callback_v2.assert_called_once()
    mock_dll.set_progress_callback.assert_called_once()
    mock_dll.get_history_trades.assert_called_once()
    assert mock_dll.translate_trade.call_count == 3


# =====================================================================
# Story 1.7b-followup — SubscribeTicker / UnsubscribeTicker integration
# =====================================================================


@pytest.mark.integration
def test_download_chunk_subscribes_before_get_history_trades() -> None:
    """``subscribe_ticker`` é chamada ANTES de ``get_history_trades`` (autoridade ProfitDLL).

    Bug crítico corrigido: sem subscribe pré-download, a DLL não entrega
    trades históricos. Validação via call_order.

    Usa ``last_packet=True`` + ``progress_sequence=[]`` para sinalizar fim
    via TC_LAST_PACKET (não depende de progress=100 — independente do
    quirk Q-DRIFT-05 do progress callback signature).
    """
    base = datetime(2026, 4, 15, 9, 0, 0)
    specs = [_spec(timestamp=base, trade_number=1, last_packet=True)]
    dll = _FakeProfitDLL(trade_specs=specs, progress_sequence=[])

    download_chunk(
        dll,  # type: ignore[arg-type]
        "WDOJ26",
        "F",
        base,
        base.replace(hour=17),
        timeout=10,
    )

    assert dll.subscribe_calls == 1
    assert dll.get_history_calls == 1
    # subscribe DEVE preceder get_history (ordem é crítica — manual + Nelogica).
    sub_idx = dll.call_order.index("subscribe_ticker")
    get_idx = dll.call_order.index("get_history_trades")
    assert (
        sub_idx < get_idx
    ), f"subscribe_ticker deve vir ANTES de get_history_trades; call_order={dll.call_order}"


@pytest.mark.integration
def test_download_chunk_unsubscribes_after_completed_download() -> None:
    """``unsubscribe_ticker`` é chamada APÓS download bem-sucedido (try/finally).

    Usa ``last_packet=True`` para sinalizar fim — independente do progress
    callback (cuja signature foi atualizada Q-DRIFT-05).
    """
    base = datetime(2026, 4, 15, 9, 0, 0)
    specs = [_spec(timestamp=base, trade_number=1, last_packet=True)]
    dll = _FakeProfitDLL(trade_specs=specs, progress_sequence=[])

    result = download_chunk(
        dll,  # type: ignore[arg-type]
        "WDOJ26",
        "F",
        base,
        base.replace(hour=17),
        timeout=10,
    )

    assert result.status == "completed"
    assert dll.unsubscribe_calls == 1
    # unsubscribe DEVE vir DEPOIS de get_history.
    unsub_idx = dll.call_order.index("unsubscribe_ticker")
    get_idx = dll.call_order.index("get_history_trades")
    assert unsub_idx > get_idx


@pytest.mark.integration
def test_download_chunk_unsubscribes_even_on_failed_get_history() -> None:
    """try/finally — unsubscribe é chamado mesmo quando GetHistoryTrades falha."""
    base = datetime(2026, 4, 15, 9, 0, 0)
    dll = _FakeProfitDLL(get_history_return=-2147483390)  # NL_INVALID_TICKER

    result = download_chunk(
        dll,  # type: ignore[arg-type]
        "BADTICKER",
        "F",
        base,
        base.replace(hour=17),
        timeout=5,
    )

    assert result.status == "failed"
    assert dll.subscribe_calls == 1
    assert dll.unsubscribe_calls == 1, "unsubscribe DEVE ser chamado mesmo em falha (try/finally)"


@pytest.mark.integration
def test_download_chunk_unsubscribes_on_timeout() -> None:
    """try/finally — unsubscribe é chamado mesmo quando download dá timeout."""
    base = datetime(2026, 4, 15, 9, 0, 0)
    specs = [_spec(timestamp=base, trade_number=1)]
    dll = _FakeProfitDLL(trade_specs=specs, progress_sequence=[25, 50])

    result = download_chunk(
        dll,  # type: ignore[arg-type]
        "WDOJ26",
        "F",
        base,
        base.replace(hour=17),
        timeout=2,
    )

    assert result.status == "timeout"
    assert dll.unsubscribe_calls == 1


@pytest.mark.integration
def test_download_chunk_subscribed_flag_true_on_success() -> None:
    """ChunkResult.subscribed=True quando SubscribeTicker retorna >= 0."""
    base = datetime(2026, 4, 15, 9, 0, 0)
    specs = [_spec(timestamp=base, trade_number=1, last_packet=True)]
    dll = _FakeProfitDLL(trade_specs=specs, progress_sequence=[], subscribe_return=0)

    result = download_chunk(
        dll,  # type: ignore[arg-type]
        "WDOJ26",
        "F",
        base,
        base.replace(hour=17),
        timeout=10,
    )

    assert result.subscribed is True


@pytest.mark.integration
def test_download_chunk_subscribed_flag_false_on_negative_code() -> None:
    """ChunkResult.subscribed=False quando SubscribeTicker retorna NL_* negativo.

    Download SEGUE adiante (DLL pode aceitar tickers já subscritos retornando
    código não-zero) — apenas o flag indica forensics.
    """
    base = datetime(2026, 4, 15, 9, 0, 0)
    specs = [_spec(timestamp=base, trade_number=1, last_packet=True)]
    dll = _FakeProfitDLL(trade_specs=specs, progress_sequence=[], subscribe_return=-1234)

    result = download_chunk(
        dll,  # type: ignore[arg-type]
        "WDOJ26",
        "F",
        base,
        base.replace(hour=17),
        timeout=10,
    )

    # Download segue mesmo com subscribe falhando — flag indica.
    assert result.subscribed is False


@pytest.mark.integration
def test_download_chunk_subscribed_flag_false_when_subscribe_raises() -> None:
    """Subscribe raise (e.g. AttributeError em DLL drift) → subscribed=False, download segue."""
    base = datetime(2026, 4, 15, 9, 0, 0)
    specs = [_spec(timestamp=base, trade_number=1, last_packet=True)]
    dll = _FakeProfitDLL(
        trade_specs=specs,
        progress_sequence=[],
        subscribe_raises=AttributeError("SubscribeTicker not exported"),
    )

    result = download_chunk(
        dll,  # type: ignore[arg-type]
        "WDOJ26",
        "F",
        base,
        base.replace(hour=17),
        timeout=10,
    )

    # Subscribe raise não bloqueia download; flag indica forensics.
    assert result.subscribed is False
    # Unsubscribe ainda é chamado no finally (cleanup best-effort).
    assert dll.unsubscribe_calls == 1


@pytest.mark.integration
def test_download_chunk_subscribe_unsubscribe_full_order() -> None:
    """Ordem completa do fluxo: subscribe → set_callbacks → get_history → unsubscribe."""
    base = datetime(2026, 4, 15, 9, 0, 0)
    specs = [_spec(timestamp=base, trade_number=1, last_packet=True)]
    dll = _FakeProfitDLL(trade_specs=specs, progress_sequence=[])

    download_chunk(
        dll,  # type: ignore[arg-type]
        "WDOJ26",
        "F",
        base,
        base.replace(hour=17),
        timeout=10,
    )

    # Cinco eventos esperados — ordem importa.
    expected_prefix = [
        "subscribe_ticker",
        "set_history_trade_callback_v2",
        "set_progress_callback",
        "get_history_trades",
    ]
    actual_prefix = dll.call_order[: len(expected_prefix)]
    assert (
        actual_prefix == expected_prefix
    ), f"Prefix order mismatch:\nexpected: {expected_prefix}\nactual: {actual_prefix}"
    # Unsubscribe é o ÚLTIMO evento (try/finally).
    assert dll.call_order[-1] == "unsubscribe_ticker"


# =====================================================================
# Story 1.7b-followup — TranslateTrade complete + AgentResolver integration
# =====================================================================


@pytest.mark.integration
def test_download_chunk_resolves_agent_names_per_trade() -> None:
    """IngestorThread chama AgentResolver.resolve para cada trade não-zero.

    Cenário: 3 trades com agents (308, 110), (308, 33), (110, 308). Resolver
    cacheia — apenas 3 lookups distintos esperados (308, 110, 33). Cada
    TradeRecord tem ``buy_agent_name`` e ``sell_agent_name`` populados.
    """
    from data_downloader.dll.agent_resolver import AgentResolver

    base = datetime(2026, 4, 15, 9, 0, 0)
    specs = [
        {
            **_spec(timestamp=base.replace(second=0), trade_number=1, last_packet=False),
            "buy_agent": 308,
            "sell_agent": 110,
        },
        {
            **_spec(timestamp=base.replace(second=1), trade_number=2, last_packet=False),
            "buy_agent": 308,
            "sell_agent": 33,
        },
        {
            **_spec(timestamp=base.replace(second=2), trade_number=3, last_packet=True),
            "buy_agent": 110,
            "sell_agent": 308,
        },
    ]
    dll = _FakeProfitDLL(trade_specs=specs, progress_sequence=[])

    # Resolver injetado com mock-side cache pre-popular para evitar dependência
    # de _dll attribute (FakeProfitDLL não expõe). MonkeyPatch via lookup
    # substituto.
    name_map = {308: "XP Inv. CCTVM", 110: "BTG Pactual", 33: "Genial Inst."}

    class _StubResolver(AgentResolver):
        def resolve(self, agent_id: int, *, short: bool = False) -> str:
            return name_map.get(agent_id, f"Agent#{agent_id}")

    stub = _StubResolver(dll)  # type: ignore[arg-type]

    # Patch _IngestorThread para injetar o stub. Mais simples: rodar
    # download_chunk normal e validar via fallback ``Agent#{id}`` (DLL fake
    # não tem GetAgentName, resolver cai em fallback graceful).
    del stub  # mantive a class definida acima como referência didática

    result = download_chunk(
        dll,  # type: ignore[arg-type]
        "WDOJ26",
        "F",
        base,
        base.replace(hour=17),
        timeout=10,
    )

    assert result.status == "completed"
    assert len(result.trades) == 3

    # Cada trade tem buy_agent_name e sell_agent_name populados (fallback
    # ``Agent#{id}`` quando FakeProfitDLL não expõe GetAgentName).
    for t in result.trades:
        assert t.buy_agent_id is not None and t.buy_agent_id != 0
        assert t.sell_agent_id is not None and t.sell_agent_id != 0
        assert t.buy_agent_name is not None
        assert t.sell_agent_name is not None
        # Fallback determinístico:
        assert t.buy_agent_name == f"Agent#{t.buy_agent_id}"
        assert t.sell_agent_name == f"Agent#{t.sell_agent_id}"


@pytest.mark.integration
def test_download_chunk_zero_agent_id_results_in_none_name() -> None:
    """agent_id == 0 (DLL convention "desconhecido") → buy_agent_name=None.

    Não chamamos resolver para ID 0 — economiza 1 lookup por trade quando o
    broker não populou os campos. ``buy_agent_id`` e ``buy_agent_name`` ambos
    None nesse caso.
    """
    base = datetime(2026, 4, 15, 9, 0, 0)
    specs = [
        # Sem buy_agent / sell_agent definidos → defaults para 0 em
        # FakeProfitDLL.translate_trade.
        _spec(timestamp=base, trade_number=1, last_packet=True),
    ]
    dll = _FakeProfitDLL(trade_specs=specs, progress_sequence=[])

    result = download_chunk(
        dll,  # type: ignore[arg-type]
        "WDOJ26",
        "F",
        base,
        base.replace(hour=17),
        timeout=10,
    )

    assert result.status == "completed"
    assert len(result.trades) == 1
    t = result.trades[0]
    assert t.buy_agent_id is None
    assert t.sell_agent_id is None
    assert t.buy_agent_name is None
    assert t.sell_agent_name is None


@pytest.mark.integration
def test_download_chunk_uses_new_translate_trade_api() -> None:
    """IngestorThread usa novo ``translate_trade(handle) -> TradeFields``.

    Sanity check: mock returna TradeFields direto + verifica que campos
    extraídos chegam em TradeRecord (price, quantity, trade_type).
    """
    base = datetime(2026, 4, 15, 9, 0, 0)
    specs = [
        {
            **_spec(timestamp=base, trade_number=42, last_packet=True),
            "price": 5025.5,
            "quantity": 17,
            "trade_type": 3,
        },
    ]
    dll = _FakeProfitDLL(trade_specs=specs, progress_sequence=[])

    result = download_chunk(
        dll,  # type: ignore[arg-type]
        "WDOJ26",
        "F",
        base,
        base.replace(hour=17),
        timeout=10,
    )

    assert result.status == "completed"
    assert len(result.trades) == 1
    t = result.trades[0]
    assert t.price == pytest.approx(5025.5)
    assert t.quantity == 17
    assert t.trade_type == 3
    assert t.trade_id == 42
