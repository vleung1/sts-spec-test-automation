# STS Test Framework – Runbook

Commands to run each kind of test in this repo, what they exercise, and which artifacts to review afterward. For concepts (discovery, generator, fixtures), see [ONBOARDING.md](ONBOARDING.md). This doc does not replace onboarding; it is a command-centric checklist.

**To run everything in order (pytest, CLI reports, optional multi-model, all term-verify):** see [Full coverage: step-by-step](#full-coverage-step-by-step-run-all-tests).

**Prerequisites**

- From the project root: `pip install -e .` (or use `uv run` if you use uv).
- Network access to STS for generated, manual, CLI, and term-verify runs.
- Optional env vars: `STS_BASE_URL` (default `https://sts-qa.cancer.gov/v2`), `REPORT_DIR` (default `reports`), `STS_SSL_VERIFY` (`false` only for dev/self-signed).

---

## Summary: test types vs commands

| Kind | What it is | Typical command | Needs live STS? |
|------|------------|-----------------|-----------------|
| **Auto-generated (pytest)** | One parametrized test per generated GET from `spec/v2.yaml` + discovery (includes `__pagination_positive` for routes with both `skip` and `limit`) | `pytest tests/test_generated/ -v` | Yes |
| **Manual (pytest)** | Hand-written checks (e.g. model-pvs dedup, id-by-type) | `pytest tests/test_manual/ -v` | Yes |
| **CLI functional** | Same cases as generated pytest, run in one process; writes JSON + HTML reports | `python -m sts_test_framework.cli --report reports/` | Yes |
| **Multi-model CLI** | Runs CLI once per data model | `python scripts/run_all_models.py` | Yes |
| **Term-by-value** | YAML-driven enum → STS term endpoint verification per commons | `sts-ccdi-term-verify` (etc.) | Yes |

---

## Full coverage: step-by-step (run all tests)

Use this sequence from the **project root** when you want every automated check in this repo against a live STS (default QA). Set `STS_BASE_URL` first if not using QA.

**1. Install the package**

```bash
cd sts-test-framework-agent   # your clone path
pip install -e .
# or: uv sync && uv run ...
```

**2. Pytest — full suite (generated + manual + any other tests under `tests/`)**

```bash
export STS_BASE_URL=https://sts-qa.cancer.gov/v2   # optional; omit to use default QA
pytest tests/ -v
```

Expect exit code **0** before continuing. This is the main “all pytest” gate.

**3. Functional CLI — OpenAPI-driven suite with framework HTML + JSON reports**

Same logical cases as the generated pytest tests, but writes timestamped artifacts (good for sharing and CI artifacts).

```bash
python -m sts_test_framework.cli --report reports/
# equivalent: sts-test --report reports/
```

**4. (Optional) Multi-model CLI — functional suite once per data model**

Use this when you need **per-model** reports under `reports/<ModelHandle>/` (longer run; overlaps with step 3 conceptually). Skip if step 3 is enough.

```bash
python scripts/run_all_models.py
```

Optional: `STS_MODELS=PSDC,CTDC python scripts/run_all_models.py` to limit models.

**5. Term-by-value verification — all commons**

These are **separate** from OpenAPI/pytest: YAML enums → STS term endpoints. Run each (order does not matter):

```bash
sts-ccdi-term-verify
sts-c3dc-term-verify
sts-ctdc-term-verify
sts-icdc-term-verify
sts-cds-term-verify
sts-ccdi-dcc-term-verify
```

**What to review after a full run**

| Step | Check |
|------|--------|
| 2 | Pytest console: all passed |
| 3 | Latest `reports/report_*.html` and `report_*.json` (details in **§4** below) |
| 4 | Newest HTML under each `reports/<model>/` you care about (**§5**) |
| 5 | Each commons `*_term_endpoint_verification_report.md` (and CSV) under `reports/term_value/...` (**§6**) |

**Overlap note:** Steps 2 and 3 exercise the same generated cases different ways (pytest vs CLI). Run both when you need pytest’s exit code **and** archived framework reports. Step 4 adds per-model discovery; it does not replace step 5.

---

## 1. Pytest – full suite

Runs generated tests, manual tests, and any other tests under `tests/`.

```bash
cd mdb/sts-test-framework-agent   # or your clone path
pip install -e .
STS_BASE_URL=https://sts-qa.cancer.gov/v2 pytest tests/ -v
```

Equivalent using the project virtualenv:

```bash
uv run pytest tests/ -v
```

**What it tests:** Everything under `tests/` (see sections 2–3).

**Reports:** Pytest prints pass/fail to the terminal. It does **not** write the framework’s `report_*.html` / `report_*.json` files; those come from the CLI (section 4).

**What to check:** Console summary (`X passed`, failures with tracebacks). For a shareable HTML table of every endpoint case, run the CLI after or instead (section 4).

---

## 2. Pytest – auto-generated (OpenAPI-driven) only

```bash
pytest tests/test_generated/ -v
```

**What it tests:** [`tests/test_generated/test_from_spec.py`](../tests/test_generated/test_from_spec.py) – at collection time, loads `spec/v2.yaml`, runs discovery, generates cases, and parametrizes one test per case (status + body rules aligned with [`functional.py`](../src/sts_test_framework/runners/functional.py)).

**Reports:** Terminal only.

**What to check:** Failing test names (`operation_id` in pytest ids); stderr/assert messages for expected vs actual status or body shape.

---

## 3. Pytest – manual only

```bash
pytest tests/test_manual/ -v
```

**What it tests:** Currently:

- [`test_model_pvs_no_duplicates.py`](../tests/test_manual/test_model_pvs_no_duplicates.py) – no duplicate permissible values on `.../terms/model-pvs/...` for major models (and optional bug-ticket pins).
- [`test_id_by_type.py`](../tests/test_manual/test_id_by_type.py) – id-by-type behavior.

**Reports:** Terminal only.

**What to check:** Assertion failures and any logged `STS_DEDUP_LIMIT` / env-related behavior described in those files.

---

## 4. CLI – single functional run (with framework reports)

**Entry points (equivalent):**

```bash
python -m sts_test_framework.cli --report reports/
sts-test --report reports/
```

**Common options:**

```bash
# Explicit base URL
python -m sts_test_framework.cli --base-url https://sts-qa.cancer.gov/v2 --report reports/

# Only certain OpenAPI tags
python -m sts_test_framework.cli --report reports/ --tags id,model,models

# Skip negative (404/422) cases
python -m sts_test_framework.cli --report reports/ --no-negative

# One model + latest release version
python -m sts_test_framework.cli --report reports/ --model PSDC --release

# Minimal log noise (CI)
python -m sts_test_framework.cli --report reports/ --quiet
```

**What it tests:** Same pipeline as pytest generated tests: load spec → discover → `generate_cases` → `run_functional_tests`.

**Reports generated (each run creates a new pair):**

| File pattern | Purpose |
|--------------|---------|
| `reports/report_YYYY-MM-DDTHH-MM-SS.json` | Machine-readable: summary, per-case results, durations, errors. |
| `reports/report_YYYY-MM-DDTHH-MM-SS.html` | Human-readable table: operation id, path, pass/fail, status codes, duration, error snippet. |

`REPORT_DIR` overrides the `reports/` directory.

**What to check first:** Open the **latest** `report_*.html` for a quick pass/fail grid and error text. Use **JSON** for automation, diffing, or extracting P95 timing / counts. Exit code **1** if any case failed.

---

## 5. Multi-model CLI (`run_all_models.py`)

Runs the CLI once per configured model handle (default list includes CDS, CCDI, CCDI-DCC, ICDC, CTDC, C3DC, PSDC, and others – see the script).

```bash
STS_BASE_URL=https://sts-qa.cancer.gov/v2 python scripts/run_all_models.py
```

Subset of models:

```bash
STS_MODELS=PSDC,CTDC python scripts/run_all_models.py
```

**Reports generated:**

| Location | Contents |
|----------|----------|
| `reports/<ModelHandle>/report_YYYY-MM-DDTHH-MM-SS.html` | Same HTML report as single CLI, scoped to that model’s discovery. |
| `reports/<ModelHandle>/report_YYYY-MM-DDTHH-MM-SS.json` | Same JSON structure as single CLI. |

**What to check:** Under each `reports/<model>/`, open the newest HTML for that model’s run. Investigate any model subdirectory with failures before treating the overall script exit code as green.

---

## 6. Term-by-value verification (per commons)

Each command reads a vendored YAML under `data/data-models-yaml/` and writes CSV/MD under `reports/term_value/<COMMONS>/`. Install provides console scripts from `pyproject.toml` (e.g. `sts-ccdi-term-verify`).

| Command | Output directory (default) | Final report filenames (under that dir) |
|---------|----------------------------|----------------------------------------|
| `sts-ccdi-term-verify` | `reports/term_value/CCDI/` | `ccdi_term_endpoint_verification_report.csv`, `ccdi_term_endpoint_verification_report.md` |
| `sts-c3dc-term-verify` | `reports/term_value/C3DC/` | `c3dc_term_endpoint_verification_report.csv`, `.md` |
| `sts-ctdc-term-verify` | `reports/term_value/CTDC/` | `ctdc_term_endpoint_verification_report.csv`, `.md` |
| `sts-icdc-term-verify` | `reports/term_value/ICDC/` | `icdc_term_endpoint_verification_report.csv`, `.md` |
| `sts-cds-term-verify` | `reports/term_value/CDS/` | `cds_term_endpoint_verification_report.csv`, `.md` |
| `sts-ccdi-dcc-term-verify` | `reports/term_value/CCDI-DCC/` | `ccdi_dcc_term_endpoint_verification_report.csv`, `.md` |

**Useful flags:**

```bash
sts-ctdc-term-verify --limit 50   # first N rows only
sts-ctdc-term-verify --warn-only  # exit 0 even if some rows fail (still lists failures in reports)
```

**What it tests:** Extract enums from YAML → enrich with STS → verify `GET .../term/{termValue}` (or CDS-specific path). Not the same as OpenAPI functional tests.

**Reports generated:** Each commons pipeline also writes intermediate CSVs (summary, query list, enriched) during extract/enrich steps. For triage, use the final pair in the table above (`*_term_endpoint_verification_report.csv` / `.md`).

**What to check:** Open the **`*.md`** for a readable summary and failed-row previews; use the matching **`.csv`** for per-row status and spreadsheet filters. Intermediate files are for debugging the pipeline.

---

## 7. Which report should I open? (quick guide)

| Goal | Open this |
|------|-----------|
| “Did every generated GET pass on QA?” | Latest `reports/report_*.html` from CLI, or per-model `reports/<model>/report_*.html` from `run_all_models.py` |
| “Automate pass rate / export failures” | Same run’s `report_*.json` |
| “Dedup / manual pytest failed” | No HTML; re-read pytest output or run CLI for the same env to compare |
| “Did YAML enum terms resolve in STS?” | Latest `reports/term_value/<COMMONS>/*_term_endpoint_verification_report.md` (and CSV for detail) |

---

## 8. Optional: pytest HTML plugin

The project depends on `pytest-html`, but the **framework’s** official HTML report is the CLI output above. If you wire `pytest` with `--html=...` yourself, that file is separate from `report_*.html` produced by `sts_test_framework.cli`.
