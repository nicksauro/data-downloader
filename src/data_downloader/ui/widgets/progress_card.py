"""data_downloader.ui.widgets.progress_card — Card de progresso do download.

Owner: Felix (frontend-dev) | Design: Uma (ux-design-expert).

**Status:** Epic 3 — TODO (placeholder skeleton, COUNCIL-12 prep).

Widget composto que aparece em estado **Loading** da DownloadScreen.
Encapsula barra de progresso, subtitle textual, log expansível e botão
CANCELAR.

Componentes (Felix Story 3.2):

    - **Label "Contrato atual"** — atualizado a cada ``progress`` recebido
      (M16 — ``current_contract`` em DownloadProgress).
    - **QProgressBar** com property dinâmica ``state``:
        - ``state="normal"`` → cor ``accent.cyan`` #3DD0E1
        - ``state="reconnecting"`` → cor ``warning.yellow`` #F2C94C
          (quirk 99% — Flow 4)
        - ``state="cancelling"`` → cor ``warning.yellow`` + spinner
        - ``state="complete"`` → cor ``success.green`` #3FCB6F
    - **Subtitle textual** — varia por state:
        - normal: ``INF_FETCHING_CHUNK`` ("Chunk {x} de {y}")
        - reconnecting: ``WAR_99_RECONNECT`` (texto literal canônico)
        - cancelling: ``INF_GRACEFUL_SHUTDOWN``
    - **Stats line** — "{x}/{y} • {elapsed} • ~{remaining}".
    - **Log expansível** ("▸ Detalhes" / "▾ Detalhes") — mostra ``INF_*``
      events com timestamps em monospace 13px text.muted.
    - **Botão CANCELAR** — ``BTN_CANCEL`` cor ``error.red``; tooltip
      varia por state (durante reconnect: ``TIP_CANCEL_DURING_RECONNECT``).
    - **Spinner** — ``QMovie`` (animado) ao lado da barra durante
      reconnecting/cancelling.

Sinais (Felix define no Adapter; este card é consumidor):

    - ``progress(DownloadProgress)`` → ``set_progress()``
    - ``state_changed(str)`` → ``set_state()``
    - clique CANCELAR → emite signal próprio ``cancel_requested``

Microcopy referenced:
    - ``LBL_CURRENT_CONTRACT`` — label do contrato
    - ``INF_FETCHING_CHUNK``, ``INF_GRACEFUL_SHUTDOWN``
    - ``WAR_99_RECONNECT`` (literal canônico — MICROCOPY §18)
    - ``BTN_CANCEL``, ``TIP_BTN_CANCEL``, ``TIP_CANCEL_DURING_RECONNECT``
    - ``BTN_DETAILS`` / ``BTN_DETAILS_HIDE``
    - ``TIP_PROGRESS_DETAILS``

Referências:
    - docs/ux/WIREFRAMES.md (DownloadScreen — estados Loading + sub-estados)
    - docs/ux/FLOWS.md (Flow 4 — quirk 99% reconnect)
    - docs/ux/MICROCOPY_CATALOG.md §18 (texto WAR_99_RECONNECT canônico)
    - docs/ux/THEME.md §3 (cores progress bar por state)
    - docs/ux/QT_PATTERNS.md §2.4 (current_contract M16)
    - docs/decisions/COUNCIL-12-epic3-prep.md
"""

from __future__ import annotations

__all__ = ["ProgressCard"]


class ProgressCard:
    """Placeholder — Epic 3 Story 3.2 implementa ``QWidget`` real.

    Visualiza progresso de download com state property (cor barra muda
    automaticamente). Sub-estado reconnecting mostra texto LITERAL
    ``WAR_99_RECONNECT`` (proibido editar — autorização Uma + Nelo).
    """

    def __init__(self) -> None:
        raise NotImplementedError(
            "Epic 3 — Story 3.2 implementa ProgressCard. "
            "Veja docs/ux/WIREFRAMES.md + Flow 4 + COUNCIL-12."
        )
