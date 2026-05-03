# DEBT-001 — Pre-commit hooks: cp1252 UnicodeDecodeError on UTF-8 content

| Field | Value |
|-------|-------|
| **Status** | RESOLVED 2026-05-03 |
| **Owner** | Gage (devops) |
| **Severity** | CRITICAL (blocked normal git workflow; forced 3 consecutive `--no-verify` commits) |
| **Detected by** | Pyro (perf-engineer) during F821 hotfix |
| **Resolved in** | Task #38 (this fix) |
| **Related commits** | f014848, 6c6ec4d, 0c1ff42 (all used `--no-verify` due to this bug) |

---

## Problem

Hook `scripts/hooks/check_no_dotenv.py` (created in Story 0.2) crashed with:

```
UnicodeDecodeError: 'charmap' codec can't decode byte 0x9d in position 6977:
character maps to <undefined>
```

whenever a staged file contained UTF-8 multi-byte sequences (em-dash `—` = `0xE2 0x80 0x94`,
which decodes to `\x9d` under cp1252). Since virtually every squad markdown file (PRD,
manifest, ADRs, stories) uses em-dashes, the hook crashed on essentially every commit.

The crash forced 3 consecutive commits to use `--no-verify`:
- `f014848` (Story 0.4 — CodeRabbit Opção B)
- `6c6ec4d` (docs: backfill SHA in Story 0.4 AUDIT)
- `0c1ff42` (hotfix: F821 in benchmarks)

This is a CRITICAL operational hazard: `--no-verify` bypasses ALL pre-commit checks
(secret detection, lint, conventional commit format), creating a culture where the gate
is routinely skipped because "the gate itself is broken."

---

## Root cause

Python's `subprocess.run(..., text=True)` decodes the subprocess stdout using the host's
preferred locale encoding. On Windows, this is cp1252 by default (verified:
`locale.getpreferredencoding() == 'cp1252'`).

When `git show :path/to/file.md` outputs UTF-8 bytes (the canonical encoding for git
blobs), Python's stdout reader thread crashes attempting to decode them as cp1252.

The hook was written without explicit `encoding=` parameter to `subprocess.run()`, so
behavior is host-locale-dependent — broken on Windows, accidentally functional on Linux
CI (where locale is usually UTF-8).

---

## Fix applied

Force `encoding='utf-8', errors='replace'` on every `subprocess.run()` call that captures
text output, in every hook under `scripts/hooks/`.

### Files patched

| Hook | Subprocess calls fixed |
|------|------------------------|
| `check_no_dotenv.py` | 2 (`staged_files()`, `staged_blob()`) |
| `check_dll_story_ref.py` | 1 (`staged_files()`) |
| `gage_pre_push_gate.py` | 2 (`commits_in_range()`, `working_tree_clean()`) |

### Files audited and OK (no fix needed)

| Hook | Reason |
|------|--------|
| `check_no_print.py` | Only uses `Path.read_text(encoding="utf-8", errors="replace")` — already explicit |
| `check_conventional_commit.py` | Only uses `Path.read_text(encoding="utf-8", errors="replace")` — already explicit |

### Secondary fix (same hook)

`check_no_dotenv.py` docstring contained a literal example matching the hook's own
secret-detection regex (the `PROFITDLL_<NAME>` assignment pattern), causing self-block
whenever the hook source was staged. Docstring rewritten to describe the patterns
abstractly (e.g., `PROFITDLL_<NAME> assignment (KEY/USER/PASS)`) without embedding
literal trigger strings.

---

## Validation

1. Reproduced original `UnicodeDecodeError` on `docs/MANIFEST.md` via `git show` without
   explicit encoding (cp1252 default).
2. Verified fix: `git show HEAD:docs/MANIFEST.md` with `encoding='utf-8'` returns 10405
   chars including em-dashes, no error.
3. Ran `python scripts/hooks/check_no_dotenv.py` against staged files containing
   em-dashes (the patched hook sources themselves) — exit 0 clean.
4. Ran `python scripts/hooks/check_no_dotenv.py docs/MANIFEST.md` and
   `docs/stories/1.1.story.md` — exit 0.
5. Direct call to patched `staged_blob()` confirmed UTF-8 decode of all 3 staged hook
   files including em-dashes.

`pre-commit run no-dotenv --all-files` could not be run end-to-end because the squad
host lacks Python 3.12 (config pins `default_language_version: python3.12`; squad
currently on 3.14). Tracking in Story 1.1 Debug Log; not blocking.

---

## Lesson learned (process change)

**MANDATORY for all NEW hooks under `scripts/hooks/` (and any squad Python script that
reads subprocess output or file content on Windows):**

1. EVERY `subprocess.run(..., capture_output=True, text=True)` MUST also pass
   `encoding='utf-8', errors='replace'`.
2. EVERY `open(path, ...)` for reading text MUST pass `encoding='utf-8'` (and
   `errors='replace'` if input is untrusted).
3. EVERY `Path.read_text()` MUST pass `encoding='utf-8'` (and `errors='replace'` if
   input is untrusted).
4. EVERY `open(path, ...)` for writing text MUST pass `encoding='utf-8'`.

Rationale: Windows defaults to cp1252; Linux/macOS default to UTF-8. Implicit reliance
on locale produces non-portable code that silently breaks on the development host
(Windows-first project). UTF-8 is the canonical encoding for git, markdown, and Python
source — there is no scenario where cp1252 is the correct default.

**Codification:** Add this rule to the squad's pre-commit checklist (Quinn `*qa-gate`
should fail any new hook that omits explicit `encoding=`). Consider adding a meta-hook
(custom AST check) that flags `subprocess.run()`/`open()`/`read_text()` calls without
`encoding=` in `scripts/hooks/`.

---

## Related references

- Story 0.2 — Pre-commit Framework (introduced the hooks)
- Story 0.4 AUDIT entry — first known occurrence of `--no-verify` due to this bug
- Python docs — [`subprocess.Popen` encoding parameter](https://docs.python.org/3/library/subprocess.html#popen-constructor)
- PEP 597 — Add optional EncodingWarning (warn on implicit locale encoding)

— Gage, publicando com cuidado ⚙️
