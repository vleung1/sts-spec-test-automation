# STS v2 API Test Framework Agent

OpenAPI-driven end-to-end API test automation framework for the **Simple Terminology Server (STS) v2** API. Tests are generated from the OpenAPI spec (`spec/v2.yaml`) and executed against a live STS instance, with optional contract validation and HTML/JSON reporting.

## Purpose

- **95%+ endpoint coverage**: All v2 paths get at least one positive and, where applicable, one negative test.
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

- `STS_BASE_URL` – STS v2 base URL (default: `https://sts.cancer.gov/v2`)
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
python -m sts_test_framework.cli --spec spec/v2.yaml --base-url https://sts.cancer.gov/v2 --report reports/
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

## Project layout

| Path | Purpose |
|------|---------|
| `spec/v2.yaml` | OpenAPI 3.1 spec for STS v2 (source of truth) |
| `src/sts_test_framework/` | Framework code: loader, client, discover, generator, runners, reporters, cli |
| `tests/conftest.py` | Pytest fixtures: spec, api_client, test_data, generated_cases |
| `tests/test_manual/` | Manual tests (e.g. root, consistency) |
| `tests/test_generated/` | Dynamic tests parametrized from generated cases |
| `reports/` | Default output for timestamped report files (`report_YYYY-MM-DDTHH-MM-SS.json`, `.html`) |
| `scripts/run_all_models.py` | Run CLI once per data model (CDS, CCDI, CCDI-DCC, ICDC, CTDC, C3DC, PSDC); reports in `reports/<model>/` |
| `docs/ONBOARDING.md` | Full onboarding: concepts, structure, run, add tests, glossary |
| `docs/FRAMEWORK.md` | Short summary and pointer to ONBOARDING |

## Extending the framework

- **Add manual tests**: Add modules under `tests/test_manual/` and use the `api_client` and `test_data` fixtures.
- **Adjust discovery**: Edit `src/sts_test_framework/discover.py` to change how test data is discovered.
- **Adjust generation**: Edit `src/sts_test_framework/generator.py` to add or change positive/negative cases (e.g. query param validation).
- **Contract validation**: Use the optional `runners.contract.run_contract_tests` and install `jsonschema` (and optionally `openapi-spec-validator`).

## Dependencies

- Python 3.9+
- pytest, pytest-html, PyYAML, jsonschema (see `pyproject.toml`)
