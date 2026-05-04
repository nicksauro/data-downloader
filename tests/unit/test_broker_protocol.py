"""Unit tests — broker.protocol (Story 4.1 AC2).

Cobertura:

- BrokerProtocol enum: valores estáveis, serialização pickle.
- BrokerRequest: criação, immutabilidade, pickle round-trip.
- BrokerResponse: success/failure semantics, data/error fields.
- BrokerTimeoutError: contém request_id + op + timeout no message.
"""

from __future__ import annotations

import pickle

import pytest

from data_downloader.orchestrator.broker.protocol import (
    BrokerProtocol,
    BrokerRequest,
    BrokerResponse,
    BrokerTimeoutError,
)


class TestBrokerProtocol:
    """BrokerProtocol enum stability."""

    def test_all_expected_ops_present(self) -> None:
        expected = {
            "register_partition",
            "register_gap",
            "update_job_progress",
            "register_job",
            "query_completed_partitions",
            "shutdown",
        }
        actual = {p.value for p in BrokerProtocol}
        assert actual == expected

    def test_protocol_is_string_enum(self) -> None:
        # Permite serialização limpa em logs e pickle.
        assert BrokerProtocol.REGISTER_PARTITION.value == "register_partition"
        assert isinstance(BrokerProtocol.REGISTER_PARTITION.value, str)

    def test_protocol_pickleable(self) -> None:
        op = BrokerProtocol.REGISTER_GAP
        restored = pickle.loads(pickle.dumps(op))
        assert restored is op


class TestBrokerRequest:
    """BrokerRequest dataclass."""

    def test_create_basic(self) -> None:
        req = BrokerRequest(
            request_id="abc123",
            op=BrokerProtocol.REGISTER_GAP,
            payload={"symbol": "WDOJ26"},
            worker_id="worker-0",
        )
        assert req.request_id == "abc123"
        assert req.op is BrokerProtocol.REGISTER_GAP
        assert req.payload == {"symbol": "WDOJ26"}
        assert req.worker_id == "worker-0"

    def test_default_payload_empty_dict(self) -> None:
        req = BrokerRequest(request_id="x", op=BrokerProtocol.SHUTDOWN)
        assert req.payload == {}

    def test_immutable(self) -> None:
        from dataclasses import FrozenInstanceError

        req = BrokerRequest(request_id="x", op=BrokerProtocol.SHUTDOWN)
        with pytest.raises(FrozenInstanceError):
            req.request_id = "y"  # type: ignore[misc]

    def test_pickle_round_trip(self) -> None:
        req = BrokerRequest(
            request_id="xyz",
            op=BrokerProtocol.REGISTER_PARTITION,
            payload={
                "write_result": {
                    "path": "/data/foo.parquet",
                    "row_count": 42,
                    "first_ts_ns": 1000,
                    "last_ts_ns": 2000,
                    "checksum_sha256": "deadbeef" * 8,
                    "file_size_bytes": 1024,
                },
                "partition": {"exchange": "F", "symbol": "WDOJ26", "year": 2026, "month": 4},
                "job_id": "job-abc",
            },
            worker_id="worker-1",
        )
        restored = pickle.loads(pickle.dumps(req))
        assert restored == req


class TestBrokerResponse:
    """BrokerResponse dataclass + semantics."""

    def test_success_response(self) -> None:
        resp = BrokerResponse(request_id="abc", success=True, data={"job_id": "x"})
        assert resp.success is True
        assert resp.data == {"job_id": "x"}
        assert resp.error is None
        assert resp.error_type is None

    def test_failure_response(self) -> None:
        resp = BrokerResponse(
            request_id="abc",
            success=False,
            error="Catalog rejected mutation",
            error_type="IntegrityError",
        )
        assert resp.success is False
        assert resp.error == "Catalog rejected mutation"
        assert resp.error_type == "IntegrityError"
        assert resp.data is None

    def test_pickle_round_trip(self) -> None:
        resp = BrokerResponse(
            request_id="xyz",
            success=True,
            data=[{"partition_path": "F/WDOJ26/2026/04.parquet"}],
        )
        restored = pickle.loads(pickle.dumps(resp))
        assert restored == resp


class TestBrokerTimeoutError:
    """BrokerTimeoutError diagnostic fields."""

    def test_carries_diagnostics(self) -> None:
        exc = BrokerTimeoutError(request_id="abc123", op="register_partition", timeout=10.0)
        assert exc.request_id == "abc123"
        assert exc.op == "register_partition"
        assert exc.timeout == 10.0
        assert "abc123" in str(exc)
        assert "register_partition" in str(exc)
        assert "10" in str(exc)

    def test_is_timeout_error_subclass(self) -> None:
        exc = BrokerTimeoutError(request_id="x", op="y", timeout=1.0)
        assert isinstance(exc, TimeoutError)
