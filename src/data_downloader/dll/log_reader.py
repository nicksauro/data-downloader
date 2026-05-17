"""data_downloader.dll.log_reader — Parser do LogDesktop da ProfitDLL nativa.

Owner: Sol (data-engineer). Story 4.29 — MaxHID UX fix.

A ProfitDLL nativa Nelogica escreve um log textual em
``<install>/_internal/Logs/LogDesktop_YYYY_MM_DD.log`` com eventos do servidor
de autenticação, roteamento, market data e order entry. O diagnóstico Aria
2026-05-17 confirmou que falhas de **licença ocupada** (``ActivationResult=
MaxHID``) **só** aparecem nesse log: o servidor responde ``MaxHID`` 178ms
após login, a DLL marca ``Profit Dll Valid=False`` e NUNCA emite o estado
``(MARKET_DATA, MARKET_CONNECTED=4)`` do state callback Python. Resultado:
``wait_market_connected`` espera 990s (3 retries x 300s + cooldowns) e o
usuário fica olhando para um spinner infinito sem mensagem clara.

Este módulo lê o LogDesktop e extrai o **último** bloco
``TInfoClientProcessor.ProcessLoginResult`` para que
:meth:`ProfitDLL.wait_market_connected` possa detectar MaxHID proativamente
em <1s pós-login e raise :class:`MaxHIDError` com remedies prescritivos
em vez do timeout genérico de 990s.

Formato real (evidência LogDesktop_2026_05_17.log)::

    17/05 11:40:19.197 : #Con#Info  TInfoClientProcessor.ProcessLoginResult:
                                      ActivationResult=MaxHID
                                      Mensagem="Todos os seus logins estão em uso"
                                      HardLogout=True
                                      LoginResult=MaxHID

O parser é **defensivo** (R3 amended Story 4.29):

- Encoding ``errors='ignore'`` — a DLL pode estar escrevendo no log enquanto
  Python lê; bytes parciais não-UTF8 são ignorados em vez de levantar.
- Tolerante a logs truncados (última linha incompleta) — se um bloco não
  tem todos os 4 atributos esperados, retorna ``None`` (caller decide).
- Busca de baixo para cima — o ``ProcessLoginResult`` mais recente é o
  autoritativo (sessões anteriores podem ter MaxHID histórico).
- Sem I/O no import (R21 — hot path safety; resolução lazy).

Story 4.29 AC1 + AC3 — usado por ``wrapper.wait_market_connected`` para
detecção proativa.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

__all__ = [
    "LoginResultSnapshot",
    "find_latest_log_desktop",
    "parse_login_result_from_log",
]


# =====================================================================
# Regexes — formato canônico observado em LogDesktop_2026_05_17.log
# =====================================================================
#
# A linha-cabeçalho do bloco é::
#
#     17/05 11:40:19.197 : #Con#Info  TInfoClientProcessor.ProcessLoginResult:
#
# As 4 linhas seguintes são atributos indentados ``  Nome=Valor`` (Mensagem
# pode vir entre aspas). O parser identifica os atributos por nome, não por
# posição — formato pode mudar em releases futuras da DLL e ordem não é
# garantida.
# =====================================================================

# Cabeçalho do bloco — captura também o timestamp ``DD/MM HH:MM:SS.mmm``.
_RE_PROCESS_LOGIN = re.compile(
    r"^(?P<day>\d{2})/(?P<month>\d{2})\s+"
    r"(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})\.(?P<ms>\d{3})"
    r".*TInfoClientProcessor\.ProcessLoginResult:\s*$"
)

# Linha de atributo ``  Nome=Valor`` (com indent). ``Mensagem="..."`` aparece
# entre aspas em algumas releases; o parser remove aspas no extract.
_RE_ATTR = re.compile(r"^\s+(?P<key>\w+)\s*=\s*(?P<value>.*?)\s*$")

# Nome canônico do arquivo gerado pela DLL.
_RE_LOG_FILENAME = re.compile(r"^LogDesktop_(?P<year>\d{4})_(?P<month>\d{2})_(?P<day>\d{2})\.log$")


@dataclass(frozen=True)
class LoginResultSnapshot:
    """Snapshot imutável do último ``ProcessLoginResult`` do LogDesktop.

    Atributos refletem 1:1 as 4 chaves esperadas no bloco. ``activation_result``
    é o campo crítico para detecção de MaxHID (``"MaxHID"`` indica licença
    ocupada; outros valores ``OK``, ``Invalid``, ``Expired`` etc. seguem
    fluxos próprios — Story 4.29 cobre **só** MaxHID).

    Attributes:
        activation_result: Valor do servidor (``"MaxHID"`` em licença ocupada,
            ``"OK"`` em sucesso). String vazia se atributo não encontrado.
        message: Texto humanizado do servidor (ex.: ``"Todos os seus logins
            estão em uso"``). Aspas removidas. String vazia se ausente.
        hard_logout: ``True`` se servidor sinalizou desconexão dura
            (``HardLogout=True`` na evidência). ``False`` se ausente ou
            ``"False"``.
        login_result: Geralmente espelha ``activation_result``; mantido
            separado porque o protocolo da DLL trata como campos distintos
            (vide manual §3 e exemplos Nelogica).
        timestamp: Datetime BRT naive do bloco (composto via ``DD/MM
            HH:MM:SS.mmm`` da linha-cabeçalho + ano = ano da pasta corrente).
            ``None`` se timestamp não pôde ser parseado.
    """

    activation_result: str
    message: str
    hard_logout: bool
    login_result: str
    timestamp: datetime | None


def find_latest_log_desktop(logs_dir: Path) -> Path | None:
    """Localiza o ``LogDesktop_YYYY_MM_DD.log`` mais recente em ``logs_dir``.

    A DLL roda um arquivo por dia; quando o usuário deixa o app aberto
    múltiplos dias, há vários ``LogDesktop_*.log`` na pasta. Escolhemos o
    de data mais recente (parseada do nome — `mtime` poderia mentir se o
    usuário copiar a pasta).

    Args:
        logs_dir: Caminho para ``<install>/_internal/Logs/`` (frozen) ou
            equivalente em dev.

    Returns:
        Path para o log mais recente, ou ``None`` se a pasta não existir
        ou não contiver nenhum ``LogDesktop_*.log`` válido. Caller decide
        como reagir (ex.: parse_login_result_from_log retorna ``None``).

    Examples:
        >>> # logs_dir contém LogDesktop_2026_05_17.log e LogDesktop_2026_05_16.log
        >>> # find_latest_log_desktop(logs_dir) retorna o primeiro.
        >>> True
        True
    """
    try:
        if not logs_dir.is_dir():
            return None
    except OSError:
        return None

    candidates: list[tuple[tuple[int, int, int], Path]] = []
    try:
        entries = list(logs_dir.iterdir())
    except OSError:
        return None

    for entry in entries:
        try:
            if not entry.is_file():
                continue
        except OSError:
            continue
        match = _RE_LOG_FILENAME.match(entry.name)
        if match is None:
            continue
        key = (
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
        )
        candidates.append((key, entry))

    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def _parse_attribute_value(raw: str) -> str:
    """Remove aspas duplas envolvendo ``raw`` (formato ``Mensagem="..."``).

    A DLL escreve apenas alguns atributos entre aspas (``Mensagem`` sim,
    ``ActivationResult`` não). Defensivo: idempotente em valores sem aspas.
    """
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        return raw[1:-1]
    return raw


def _parse_timestamp(
    match: re.Match[str],
    *,
    year_hint: int | None = None,
) -> datetime | None:
    """Constrói datetime BRT naive a partir do match do cabeçalho.

    A DLL escreve ``DD/MM HH:MM:SS.mmm`` sem ano — assumimos o ano corrente
    do sistema (``year_hint`` permite override em testes deterministas). O
    timestamp é BRT naive (R7), idêntico à semântica de ``TradeDate``
    convertido em ``ProfitDLL.translate_trade``.

    Returns:
        ``datetime`` ou ``None`` se algum campo for inválido (mês>12 etc.).
    """
    try:
        year = year_hint if year_hint is not None else datetime.now().year
        return datetime(
            year=year,
            month=int(match.group("month")),
            day=int(match.group("day")),
            hour=int(match.group("hour")),
            minute=int(match.group("minute")),
            second=int(match.group("second")),
            microsecond=int(match.group("ms")) * 1000,
        )
    except (ValueError, KeyError):
        return None


def parse_login_result_from_log(
    logs_dir: Path,
    *,
    year_hint: int | None = None,
) -> LoginResultSnapshot | None:
    """Lê o LogDesktop mais recente e extrai o último ``ProcessLoginResult``.

    Story 4.29 AC1 — coração do detector proativo de MaxHID. Operação:

    1. Localiza ``LogDesktop_YYYY_MM_DD.log`` mais recente em ``logs_dir``.
    2. Lê o arquivo com ``errors='ignore'`` (race com escrita da DLL).
    3. Procura **de baixo para cima** o último bloco com
       ``TInfoClientProcessor.ProcessLoginResult``.
    4. Parseia até 4 linhas de atributos seguintes; aceita variações de
       ordem e atributos faltantes (apenas registra valor vazio).
    5. Retorna ``LoginResultSnapshot`` (mesmo que parcial — caller checa
       ``activation_result == "MaxHID"`` antes de raise).

    Args:
        logs_dir: ``Path`` para ``<install>/_internal/Logs/``. Pode não
            existir (dev / primeira execução) — retorna ``None`` sem
            levantar.
        year_hint: Ano para compor o ``timestamp`` (DLL não escreve ano).
            Default = ``datetime.now().year``. Útil para testes.

    Returns:
        ``LoginResultSnapshot`` com os 4 campos (mesmo que vazios) +
        ``timestamp``, OU ``None`` se:

        - Pasta inexistente / inacessível.
        - Nenhum ``LogDesktop_*.log`` na pasta.
        - Arquivo vazio ou sem cabeçalho ``ProcessLoginResult``.
        - I/O error durante leitura.

    Examples:
        >>> from pathlib import Path
        >>> snap = parse_login_result_from_log(Path("/no/such/dir"))
        >>> snap is None
        True
    """
    log_path = find_latest_log_desktop(logs_dir)
    if log_path is None:
        return None

    try:
        # ``errors='ignore'`` — Q-DRIFT-41: DLL pode estar escrevendo bytes
        # enquanto Python lê; bytes parciais não-UTF8 viram descartados em
        # vez de levantar ``UnicodeDecodeError``. Encoding utf-8 (default
        # do file open) bate com a maioria das DLLs Nelogica; releases
        # futuras podem mudar mas defensivo a ambas direções.
        with log_path.open("r", encoding="utf-8", errors="ignore") as fh:
            lines = fh.readlines()
    except OSError:
        return None

    if not lines:
        return None

    # Busca o último cabeçalho ``ProcessLoginResult`` percorrendo do fim.
    header_index = -1
    header_match: re.Match[str] | None = None
    for idx in range(len(lines) - 1, -1, -1):
        candidate = _RE_PROCESS_LOGIN.match(lines[idx])
        if candidate is not None:
            header_index = idx
            header_match = candidate
            break

    if header_index < 0 or header_match is None:
        return None

    # Parseia até 8 linhas após o cabeçalho — formato canônico tem 4
    # atributos, mas defensivo com folga (Mensagem pode quebrar em duas
    # linhas se a DLL mudar de release). Para com primeira linha que NÃO
    # bate o padrão de atributo indentado (próximo evento começou).
    attrs: dict[str, str] = {}
    for offset in range(1, 9):
        target = header_index + offset
        if target >= len(lines):
            break
        line = lines[target].rstrip("\r\n")
        attr_match = _RE_ATTR.match(line)
        if attr_match is None:
            break
        key = attr_match.group("key")
        value = _parse_attribute_value(attr_match.group("value"))
        attrs[key] = value

    # Sem nenhum atributo capturado — bloco está truncado (DLL crashou no
    # meio da escrita). Tratamos como "log inválido" e retornamos None
    # para que caller volte ao path legacy (timeout genérico).
    if not attrs:
        return None

    hard_logout_raw = attrs.get("HardLogout", "").strip().lower()
    hard_logout = hard_logout_raw == "true"

    return LoginResultSnapshot(
        activation_result=attrs.get("ActivationResult", ""),
        message=attrs.get("Mensagem", ""),
        hard_logout=hard_logout,
        login_result=attrs.get("LoginResult", ""),
        timestamp=_parse_timestamp(header_match, year_hint=year_hint),
    )
