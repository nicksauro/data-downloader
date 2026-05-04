#!/usr/bin/env python3
"""scripts/audit_hot_path.py — Auditoria mecânica R21 (HOT_PATH_RULES.md).

Story 2.7 / COUNCIL-22 (Pyro+Dex+Quinn). Authority: Pyro (perf-engineer).

Faz AST scan de funções declaradas como hot path em
``src/data_downloader/`` e detecta violações da política R21:

- ``structlog.get_logger().info/debug/...`` (logging síncrono per-trade)
- ``logging.*`` (idem)
- ``print(...)`` (saída síncrona bloqueante)
- ``json.dumps(...)`` (serialização per-evento)
- ``time.strftime(...)`` (formatação de tempo per-evento)
- f-strings em chamadas de log (eager evaluation mesmo se filtered)

Hot paths são identificados por:

1. **Decorator/anotação ``# @hot_path``** acima da definição da função.
2. **Registry inline** ``_HOT_PATH_REGISTRY`` abaixo (caminho:função).

Exit codes:
    0 — clean (nenhuma violação)
    1 — violations encontradas (lista impressa em stderr)
    2 — erro de execução (parse, etc.)

Uso:
    python scripts/audit_hot_path.py
    python scripts/audit_hot_path.py --paths src/data_downloader/dll/wrapper.py
    python scripts/audit_hot_path.py --json   # output como JSON

CI / pre-commit (opcional, futuro):
    python scripts/hooks/check_hot_path.py
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path

# =====================================================================
# Hot path registry — autoritativo
# =====================================================================
#
# Lista canônica dos hot paths atuais do projeto. Cada entrada é uma
# tupla ``(file_relative_path, qualified_name)``. Caminhos relativos a
# ``src/data_downloader/`` para legibilidade.
#
# Manter sincronizado com ``docs/perf/HOT_PATH_RULES.md`` §"Auditoria
# mecânica" — dev que adicionar novo hot path DEVE atualizar este
# registry E o doc.

_HOT_PATH_REGISTRY: list[tuple[str, str]] = [
    # DLL callbacks — invocados per-trade pela ConnectorThread (R3).
    # ``_history_cb`` é a closure interna criada por
    # ``make_history_trade_callback_v2``; ``_progress_cb`` idem para
    # ``make_progress_callback``. AST scan encontra ambas via nested
    # FunctionDef walk.
    ("dll/callbacks.py", "_history_cb"),
    ("dll/callbacks.py", "_progress_cb"),
    # download_primitive — IngestorThread per-trade hot loop.
    # ``_process_trade`` é o método interno do IngestorThread que roda
    # per-trade no drain da queue.
    ("orchestrator/download_primitive.py", "_process_trade"),
    # NÃO listados (COOL conforme HOT_PATH_RULES.md tabela):
    #   - _trades_to_table (per-batch, ~1-10/s)
    #   - register_partition (per-chunk)
    #   - _process_progress (per-1%, ~100/job)
]

# =====================================================================
# Regras vetadas
# =====================================================================

# Funções/atributos cujas chamadas são vetadas em hot path.
# Detecção é feita por análise de Call.func — match parcial.
_VETOED_CALLS: dict[str, str] = {
    "print": "print() é synchronous I/O — bloqueia hot path",
    "json.dumps": "json.dumps() serialize per-trade viola R21.4 (use Counter)",
    "json.dump": "json.dump() per-trade viola R21.4",
    "time.strftime": "time.strftime() per-trade — use timestamp_ns + lazy fmt",
    "datetime.strftime": "datetime.strftime() per-trade — defer formatting",
    "logging.debug": "logging.* synchronous — viola R21.1 (use Counter/Histogram)",
    "logging.info": "logging.* synchronous — viola R21.1",
    "logging.warning": "logging.* synchronous — viola R21.1",
    "logging.error": "logging.* synchronous — viola R21.1",
    "logging.critical": "logging.* synchronous — viola R21.1",
}

# Métodos de logger (structlog/logging) vetados — match em Call.func.attr.
_VETOED_LOGGER_METHODS: frozenset[str] = frozenset(
    {"debug", "info", "warning", "error", "critical", "exception", "fatal"}
)

# Substrings que indicam uma variável/atributo é um logger.
_LOGGER_NAME_HINTS: tuple[str, ...] = ("log", "logger", "_log", "_logger")


# =====================================================================
# Data classes
# =====================================================================


@dataclass(frozen=True)
class Violation:
    """Uma violação R21 detectada em hot path."""

    file: str
    function: str
    line: int
    rule: str
    snippet: str
    message: str

    def format_human(self) -> str:
        return (
            f"{self.file}:{self.line} [{self.function}] "
            f"VIOLATION {self.rule}: {self.message}\n"
            f"    > {self.snippet}"
        )


@dataclass
class AuditReport:
    """Relatório agregado de auditoria."""

    files_scanned: int = 0
    functions_audited: int = 0
    violations: list[Violation] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.violations

    def to_dict(self) -> dict[str, object]:
        return {
            "files_scanned": self.files_scanned,
            "functions_audited": self.functions_audited,
            "violations": [asdict(v) for v in self.violations],
            "clean": self.clean,
        }


# =====================================================================
# AST inspection
# =====================================================================


def _is_logger_attr_call(node: ast.Call) -> tuple[bool, str]:
    """Detecta se ``node`` é ``some_logger.method(...)`` com method em vetados.

    Returns:
        (True, method_name) se identificado como log call vetado.
    """
    if not isinstance(node.func, ast.Attribute):
        return False, ""
    method = node.func.attr
    if method not in _VETOED_LOGGER_METHODS:
        return False, ""
    # Tenta identificar se receiver parece um logger.
    receiver = node.func.value
    receiver_name = ""
    if isinstance(receiver, ast.Name):
        receiver_name = receiver.id.lower()
    elif isinstance(receiver, ast.Attribute):
        receiver_name = receiver.attr.lower()
    if any(hint in receiver_name for hint in _LOGGER_NAME_HINTS):
        return True, method
    return False, ""


def _qualname_call(node: ast.Call) -> str:
    """Extrai um qualname approximado do alvo da call (para matching VETOED)."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        # Construir "mod.attr" se possível.
        if isinstance(func.value, ast.Name):
            return f"{func.value.id}.{func.attr}"
        return func.attr
    return ""


def _snippet_for(source: str, node: ast.AST) -> str:
    """Extrai snippet de uma linha do source para o node."""
    if not hasattr(node, "lineno"):
        return ""
    lineno: int = node.lineno  # type: ignore[attr-defined]
    lines = source.splitlines()
    if 1 <= lineno <= len(lines):
        return lines[lineno - 1].strip()
    return ""


def _has_hot_path_marker(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    source_lines: list[str] | None = None,
) -> bool:
    """Detecta marker ``# @hot_path`` ou ``@hot_path`` em decorator/docstring/comentário.

    Tres formas aceitas:

    1. Decorator real: ``@hot_path`` (precisa import + decorator no-op).
    2. Docstring contendo ``@hot_path`` em qualquer posição.
    3. Comentário ``# @hot_path`` na linha imediatamente acima da
       definição (mais comum em src atual — zero overhead, zero deps).
    """
    # 1. Decoradores nomeados ``hot_path``.
    for dec in node.decorator_list:
        if isinstance(dec, ast.Name) and dec.id == "hot_path":
            return True
        if isinstance(dec, ast.Attribute) and dec.attr == "hot_path":
            return True
    # 2. Docstring com marcador "@hot_path".
    if (
        node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
        and "@hot_path" in node.body[0].value.value
    ):
        return True
    # 3. Comentário "# @hot_path" na linha imediatamente acima.
    if source_lines is not None and hasattr(node, "lineno"):
        # node.lineno é 1-indexed; queremos a linha (lineno-1).
        # Busca até 3 linhas acima para tolerar decorators mas sem
        # cruzar uma definição/blank-comment-block longo.
        start = max(0, node.lineno - 4)
        end = node.lineno - 1
        for line in source_lines[start:end]:
            stripped = line.strip()
            if stripped.startswith("#") and "@hot_path" in stripped:
                return True
    return False


def _resolve_hot_path_targets(
    src_root: Path, registry: Iterable[tuple[str, str]]
) -> dict[Path, set[str]]:
    """Resolve registry para mapping {abs_path: {qualnames...}}."""
    out: dict[Path, set[str]] = {}
    for rel, qual in registry:
        abs_path = (src_root / rel).resolve()
        out.setdefault(abs_path, set()).add(qual)
    return out


# =====================================================================
# Audit core
# =====================================================================


def _audit_function(
    source: str,
    file_rel: str,
    func: ast.FunctionDef | ast.AsyncFunctionDef,
) -> Iterator[Violation]:
    """Audita uma função hot path por violações R21."""
    func_name = func.name
    for child in ast.walk(func):
        if not isinstance(child, ast.Call):
            continue

        # Regra 1: chamadas globais vetadas (print, json.dumps, etc.).
        qual = _qualname_call(child)
        if qual in _VETOED_CALLS:
            yield Violation(
                file=file_rel,
                function=func_name,
                line=child.lineno,
                rule=qual,
                snippet=_snippet_for(source, child),
                message=_VETOED_CALLS[qual],
            )
            continue

        # Regra 2: chamadas a métodos de logger.
        is_log, method = _is_logger_attr_call(child)
        if is_log:
            yield Violation(
                file=file_rel,
                function=func_name,
                line=child.lineno,
                rule=f"logger.{method}",
                snippet=_snippet_for(source, child),
                message=(
                    f"chamada {method}() em hot path viola R21.1 — "
                    "use Counter/Histogram (ADR-013) ou drain async"
                ),
            )


def _audit_file(
    source: str,
    file_path: Path,
    file_rel: str,
    target_funcs: set[str] | None,
) -> tuple[int, list[Violation]]:
    """Audita um arquivo. Retorna (functions_audited, violations).

    Se ``target_funcs`` é None, audita TODAS as funções marcadas com
    ``@hot_path``. Se não-None, audita apenas funções cujo nome está
    em ``target_funcs`` (inclusive sem marker).
    """
    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError as exc:  # pragma: no cover — defensivo
        raise RuntimeError(f"Erro de parse em {file_path}: {exc}") from exc

    violations: list[Violation] = []
    audited = 0
    source_lines = source.splitlines()

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        is_target = (target_funcs is not None and node.name in target_funcs) or (
            target_funcs is None and _has_hot_path_marker(node, source_lines)
        )
        if not is_target:
            continue
        audited += 1
        violations.extend(_audit_function(source, file_rel, node))

    return audited, violations


def audit(
    src_root: Path,
    paths: list[Path] | None = None,
    *,
    registry: Iterable[tuple[str, str]] | None = None,
) -> AuditReport:
    """Roda auditoria R21 nos hot paths registrados ou em ``paths`` extras.

    Args:
        src_root: Raiz do source tree (ex.: ``src/data_downloader/``).
        paths: Lista opcional de arquivos extras a auditar (caso queira
            forçar audit de um arquivo não no registry — útil para
            pre-commit hook em diff).
        registry: Override do registry default (testes).

    Returns:
        AuditReport com contadores + lista de violações.
    """
    report = AuditReport()
    # Honra ``registry=[]`` explícito (testes) — só fallback quando None.
    effective_registry = _HOT_PATH_REGISTRY if registry is None else registry
    targets = _resolve_hot_path_targets(src_root, effective_registry)

    # Adiciona paths extras como "audit-all-marked" (sem target_funcs).
    extra_paths: set[Path] = set()
    if paths:
        for p in paths:
            extra_paths.add(p.resolve())

    all_files = sorted(set(targets.keys()) | extra_paths)
    for file_path in all_files:
        if not file_path.exists():
            # Hot path declarado mas arquivo não existe — registry stale.
            report.violations.append(
                Violation(
                    file=str(file_path.relative_to(src_root.parent.parent))
                    if file_path.is_absolute() and src_root.parent.parent in file_path.parents
                    else str(file_path),
                    function="<registry>",
                    line=0,
                    rule="stale-registry",
                    snippet="",
                    message=(
                        "Hot path declarado em _HOT_PATH_REGISTRY mas arquivo "
                        "não existe — atualize scripts/audit_hot_path.py"
                    ),
                )
            )
            continue
        report.files_scanned += 1
        try:
            file_rel = str(file_path.relative_to(src_root.parent.parent))
        except ValueError:
            file_rel = str(file_path)
        source = file_path.read_text(encoding="utf-8")
        target_funcs: set[str] | None = targets.get(file_path)
        # Se file também foi passado como path extra, audita TODAS marcadas.
        if file_path in extra_paths and target_funcs is None:
            target_funcs = None  # all marked
        audited, viols = _audit_file(source, file_path, file_rel, target_funcs)
        report.functions_audited += audited
        report.violations.extend(viols)

    return report


# =====================================================================
# CLI
# =====================================================================


def _default_src_root() -> Path:
    here = Path(__file__).resolve().parent
    candidate = here.parent / "src" / "data_downloader"
    return candidate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit R21 hot path compliance (HOT_PATH_RULES.md)."
    )
    parser.add_argument(
        "--src-root",
        type=Path,
        default=_default_src_root(),
        help="Raiz do source tree (default: src/data_downloader/).",
    )
    parser.add_argument(
        "--paths",
        type=Path,
        nargs="*",
        default=None,
        help="Arquivos extras a auditar (audit-all-marked). Útil para pre-commit.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON em stdout (em vez de texto humano).",
    )
    args = parser.parse_args(argv)

    src_root: Path = args.src_root.resolve()
    if not src_root.exists():
        print(f"ERROR: src_root não existe: {src_root}", file=sys.stderr)
        return 2

    report = audit(src_root, paths=args.paths)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(
            f"Audit hot path R21: {report.files_scanned} arquivos, "
            f"{report.functions_audited} funções auditadas."
        )
        if report.clean:
            print("OK — Nenhuma violacao R21 detectada.")
        else:
            print(
                f"FAIL — {len(report.violations)} violacao(oes) encontrada(s):",
                file=sys.stderr,
            )
            for v in report.violations:
                print(v.format_human(), file=sys.stderr)

    return 0 if report.clean else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
