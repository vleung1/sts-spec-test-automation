# STS v2 API Test Framework – Design and CI

**Full documentation:** See **[ONBOARDING.md](ONBOARDING.md)** for complete onboarding: what the framework does, key concepts, project structure, how to run it, how to add tests, design decisions, glossary, and troubleshooting. The README provides quick start; ONBOARDING is the single place for detailed explanations and maintenance guidance.

---

## Short summary

The framework is **spec-driven**: it loads the OpenAPI spec (`spec/v2.yaml`), runs **discovery** against the live API to get real IDs, **generates** positive (200) and negative (404/422) test cases from the spec (including **`__skip_oob`**: default huge `skip` → **404** + detail; **`/terms/cde-pvs/.../pvs`** and **`/terms/model-pvs/...`** expect **200** with `[]` or empty `permissibleValues`), **runs** them via a single HTTP client, and **reports** results as JSON and HTML. Run with **pytest** (`pytest tests/ -v`) or the **CLI** (`python -m sts_test_framework.cli --report reports/`). Use **`--model <handle>`** to test a specific data model (e.g. PSDC, CTDC) and **`--release`** to use the latest release version. Use **`scripts/run_all_models.py`** to run the CLI once per model and write reports to `reports/<model>/` (optional env: `STS_MODELS`, `STS_BASE_URL`). Default STS base URL when `STS_BASE_URL` is unset: **`sts_test_framework.config.DEFAULT_STS_BASE_URL`** (`https://sts-qa.cancer.gov/v2`). Environment variables: `STS_BASE_URL`, `STS_SSL_VERIFY`, `REPORT_DIR` (see `config/env.example` and [ONBOARDING.md](ONBOARDING.md#62-configuration-the-config-folder-and-environment-variables)). For CI, install the package and run the CLI or pytest; the CLI exits with code 1 on failure.
