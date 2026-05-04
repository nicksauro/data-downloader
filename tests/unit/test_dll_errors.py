"""tests/unit/test_dll_errors.py — Story 1.2.

Cobertura de ``data_downloader.dll.errors``:

- ``decode_nl_error(0)`` → NL_OK.
- ``decode_nl_error(NL_*)`` → nome simbólico.
- Códigos desconhecidos → ``NL_UNKNOWN_<code>`` (não levanta).
- ``DLLInitError.__str__`` formata corretamente.
"""

from __future__ import annotations

import pytest

from data_downloader.dll.errors import DLLInitError, decode_nl_error


@pytest.mark.unit
def test_decode_nl_error_zero_returns_nl_ok() -> None:
    """``decode_nl_error(0)`` retorna NL_OK com mensagem informativa."""
    info = decode_nl_error(0)
    assert info.code == 0
    assert info.name == "NL_OK"
    assert "sucesso" in info.message.lower()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("code", "expected_name"),
    [
        (-2147483647, "NL_INTERNAL_ERROR"),
        (-2147483646, "NL_NOT_INITIALIZED"),
        (-2147483393, "NL_INVALID_ARGS"),
        (-2147483392, "NL_NO_LICENSE"),
        (-2147483391, "NL_NO_LOGIN"),
        (-2147483390, "NL_INVALID_TICKER"),
        (-2147483389, "NL_EXCHANGE_UNKNOWN"),
        (-1, "DLL_SENTINEL"),
    ],
)
def test_decode_nl_error_known_codes_return_canonical_names(
    code: int,
    expected_name: str,
) -> None:
    """Códigos canônicos retornam o nome simbólico esperado."""
    info = decode_nl_error(code)
    assert info.code == code
    assert info.name == expected_name
    assert info.message  # mensagem não vazia


@pytest.mark.unit
def test_decode_nl_error_unknown_returns_synthetic_name_without_raising() -> None:
    """Códigos desconhecidos retornam ``NL_UNKNOWN_<code>`` em vez de raise."""
    # NÃO deve raise — comportamento defensivo para releases novas da DLL.
    info = decode_nl_error(99999)
    assert info.code == 99999
    assert info.name == "NL_UNKNOWN_99999"
    assert "desconhecido" in info.message.lower()

    # Negativo não-mapeado também:
    info2 = decode_nl_error(-12345)
    assert info2.code == -12345
    assert info2.name == "NL_UNKNOWN_-12345"


@pytest.mark.unit
def test_dllinit_error_str_format_canonical() -> None:
    """``DLLInitError.__str__`` formata como 'DLL init failed: NAME (code=X): msg'."""
    err = DLLInitError(
        code=-2147483393,
        name="NL_INVALID_ARGS",
        message="Argumentos inválidos passados à ProfitDLL.",
    )
    s = str(err)
    assert "DLL init failed" in s
    assert "NL_INVALID_ARGS" in s
    assert "code=-2147483393" in s
    assert "Argumentos inválidos" in s


@pytest.mark.unit
def test_dllinit_error_carries_code_name_message_attrs() -> None:
    """``DLLInitError`` expõe ``code``, ``name``, ``cause``, ``details``."""
    cause = ValueError("inner")
    err = DLLInitError(
        code=-1,
        name="COMPANIONS_MISSING",
        message="Companions ausentes",
        cause=cause,
        details={"missing": ["libssl.dll"]},
    )
    assert err.code == -1
    assert err.name == "COMPANIONS_MISSING"
    assert err.cause is cause
    assert err.details == {"missing": ["libssl.dll"]}
    # Hierarquia: subclasse de DataDownloaderError.
    from data_downloader.public_api.exceptions import DataDownloaderError

    assert isinstance(err, DataDownloaderError)


@pytest.mark.unit
def test_dllinit_error_re_export_from_dll_errors() -> None:
    """``DLLInitError`` é re-exportada de ``data_downloader.dll.errors`` (ergonomia)."""
    from data_downloader.dll.errors import DLLInitError as ReExported
    from data_downloader.public_api.exceptions import DLLInitError as Public

    assert ReExported is Public
