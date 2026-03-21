# STS v2 API Test Framework Agent

OpenAPI-driven end-to-end API test automation framework for the **Simple Terminology Server (STS) v2** API. Tests are generated from the OpenAPI spec (`spec/v2.yaml`) and executed against a live STS instance, with optional contract validation and HTML/JSON reporting.

## Purpose

- **Endpoint coverage**: All v2 paths get at least one positive and, where applicable, one negative test.
- **Spec-driven**: Tests are derived from the spec so that spec changes can be reflected by re-running the generator.
- **Functional + negative**: Validates status codes and basic response shape; includes 404/422 negative cases.
- **CI-ready**: Run via `pytest` or the CLI; configurable base URL and report output.

## Quick Start

### Install

```bash
cd mdb/sts-test-framework-agent
pip install -e .
```

### Configure (optional)

Copy `config/env.example` and set:

- `STS_BASE_URL` – STS v2 base URL (default: `https://sts-qa.cancer.gov/v2`)
- `STS_QA_URL` – QA base URL if needed
- `STS_SSL_VERIFY` – Set to `false` to disable SSL verification
- `REPORT_DIR` – Report output directory (default: `reports/`)

### Run tests

**Via pytest (recommended):**

```bash
pytest tests/ -v
```

With report directory:

```bash
pytest tests/ -v --report reports/
```

(Report generation from pytest requires a small plugin or post-run script; the CLI writes reports by default.)

**Via CLI:**

```bash
python -m sts_test_framework.cli --spec spec/v2.yaml --base-url https://sts-qa.cancer.gov/v2 --report reports/
```

**Test a specific data model** (e.g. PSDC, CTDC) and use the **latest release version** (no pre-release hash):

```bash
STS_BASE_URL=https://sts-qa.cancer.gov/v2 python -m sts_test_framework.cli --report reports/ --model PSDC --release
```

- `--model` – Model handle to test (e.g. `PSDC`, `C3DC`). If omitted, the first model from `/models/` is used.
- `--release` – Use the latest **release** version (version string with no hyphen, e.g. `2.1.0`) from `/model/{handle}/versions`. If omitted, the first version in the list is used. If the model has no release versions, the first available version (e.g. pre-release) is used.

**Run all data models in one go** (CDS, CCDI, CCDI-DCC, ICDC, CTDC, C3DC, PSDC):

```bash
STS_BASE_URL=https://sts-qa.cancer.gov/v2 python scripts/run_all_models.py
```

Reports are written to `reports/<model>/report_<timestamp>.html` (and `.json`) per model. Optional: set `STS_MODELS=PSDC,CTDC` to run only those models. See [docs/ONBOARDING.md](docs/ONBOARDING.md) for details.

Filter by tags:

```bash
python -m sts_test_framework.cli --tags id,model,models
```

Skip negative cases:

```bash
python -m sts_test_framework.cli --no-negative
```

Use minimal output (e.g. for CI):

```bash
python -m sts_test_framework.cli --quiet --report reports/
```

### Term-by-value verification (YAML → enrich → verify)

Ports of `termValue_verification_scripts`: vendored property YAML → extract enums → enrich via STS → verify `GET .../term/{termValue}`. **Most models** use paginated `/terms` to map YAML handle→API **value** for the URL. **CDS** uses YAML **enum_value** in the URL (no `/terms` step); see [data/data-models-yaml/README.md](data/data-models-yaml/README.md).


| Commons  | CLI                        | YAML                                                      | Output                         |
| -------- | -------------------------- | --------------------------------------------------------- | ------------------------------ |
| CCDI     | `sts-ccdi-term-verify`     | `data/data-models-yaml/ccdi-model-props.yml`              | `reports/term_value/CCDI/`     |
| C3DC     | `sts-c3dc-term-verify`     | `data/data-models-yaml/c3dc-model-props.yml`              | `reports/term_value/C3DC/`     |
| CTDC     | `sts-ctdc-term-verify`     | `data/data-models-yaml/ctdc_model_properties_file-2.yaml` | `reports/term_value/CTDC/`     |
| ICDC     | `sts-icdc-term-verify`     | `data/data-models-yaml/icdc-model-props.yml`              | `reports/term_value/ICDC/`     |
| CDS      | `sts-cds-term-verify`      | `data/data-models-yaml/cds-model-props-4.yml`             | `reports/term_value/CDS/`      |
| CCDI-DCC | `sts-ccdi-dcc-term-verify` | `data/data-models-yaml/ccdi-dcc-model-props-3.yml`        | `reports/term_value/CCDI-DCC/` |


```bash
pip install -e .
sts-ccdi-term-verify
sts-c3dc-term-verify
sts-ctdc-term-verify
sts-icdc-term-verify
sts-cds-term-verify
sts-ccdi-dcc-term-verify
```

- `**--limit N**` — verify only N rows (quick check).
- `**--warn-only**` — exit 0 even if some rows fail (reports still list failures).
- `**STS_BASE_URL**` — same as other tools (default QA).

See [data/data-models-yaml/README.md](data/data-models-yaml/README.md) and [reports/term_value/](reports/term_value/) per commons (CCDI, C3DC, CTDC, ICDC, CDS, CCDI-DCC).

## Project layout


| Path                           | Purpose                                                                                                  |
| ------------------------------ | -------------------------------------------------------------------------------------------------------- |
| `spec/v2.yaml`                 | OpenAPI 3.1 spec for STS v2 (source of truth)                                                            |
| `src/sts_test_framework/`      | Framework code: loader, client, discover, generator, runners, reporters, cli                             |
| `tests/conftest.py`            | Pytest fixtures: spec, api_client, test_data, generated_cases                                            |
| `tests/unit/`                  | Unit tests for `functional.py` helpers (mocked responses; no live API)                                   |
| `tests/test_manual/`           | Manual tests (e.g. model-PVS by model, dedup, id-by-type)                                                |
| `tests/test_generated/`        | Dynamic tests parametrized from generated cases                                                          |
| `reports/`                     | Default output for timestamped report files (`report_YYYY-MM-DDTHH-MM-SS.json`, `.html`)                 |
| `reports/term_value/CCDI/`     | CCDI term verification CSV/MD (`sts-ccdi-term-verify`)                                                   |
| `reports/term_value/C3DC/`     | C3DC term verification CSV/MD (`sts-c3dc-term-verify`)                                                   |
| `reports/term_value/CTDC/`     | CTDC term verification CSV/MD (`sts-ctdc-term-verify`)                                                   |
| `reports/term_value/ICDC/`     | ICDC term verification CSV/MD (`sts-icdc-term-verify`)                                                   |
| `reports/term_value/CDS/`      | CDS term verification CSV/MD (`sts-cds-term-verify`)                                                     |
| `reports/term_value/CCDI-DCC/` | CCDI-DCC term verification CSV/MD (`sts-ccdi-dcc-term-verify`)                                           |
| `data/data-models-yaml/`       | Vendored property YAMLs for term-by-value CLIs                                                           |
| `scripts/run_all_models.py`    | Run CLI once per data model (CDS, CCDI, CCDI-DCC, ICDC, CTDC, C3DC, PSDC); reports in `reports/<model>/` |
| `docs/ONBOARDING.md`           | Full onboarding: concepts, structure, run, add tests, glossary                                           |
| `docs/RUNBOOK.md`              | Command cheat sheet: pytest (generated, manual), CLI, term-verify, and which reports to open             |
| `docs/FRAMEWORK.md`            | Short summary and pointer to ONBOARDING                                                                  |


## Extending the framework

- **Add manual tests**: Add modules under `tests/test_manual/` and use the `api_client` fixture (and `test_data` when you need session discovery). `test_model_pvs_by_model.py` checks `GET /terms/model-pvs/{model}/` and `GET /terms/model-pvs/{model}/{property}` for each `MAJOR_MODELS` handle (by-model pin from `/versions`; property handle from session-cached aggregate candidates with non-empty `permissibleValues`, verified with property-level GET both omitting `version` and using `version=<versions[0]>`). Optional `version` query; PV rows may have null `ncit_concept_code` or empty `synonyms`. In `test_model_pvs_no_duplicates.py`, `test_model_pvs_no_duplicate_permissible_values` covers the same major models; `test_model_pvs_no_duplicates_bug_ticket_endpoints` pins specific model/property/version pairs from the original dedup bug ticket.
- **Null CDE manual tests**: `tests/test_manual/test_null_cde_all_models.py` is marked `nullcde`. The reference null-CDE **value** set is loaded once per session from `GET /terms/cde-pvs/16476366/1/pvs`, keeping only PV rows with **non-null** `ncit_concept_code` (NCIt-filtered). The **main** assertion: no data model at **latest** has a property whose PVs cover that full reference set, except CDS whose latest version looks like **11.0.x** (substring `11.0.`). A **second** check calls CDS pinned at `CDS_PINNED_VERSION` (e.g. **11.0.3**); it **passes** or **skips** (see module docstring). A **third** test hits `GET /terms/cde-pvs/11527735/1.00/pvs` with `use_null_cde` omitted, `false`, and `true`, using the same reference set for disjoint/subset checks. Run: `pytest -m nullcde tests/test_manual/test_null_cde_all_models.py -v` (uses `STS_BASE_URL`, default QA).
- **Add unit tests**: Add modules under `tests/unit/` for runner logic with `APIResponse` mocks only (see `tests/unit/README.md`).
- **Adjust discovery**: Edit `src/sts_test_framework/discover.py` to change how test data is discovered.
- **Adjust generation**: Edit `src/sts_test_framework/generator.py` to add or change positive/negative cases (e.g. query param validation).
- **Contract validation**: Use the optional `runners.contract.run_contract_tests` and install `jsonschema` (and optionally `openapi-spec-validator`).

## Dependencies

- Python 3.9+
- pytest, pytest-html, PyYAML, jsonschema (see `pyproject.toml`)

