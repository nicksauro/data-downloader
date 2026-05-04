"""Unit tests — broker.worker_client (Story 4.1 AC2 + AC4).

Cobertura:

- BrokerCatalogClient.register_job: envia REGISTER_JOB + recebe ACK + retorna job_id.
- BrokerCatalogClient.register_partition: serialize WriteResult + payload OK.
- BrokerCatalogClient.register_gap: payload com ISO timestamps.
- BrokerCatalogClient.update_job_progress: subset de kwargs.
- ACK error: BrokerResponse(success=False) → raise IntegrityError.
- Timeout: ACK não chega → BrokerTimeoutError.
- Out-of-order ACK: re-enqueued + correto eventualmente retornado.

Mock broker: responde via thread separada (simula CatalogBroker rodando).
Usa queue.Queue (in-process) em vez de mp.Queue para simplicidade —
contrato é o mesmo (put/get com timeout).
"""

from __future__ import annotations

import queue
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest

from data_downloader.orchestrator.broker.protocol import (
    BrokerProtocol,
    BrokerRequest,
    BrokerResponse,
    BrokerTimeoutError,
)
from data_downloader.orchestrator.broker.worker_client import BrokerCatalogClient
from data_downloader.public_api.exceptions import IntegrityError
from data_downloader.storage.parquet_writer import WriteResult
from data_downloader.storage.partition import PartitionKey


def _drive_broker(
    mutation_q: queue.Queue,
    response_q: queue.Queue,
    *,
    success: bool = True,
    data: object = None,
    error: str | None = None,
    error_type: str | None = None,
    delay_s: float = 0.0,
) -> threading.Thread:
    """Mock broker: lê 1 request da mutation_q, devolve response controlado."""

    def runner() -> None:
        req = mutation_q.get(timeout=5.0)
        if delay_s > 0:
            time.sleep(delay_s)
        if req.op == BrokerProtocol.REGISTER_JOB:
            response_q.put(
                BrokerResponse(
                    request_id=req.request_id,
                    success=success,
                    data=data if data is not None else {"job_id": "mock-job"},
                    error=error,
                    error_type=error_type,
                )
            )
        else:
            response_q.put(
                BrokerResponse(
                    request_id=req.request_id,
                    success=success,
                    data=data,
                    error=error,
                    error_type=error_type,
                )
            )

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    return t


class TestRegisterJob:
    def test_returns_job_id_on_success(self) -> None:
        mut_q: queue.Queue = queue.Queue()
        resp_q: queue.Queue = queue.Queue()
        client = BrokerCatalogClient(mut_q, resp_q, "worker-0", timeout=2.0)

        _drive_broker(mut_q, resp_q, data={"job_id": "job-xyz"})

        result = client.register_job(
            symbol="WDOJ26",
            exchange="F",
            requested_start=datetime(2026, 4, 1, 9),
            requested_end=datetime(2026, 4, 1, 17),
        )
        assert result == "job-xyz"

    def test_raises_on_malformed_response_data(self) -> None:
        mut_q: queue.Queue = queue.Queue()
        resp_q: queue.Queue = queue.Queue()
        client = BrokerCatalogClient(mut_q, resp_q, "worker-0", timeout=2.0)

        # data não é dict com job_id.
        _drive_broker(mut_q, resp_q, data="garbage")

        with pytest.raises(IntegrityError, match="malformed"):
            client.register_job(
                symbol="WDOJ26",
                exchange="F",
                requested_start=datetime(2026, 4, 1),
                requested_end=datetime(2026, 4, 2),
            )

    def test_payload_uses_iso_timestamps(self) -> None:
        mut_q: queue.Queue = queue.Queue()
        resp_q: queue.Queue = queue.Queue()
        client = BrokerCatalogClient(mut_q, resp_q, "worker-0", timeout=2.0)

        # Captura request enviado.
        captured: dict[str, BrokerRequest] = {}

        def runner() -> None:
            req = mut_q.get(timeout=5.0)
            captured["req"] = req
            resp_q.put(
                BrokerResponse(
                    request_id=req.request_id,
                    success=True,
                    data={"job_id": "x"},
                )
            )

        t = threading.Thread(target=runner, daemon=True)
        t.start()

        client.register_job(
            symbol="WDOJ26",
            exchange="F",
            requested_start=datetime(2026, 4, 1, 9, 30),
            requested_end=datetime(2026, 4, 1, 17, 0),
        )
        t.join(timeout=3.0)

        req = captured["req"]
        assert req.op is BrokerProtocol.REGISTER_JOB
        assert req.payload["requested_start_iso"] == "2026-04-01T09:30:00"
        assert req.payload["requested_end_iso"] == "2026-04-01T17:00:00"
        assert req.worker_id == "worker-0"


class TestRegisterPartition:
    def test_serializes_write_result(self) -> None:
        mut_q: queue.Queue = queue.Queue()
        resp_q: queue.Queue = queue.Queue()
        client = BrokerCatalogClient(mut_q, resp_q, "worker-0", timeout=2.0)

        captured: dict[str, BrokerRequest] = {}

        def runner() -> None:
            req = mut_q.get(timeout=5.0)
            captured["req"] = req
            resp_q.put(BrokerResponse(request_id=req.request_id, success=True))

        t = threading.Thread(target=runner, daemon=True)
        t.start()

        wr = WriteResult(
            path=Path("/data/F/WDOJ26/2026/04.parquet"),
            row_count=100,
            first_ts_ns=1_000,
            last_ts_ns=2_000,
            checksum_sha256="a" * 64,
            file_size_bytes=2048,
        )
        pk = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=4)

        client.register_partition(wr, pk, job_id="job-1")
        t.join(timeout=3.0)

        req = captured["req"]
        assert req.op is BrokerProtocol.REGISTER_PARTITION
        # Path serializado como str.
        assert isinstance(req.payload["write_result"]["path"], str)
        assert req.payload["write_result"]["row_count"] == 100
        assert req.payload["partition"]["symbol"] == "WDOJ26"
        assert req.payload["job_id"] == "job-1"


class TestRegisterGap:
    def test_iso_timestamps_in_payload(self) -> None:
        mut_q: queue.Queue = queue.Queue()
        resp_q: queue.Queue = queue.Queue()
        client = BrokerCatalogClient(mut_q, resp_q, "worker-0", timeout=2.0)

        captured: dict[str, BrokerRequest] = {}

        def runner() -> None:
            req = mut_q.get(timeout=5.0)
            captured["req"] = req
            resp_q.put(BrokerResponse(request_id=req.request_id, success=True))

        threading.Thread(target=runner, daemon=True).start()

        client.register_gap(
            symbol="WDOJ26",
            exchange="F",
            gap_start=datetime(2026, 4, 1),
            gap_end=datetime(2026, 4, 2),
            reason="no_trades",
        )

        # Aguarda processamento.
        time.sleep(0.05)

        req = captured["req"]
        assert req.op is BrokerProtocol.REGISTER_GAP
        assert req.payload["gap_start_iso"] == "2026-04-01T00:00:00"
        assert req.payload["reason"] == "no_trades"


class TestUpdateJobProgress:
    def test_only_provided_kwargs_in_payload(self) -> None:
        mut_q: queue.Queue = queue.Queue()
        resp_q: queue.Queue = queue.Queue()
        client = BrokerCatalogClient(mut_q, resp_q, "worker-0", timeout=2.0)

        captured: dict[str, BrokerRequest] = {}

        def runner() -> None:
            req = mut_q.get(timeout=5.0)
            captured["req"] = req
            resp_q.put(BrokerResponse(request_id=req.request_id, success=True))

        threading.Thread(target=runner, daemon=True).start()

        client.update_job_progress(
            "job-1",
            status="completed",
            trades_count=42,
        )
        time.sleep(0.05)

        payload = captured["req"].payload
        assert payload["job_id"] == "job-1"
        assert payload["status"] == "completed"
        assert payload["trades_count"] == 42
        # actual_start/actual_end não devem aparecer.
        assert "actual_start_iso" not in payload
        assert "actual_end_iso" not in payload


class TestErrorHandling:
    def test_raises_integrity_error_on_failure_response(self) -> None:
        mut_q: queue.Queue = queue.Queue()
        resp_q: queue.Queue = queue.Queue()
        client = BrokerCatalogClient(mut_q, resp_q, "worker-0", timeout=2.0)

        _drive_broker(
            mut_q,
            resp_q,
            success=False,
            error="reason already registered",
            error_type="IntegrityError",
        )

        with pytest.raises(IntegrityError, match="reason already registered"):
            client.register_gap(
                symbol="WDOJ26",
                exchange="F",
                gap_start=datetime(2026, 4, 1),
                gap_end=datetime(2026, 4, 2),
                reason="no_trades",
            )

    def test_raises_integrity_error_for_unknown_error_type(self) -> None:
        mut_q: queue.Queue = queue.Queue()
        resp_q: queue.Queue = queue.Queue()
        client = BrokerCatalogClient(mut_q, resp_q, "worker-0", timeout=2.0)

        _drive_broker(
            mut_q,
            resp_q,
            success=False,
            error="db corrupted",
            error_type="OperationalError",
        )

        with pytest.raises(IntegrityError) as exc_info:
            client.register_gap(
                symbol="WDOJ26",
                exchange="F",
                gap_start=datetime(2026, 4, 1),
                gap_end=datetime(2026, 4, 2),
                reason="no_trades",
            )
        assert "OperationalError" in str(exc_info.value)
        assert "db corrupted" in str(exc_info.value)


class TestTimeout:
    def test_raises_broker_timeout_when_no_ack(self) -> None:
        mut_q: queue.Queue = queue.Queue()
        resp_q: queue.Queue = queue.Queue()
        client = BrokerCatalogClient(mut_q, resp_q, "worker-0", timeout=0.5)

        # NÃO inicia broker mock — request fica sem ACK.
        with pytest.raises(BrokerTimeoutError) as exc_info:
            client.register_gap(
                symbol="WDOJ26",
                exchange="F",
                gap_start=datetime(2026, 4, 1),
                gap_end=datetime(2026, 4, 2),
                reason="no_trades",
            )
        assert exc_info.value.timeout == 0.5
        assert exc_info.value.op == "register_gap"


class TestOutOfOrderAcks:
    def test_requeues_other_acks_until_correct_one_arrives(self) -> None:
        mut_q: queue.Queue = queue.Queue()
        resp_q: queue.Queue = queue.Queue()
        client = BrokerCatalogClient(mut_q, resp_q, "worker-0", timeout=2.0)

        def runner() -> None:
            req = mut_q.get(timeout=5.0)
            # Coloca um ACK com request_id ERRADO PRIMEIRO.
            resp_q.put(
                BrokerResponse(
                    request_id="not-the-right-one",
                    success=True,
                    data={"job_id": "noise"},
                )
            )
            # Pequeno delay para forçar o waiter a buffer/re-enqueue.
            time.sleep(0.05)
            # Agora o ACK correto.
            resp_q.put(
                BrokerResponse(
                    request_id=req.request_id,
                    success=True,
                    data={"job_id": "correct-one"},
                )
            )

        threading.Thread(target=runner, daemon=True).start()

        result = client.register_job(
            symbol="WDOJ26",
            exchange="F",
            requested_start=datetime(2026, 4, 1),
            requested_end=datetime(2026, 4, 2),
        )
        assert result == "correct-one"

        # ACK out-of-order foi re-enfileirado; verifica que está lá.
        leftover = resp_q.get(timeout=1.0)
        assert leftover.request_id == "not-the-right-one"
