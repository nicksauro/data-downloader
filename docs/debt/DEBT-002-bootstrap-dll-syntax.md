# DEBT-002 — bootstrap-dll.ps1: parse failure under Windows PowerShell 5.1 (no UTF-8 BOM + `$var:` interpolation)

| Field | Value |
|-------|-------|
| **Status** | RESOLVED 2026-05-03 |
| **Owner** | Gage (devops) |
| **Severity** | HIGH (blocked Story 0.1 validation step `pwsh -File scripts/bootstrap-dll.ps1`; script unusable on any Windows host without explicit PS 7) |
| **Detected by** | Story 0.1 validation run (Task #35) |
| **Resolved in** | Task #35 (this fix) |
| **Related** | DEBT-001 (same root cause family: Windows non-UTF-8 default encoding) |

---

## Problem

`scripts/bootstrap-dll.ps1` (8314 bytes, created in Story 0.1) failed to parse with multiple
syntax errors when executed via `pwsh -File scripts/bootstrap-dll.ps1` and via Windows
PowerShell 5.1. Sample of `Parser::ParseFile` output before fix:

```
135:28 - Referência de variável inválida. ':' não era seguido de um caractere de nome de variável válido.
        Considere usar ${} para delimitar o nome. [Token: $Category:]
140:53 - ')' de fechamento ausente na expressão.
147:23 - Token '[OK]' inesperado na expressão ou instrução.
152:28 - Referência de variável inválida (idem 135). [Token: $Category:]
184:54 - Argumento ausente na lista de parâmetros.
236:54 - A cadeia de caracteres não tem o terminador: ".
```

Script could not even reach the param block — every invocation died at parse time.

---

## Root cause (two independent bugs, both Windows-encoding-related)

### Bug A — Variable interpolation `$Category:`

In two interpolated strings inside `Copy-FileWithCheck`, the script wrote:

```powershell
$script:Errors += "$Category: $SourceName nao encontrado em $ProfitChartPath"
$script:Errors += "$Category: $SourceName falhou: $_"
```

PowerShell parses `$Category:` as a scope-qualified variable reference (e.g. `$global:foo`,
`$script:bar`). Since `Category` is not a valid scope name, the parser raises
"Referência de variável inválida". The fix is to delimit the variable name with braces:

```powershell
"${Category}: $SourceName nao encontrado em $ProfitChartPath"
"${Category}: $SourceName falhou: $_"
```

This is the canonical pattern documented by the parser itself ("Considere usar ${}").

### Bug B — File saved as UTF-8 *without* BOM

The file contained legitimate non-ASCII characters in comments and one banner string
(em-dashes and accented Portuguese: "Diretórios", "canônica", "Relatório", "— data-downloader").
The bytes were valid UTF-8 multi-byte sequences but the file had **no UTF-8 BOM**.

Windows PowerShell 5.1 (the system default on every Windows host, including this squad
host, see `$PSVersionTable.PSVersion = 5.1.19041.6456`) reads `.ps1` files as ANSI
(Windows-1252 in pt-BR locale) when no BOM is present. Multi-byte UTF-8 sequences then
mis-decode into mojibake characters that the tokenizer treats as identifier breaks,
causing cascading parse errors at every line containing accented characters.

PowerShell 7 (`pwsh`) defaults to UTF-8 for BOM-less files, so on a host with PS 7
**only Bug A** would surface. On a host with PS 5.1 only, *both* bugs surface and the
errors from Bug B mask the true source of Bug A. The squad host has only PS 5.1
installed (no `pwsh.exe` on PATH or in standard install paths), which is why the
original validation in Story 0.1 produced the confusing error cascade.

---

## Fix applied

### Bug A
Two `Edit` operations on `scripts/bootstrap-dll.ps1`:
- Line 135: `"$Category:` → `"${Category}:`
- Line 152: `"$Category:` → `"${Category}:`

No other interpolations in the file are affected (audited via `grep '\$[A-Za-z_][A-Za-z0-9_]*:'` —
returned only these two occurrences).

### Bug B
Re-saved `scripts/bootstrap-dll.ps1` with UTF-8 BOM (bytes `EF BB BF` prepended). File
content is byte-for-byte identical otherwise; size grew from 8314 to 8321 bytes (+3 BOM
bytes, +N for the two `${...}` braces). Now both PS 5.1 and PS 7 read the file as UTF-8.

---

## Validation

1. `[System.Management.Automation.Language.Parser]::ParseFile(...)` — returns 0 errors
   ("OK - no parse errors") under Windows PowerShell 5.1.19041.6456.
2. End-to-end smoke run with intentionally-invalid path:
   ```
   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\bootstrap-dll.ps1 \
     -ProfitChartPath C:\NoSuchPath_DryRunTest_12345
   ```
   exits 1 (expected) after printing the full banner including the em-dash and the
   `[ERRO] Caminho de origem nao existe:` validation message — proves the script
   parses, executes the param block, runs path validation, and prints all output
   correctly with the accented characters intact.
3. No logic changes: the canonical companion list (`$RequiredDlls`, `$RequiredDatFiles`,
   `$RequiredDirs`, `$OptionalDirs`) is byte-identical to the pre-fix version. Nelo's
   authority over the companions list is **not** touched by this fix.

---

## Lesson learned (process change)

**MANDATORY for all `.ps1` scripts under `scripts/`:**

1. **Save with UTF-8 BOM** when the file contains any non-ASCII character (comments,
   docstrings, Write-Host strings, ...). Windows PowerShell 5.1 is the de-facto
   target on every Windows squad host until PS 7 is universally installed; without
   BOM, accented chars mis-decode and parser fails on otherwise-valid scripts.
2. **Always brace `${var}` when followed by `:`** in interpolated strings. The colon
   is the scope-qualifier delimiter and `$var:literal` will be parsed as a
   (likely-invalid) scoped variable reference. Pattern to grep for:
   `\$[A-Za-z_][A-Za-z0-9_]*:` inside double-quoted strings.
3. **Validate every new `.ps1` with `Parser::ParseFile` before commit.** Quick check:
   ```powershell
   $errors = $null
   [System.Management.Automation.Language.Parser]::ParseFile(
     'scripts/<file>.ps1', [ref]$null, [ref]$errors
   ) | Out-Null
   if ($errors) { $errors | Format-List * }
   ```
   This catches both Bug A and Bug B without requiring the script to actually run
   (no side effects, no DLL prerequisites).

**Codification:** Consider adding a pre-commit hook `check_powershell_parse.py` that
runs `[Parser]::ParseFile` against every staged `.ps1` and blocks commit on any
parse error. Track as Story 0.2-followup.

**Cross-reference to DEBT-001:** Same root cause family — Windows defaults to non-UTF-8
encoding (cp1252 for Python on this locale, ANSI for PS 5.1), and squad code that does
not opt in explicitly to UTF-8 silently breaks. DEBT-001 codified the rule for Python
hooks (`encoding='utf-8'` mandatory). DEBT-002 extends the rule to PowerShell scripts
(UTF-8 BOM mandatory when non-ASCII present).

---

## Related references

- DEBT-001 — Pre-commit hooks: cp1252 UnicodeDecodeError on UTF-8 content
- Story 0.1 — Environment Bootstrap (introduced `bootstrap-dll.ps1`)
- ADR-008 — DLL Distribution Strategy (script's reason to exist)
- PowerShell docs — [about_Variables §Variables and scope](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_variables)
- PowerShell docs — [about_Parsing §The parsing modes and quoting](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_parsing)

— Gage, publicando com cuidado ⚙️
