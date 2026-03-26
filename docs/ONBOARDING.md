# STS v2 API Test Framework – Onboarding Guide

This document explains what the framework does, how it works, how to run it, and how to maintain or extend it. Use the [README](../README.md) for install, environment defaults, and running tests (**web UI first**, then command-line backup); this guide provides the full picture. For a **minimal command-only** path (install, optional env vars, three convenience scripts), see **[RUNBOOK.md](RUNBOOK.md)**.

**How to read this document**

- **First day / QA run:** [§1](#1-what-is-sts-and-the-v2-api)–[§2](#2-what-does-this-framework-do), [§3.6](#36-three-runnable-test-suites-overview)–[§3.8](#38-term-by-value-yaml--sts) (what each suite does), **[§5.0](#50-web-test-runner-ui-recommended)** (web UI), [§5.1](#51-prerequisites)–[§5.6](#56-running-all-data-models-in-one-go-multi-model-runner) (skim [§5.7](#57-what-happens-when-you-run-under-the-hood)), [§7.2](#72-which-file-should-i-open).
- **Scripts and logs (CLI backup):** [§5.8](#58-convenience-shell-scripts), [§3.8](#38-term-by-value-yaml--sts) (term-by-value reference).
- **Changing or debugging tests:** [§6](#6-how-to-add-or-change-tests), [§9](#9-troubleshooting-and-faq).
- **Generator internals / edge cases:** [§3.3.1](#331-advanced-pagination-skip-oob-and-reporting-quirks), [§5.7](#57-what-happens-when-you-run-under-the-hood).

Optional deep dives: [pagination, skip-OOB, reporting](#331-advanced-pagination-skip-oob-and-reporting-quirks) · [caDSR & legacy CDE-PVS manual tests](#371-cadsr-and-legacy-cde-pvs-reference)

---

## Table of Contents

1. [What is STS and the v2 API?](#1-what-is-sts-and-the-v2-api)
2. [What does this framework do?](#2-what-does-this-framework-do)
3. [Key concepts and test suites](#3-key-concepts-and-test-suites)
4. [Project structure](#4-project-structure)
5. [How to run the framework](#5-how-to-run-the-framework)
6. [How to add or change tests](#6-how-to-add-or-change-tests)
7. [Reports and CI](#7-reports-and-ci)
8. [Glossary](#8-glossary)
9. [Troubleshooting and FAQ](#9-troubleshooting-and-faq)

---

## 1. What is STS and the v2 API?

**STS** stands for **Simple Terminology Server**. It is a web API that exposes data models (e.g. for cancer research) in a consistent way. The data is stored in a graph database (Neo4j) and described as **nodes**, **properties**, **terms**, and **tags**. The API lets clients ask things like: “What models exist?”, “What nodes does this model have?”, “What are the allowed values (terms) for this property?”.

The **v2 API** is the second version of this interface. It is **read-only**: all endpoints use the **GET** method. There is no login in the spec (no API keys or tokens for normal use). The API is documented in an **OpenAPI** specification file (`spec/v2.json`), which lists every URL path, its parameters, and the expected response shapes.

**Why we test it:** Before releasing changes to STS, we need to confirm that every documented endpoint behaves as the spec says (right status codes, right response shape). This framework automates that checking.

---

## 2. What does this framework do?

At a high level, the framework does four things:

1. **Reads the API contract** – It loads the OpenAPI spec (`spec/v2.json`) so it knows every endpoint, its parameters, and expected responses.
2. **Gets real data from the API** – It calls the live API once to “discover” real IDs and names (e.g. a model handle, a node handle, a tag). That discovery data is used to build valid requests for each endpoint.
3. **Generates test cases** – For each endpoint in the spec, it creates at least one “positive” test (expects 200 OK) and, where the spec says so, one “negative” test (expects 404 or 422 for bad input).
4. **Runs the tests and reports** – It sends HTTP requests for each generated case, checks status codes and basic response shape, and writes a **JSON** and **HTML** report with pass/fail and timing.

So: **no hand-written test list per endpoint.** The spec is the source of truth; the framework turns it into executable tests and runs them. If the spec is updated, re-running the framework exercises the new or changed endpoints automatically.

The **generated** tests are **not** stored as test case files on disk. They are created **on the fly** from the spec plus discovery data, live **in memory**, and are then run—either by pytest (which builds one parametrized test per case at collection time) or by the CLI (which runs the case list in a loop). The only file under `tests/test_generated/` is `test_from_spec.py`; that file is the pytest hook that invokes the generator and parametrizes tests—it does not contain a static list of test cases.

**Static tests also exist in the framework:** **Manual** integration tests live under `tests/test_manual/`. Term-by-value verification pipelines use data model properties YAMLs in `data/data-model-yaml` and compare enums from the YAMLs to responses from STS termValue endpoint for each data model. Optional **unit** tests for the functional runner (mocked responses, no HTTP) live under `tests/unit/`. 

---

## 3. Key concepts and test suites

OpenAPI mechanics and discovery are in §3.1–§3.5; **runnable suites** and reference for manual caDSR and term-by-value are in §3.6–§3.8.

### 3.1 OpenAPI spec (the “spec”)

The **OpenAPI** (formerly Swagger) specification is a standard way to describe a REST API. The file `spec/v2.json` contains:

- **Paths** – Each URL pattern (e.g. `/v2/models/`, `/v2/id/{id}`).
- **Operations** – For each path, the HTTP method (here, only GET) and:
  - **Parameters** – Path parameters like `{id}`, `{modelHandle}`, and query parameters like `skip`, `limit`.
  - **Responses** – Documented status codes (200, 404, 422) and the **schema** of the response body (e.g. “array of Model”, “object with nanoid and handle”).

The framework **loads** this file and uses it to decide which requests to send and what to expect. The spec is the single source of truth for “what the API is supposed to do.”

### 3.2 Discovery

Many endpoints need **real values** in the URL. For example, “get node by handle” requires a real `modelHandle`, `versionString`, and `nodeHandle`. We don’t hardcode those; we **discover** them by calling the API once at the start:

1. GET `/models/` → choose a model (by `--model` handle if provided, otherwise the first in the list). GET `/model/{handle}/versions` → choose a version: with `--release`, the latest **release** version (version string with no hyphen, e.g. `2.1.0`); otherwise the first version in the list (which may be a pre-release).
2. GET `/model/{handle}/version/{version}/nodes` → take the first node’s `handle`.
3. GET that node’s properties → take the first property’s `handle`.
4. GET that property’s terms → take a real `term` value.
5. GET `/tags/` → take a real tag `key` and `value`.

The result is a **test_data** dictionary (e.g. `model_handle`, `model_version`, `node_handle`, `prop_handle`, `term_value`, `tag_key`, `tag_value`, and various `nanoid`s). The **generator** uses this to fill in path and query parameters when building test cases.

### 3.3 Test case generation

The **generator** walks every path and method in the spec. For each operation it:

- **Positive case:** Fills path and query parameters from the discovery data. If it can resolve all required parameters, it adds one case with `expected_status: 200`.
- **Negative case:** Where the spec documents 404 or 422, it adds a case that uses an **invalid** value (e.g. `invalid_nonexistent_xyz`) for a path parameter, expecting 404 or 422.
- **Bad query (422):** For operations that document 422 and have integer `skip`/`limit` query parameters, the generator adds one or two extra cases (same valid path, invalid query: `skip=-1` and/or `limit=not_a_number`) with distinct `operation_id` suffixes (e.g. `__bad_query_skip`, `__bad_query_limit`) so pytest ids stay unique.

The generator also adds **pagination** and **skip-past-end** case types for some operations; see [§3.3.1](#331-advanced-pagination-skip-oob-and-reporting-quirks) for full rules and optional fields on those cases.

Each **case** is a small dictionary: at minimum `path`, `params`, `expected_status`, `operation_id`, `summary`, `tag`, and whether it’s negative; common optional keys include `response_schema_ref` and `expected_json`. Pagination and skip-OOB cases add further fields documented in §3.3.1. No test code is written by hand for generated cases; they come from the spec + discovery.

**Sample generated cases** (the exact values depend on discovery; this is what one positive and one negative might look like in memory). Here, a **terms** endpoint shows how discovery data is used—the path is built from `model_handle`, `model_version`, `node_handle`, `prop_handle`, and `term_value` in `test_data`:

```python
# Positive case: GET term by value — path filled from discovery (model_handle, model_version, node_handle, prop_handle, term_value)
{
    "path": "/model/C3DC/version/1.4.0/node/diagnosis/property/tumor_stage_clinical_m/term/M1c",
    "params": None,
    "expected_status": 200,
    "operation_id": "get_term_by_value",
    "summary": "Get term by value",
    "tag": "terms",
    "negative": False,
    "response_schema_ref": "Term",
}

# Negative case: same path template but with invalid path params — expects 404
{
    "path": "/model/invalid_nonexistent_xyz/version/invalid_nonexistent_xyz/node/invalid_nonexistent_xyz/property/invalid_nonexistent_xyz/term/invalid_nonexistent_xyz",
    "params": None,
    "expected_status": 404,
    "operation_id": "get_term_by_value",
    "summary": "Get term by value",
    "tag": "terms",
    "negative": True,
}
```

The runner sends `GET base_url + path` with the given `params`, then asserts that the response status equals `expected_status`.

### 3.3.1 Advanced: pagination, skip-OOB, and reporting quirks

Skip this subsection unless you are debugging generated cases or report rows for pagination.

- **Positive pagination (`__pagination_positive`)**
  - **When added:** Operations that document **200** and have integer `skip` + `limit` query params.
  - **Generated case:** `skip=0`, `limit=1`, operation id suffix `__pagination_positive`, `pagination_assert_max_items: 1`.
  - **Assertion:** If body is a JSON array, runner checks `len(body) <= 1`. Non-array JSON skips this check.
- **Pagination pair (`__pagination_pair`)**
  - **When added:** Same operations as above, except `GET .../terms/model-pvs/...` and `GET .../terms/cde-pvs/.../pvs`.
  - **Generated requests:**  
    - **A:** `skip=0`, `limit=0` (default first-page behavior for this API)  
    - **B:** `skip=1`, `limit=1`
  - **Assertion logic:**  
    - If A is a JSON array with at least 2 elements, assert `B[0] == A[1]`.  
    - If A is not an array or has fewer than 2 elements, skip pair comparison (case still passes).
  - **Case fields:** `pagination_pair_assert`, `pagination_pair_params_a`, `pagination_pair_params_b`.
  - **Special pass rule:** For `/terms` and `/terms/count` routes, `404` with `{"detail":"Property exists, but does not use an acceptable value set."}` is treated as pass for request A or B.
  - **Reporting behavior (one row per pair case):**  
    - If B runs, Path/Duration reflect **B** only (`skip=1`, `limit=1`, B latency).  
    - If B is skipped, Path still shows B URL with a note; duration is A request time.  
    - If A fails before B, Path shows A URL.
  - **JSON result extras:** `pagination_pair_b_executed`, `duration_pair_a`, `duration_pair_b`, `pagination_pair_wall_time` (A+B), optional `pagination_pair_display_note`.
- **Huge skip / past end (`__skip_oob`)**
  - **Generated case:** `skip=9_999_999` (constant `SKIP_OOB`), operation id suffix `__skip_oob`.
  - **Default expectation:** For GETs with integer `skip` that document **404**, expect `404` + `expected_json: {"detail": "Not found."}` with `negative: true`.
  - **Exceptions (always emitted when route has `skip`):**  
    - `GET .../terms/cde-pvs/{id}/{version}/pvs` expects `200` + `[]` (`expected_json`).  
    - `GET .../terms/model-pvs/{model}/{property}` expects `200` + **non-empty** JSON array where each object has `permissibleValues: []` (`skip_oob_assert: model_pvs_empty_permissible_values`).
  - **Exception note:** For model-pvs skip-OOB, top-level `[]` is treated as failure and flagged for investigation.
  - **Negative flag:** Exception cases use `negative: false`.

**Pagination / skip-OOB case fields:** optional `pagination_assert_max_items` for `__pagination_positive`; optional `pagination_pair_assert` / `pagination_pair_params_a` / `pagination_pair_params_b` for `__pagination_pair`; optional `skip_oob_assert` for model-pvs skip-OOB (in addition to `response_schema_ref` / `expected_json` where used).

### 3.4 Runners and reporters

- **Functional runner** – Takes the list of cases and, for each one, calls `client.get(path, params)`, then checks that the response status equals `expected_status`. For 200 responses it can also do a basic shape check (e.g. response is a list, dict, or integer). It records pass/fail and duration.
- **Contract runner** (optional) – For 200 responses, can validate the JSON body against the OpenAPI response schema (e.g. required fields, types) using a library like `jsonschema`.
- **Reporters** – Take the list of results and produce:
  - A **summary** (total/passed/failed, by tag, by operation, P95 duration).
  - A **JSON report** (machine-readable).
  - An **HTML report** (table of endpoints, status, duration, errors).

### 3.5 Base URL and path normalization

The spec’s paths are written like `/v2/models/` or `/v2/id/{id}`. The **base URL** we use in tests is the full base including `/v2`, e.g. `https://sts-qa.cancer.gov/v2` (default). So when we send a request, we don’t send the path `/v2/models/` again; we **normalize** it to `/models/` and the client does `base_url + path` → `https://sts-qa.cancer.gov/v2/models/`. The **loader**’s `normalize_path_for_base()` does this stripping so that the same spec works whether the server is mounted at `/v2` or elsewhere.

### 3.6 Three runnable test suites (overview)

The repo ships **integration** suites against live STS plus **unit** tests for runner helpers. The three primary runnable integration suites are:


| Suite                   | Location / runner                                                                                          | Primary purpose                                               | How to run (detail)                                                                                                                                                                         |
| ----------------------- | ---------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Generated (OpenAPI)** | `tests/test_generated/` (pytest); `python -m sts_test_framework.cli`; `scripts/run_autogenerated_tests.py` | One case per spec GET (+ extras); discovery fills path params | [§5.4](#54-run-with-pytest-recommended-for-day-to-day-work), [§5.5](#55-run-with-the-cli-for-reports-and-scriptable-runs), [§5.6](#56-running-all-data-models-in-one-go-multi-model-runner) |
| **Manual pytest**       | `tests/test_manual/`                                                                                       | Hand-written checks (caDSR, legacy routes, consistency, etc.) | [§5.4](#54-run-with-pytest-recommended-for-day-to-day-work), [§5.8](#58-convenience-shell-scripts) (`run_manual_tests.sh`)                                                                  |
| **Term-by-value**       | `tests/term_verify/*_term_verify.py`                                                                       | YAML model enums vs term-by-value endpoints per commons       | [§3.8](#38-term-by-value-yaml--sts), [§5.8](#58-convenience-shell-scripts) (`run_all_term_verify.sh`)                                                                                       |


**Unit tests** (`tests/unit/`) use mocked `APIResponse` only—they do not call STS. See [§4](#4-project-structure).

Mechanics for the **generated** path are in [§3.1](#31-openapi-spec-the-spec)–[§3.5](#35-base-url-and-path-normalization) and [§3.3.1](#331-advanced-pagination-skip-oob-and-reporting-quirks).

### 3.7 Manual integration tests (`tests/test_manual/`)

These are **pytest** modules for behavior that is awkward as “one generated GET per operation” (for example root/health, cross-endpoint consistency, or caDSR vs STS). They reuse fixtures such as `api_client`, `test_data`, and `spec` where useful. Prefer the **generator + CLI** path for broad endpoint coverage; use **manual** tests for targeted or external-API scenarios. To add a new file and tests, follow [§6.1](#61-adding-a-manual-test).

### 3.7.1 caDSR and legacy CDE-PVS (reference)

Skip unless you run or debug these manual modules (`CADSR_*` env vars in [§5.2](#52-configuration-environment-variables)).

Manual caDSR `GET /DataElement/{publicId}` calls retry transient failures (connection errors, **429**, **5xx** including **504**) with a short delay; tune with `CADSR_GET_MAX_ATTEMPTS` (default **4**) and `CADSR_GET_RETRY_DELAY_SEC` (default **2.0**) — see [tests/test_manual/conftest.py](../tests/test_manual/conftest.py).

- **Multi-concept / URL-PV CDE checks**
  - **Test file:** `tests/test_manual/test_cadsr_multi_concept_cdes.py`
  - **Marker:** `cadsr_multi_concept_pv`
  - **Cases file:** `data/cadsr_multi_concept_cdes_cases.json`
  - **Case typing:** Set `case_type` explicitly (`multi_concept_pv` or `url_pv_yaml_enum_model_pvs`); default is `multi_concept_pv`.
  - **For `multi_concept_pv`:**
    - STS **cde-pvs** must return exactly one row for `pv_value` with `ncit_concept_code: null` and `synonyms: []`.
    - Each listed **model-pvs** endpoint must return exactly one row for the same `value` with null NCIt and empty synonyms.
    - caDSR must expose multiple `ValueMeaning.Concepts` / `conceptCode` values.
  - **For `url_pv_yaml_enum_model_pvs`:**
    - STS cde-pvs is not checked.
    - model-pvs must exclude the URL, match YAML enum multiset (`yaml_enum.file` / `yaml_enum.property`), and return rows with null NCIt + empty synonyms.
  - **Optional display helper:** `pytest_param_id` shortens pytest case names.
  - **Run command:** `pytest tests/test_manual/test_cadsr_multi_concept_cdes.py -m cadsr_multi_concept_pv -v`
- **caDSR vs STS PVS (Designations / DRAFT NEW)**
  - **Test file:** `tests/test_manual/test_cadsr_alternatevalues_draftnew_cdes.py`
  - **Markers:** `cadsr_alt_pvs`, `cadsr_draft_new`
  - **`cadsr_alt_pvs`:** Compares caDSR **Designations** names to STS **cde-pvs** and **model-pvs** (`data/cadsr_alternate_values_cases.json`).
  - **`cadsr_draft_new` assertions:**
    - caDSR `workflowStatus` is **DRAFT NEW**
    - caDSR `longName` exactly matches STS `CDEFullName`
    - Every caDSR `PermissibleValues[].value` appears in STS cde-pvs rows with non-null `ncit_concept_code` (rows with null NCIt are ignored)
  - **Optional model-pvs check:** If case has `model`, `model_version`, and `property`, also assert PV multiset subset against STS model-pvs NCIt-coded rows (no `CDEFullName` check there).
  - **Cases file:** `data/cadsr_draft_new_cases.json`
  - **Other notes:**
    - CDE version for cde-pvs URL is read from live caDSR.
    - Set `CADSR_BASE_URL` to use non-default caDSR host.
    - `STS_SSL_VERIFY` applies to both STS and caDSR `APIClient` calls.
    - By default all designation types are required; set `CADSR_DESIGNATION_TYPES` (for example `MCL Alt Name`) to filter required types.
- **Legacy CDE-PVS vs v2**
  - **Comparison:** Legacy `GET {origin}/cde-pvs/{id}/{version}?format=json` vs v2 `GET .../terms/cde-pvs/{id}/{version}/pvs`
  - **Origin derivation:** `origin` comes from `STS_BASE_URL` with trailing `/v2` removed via `sts_test_framework.config.sts_legacy_origin()`.
  - **Config rule:** Do not set a second base URL unless legacy routes are hosted elsewhere; then adjust `STS_BASE_URL` or extend the helper.
  - **Reference test:** `tests/test_manual/test_cde_pvs_legacy_vs_v2.py` (marker `cde_pvs_legacy`)

### 3.8 Term-by-value (YAML → STS)

#### 3.8.1 What this is

These verification pipelines are **not** pytest and **not** the OpenAPI-generated suite. Each runner reads a vendored property YAML under [data/data-models-yaml/](../data/data-models-yaml/), walks enums, calls the live STS API to enrich rows, then GETs the term-by-value endpoint per row. From the repo root, use `pip install -e .` so `sts_test_framework` imports resolve, or set `PYTHONPATH=src` when running the scripts under `tests/term_verify/`.

#### 3.8.2 Vendored YAML files


| Vendored file                       | Runner                                             | Default report directory       |
| ----------------------------------- | -------------------------------------------------- | ------------------------------ |
| `ccdi-model-props.yml`              | `python tests/term_verify/ccdi_term_verify.py`     | `reports/term_value/CCDI/`     |
| `c3dc-model-props.yml`              | `python tests/term_verify/c3dc_term_verify.py`     | `reports/term_value/C3DC/`     |
| `ctdc_model_properties_file-2.yaml` | `python tests/term_verify/ctdc_term_verify.py`     | `reports/term_value/CTDC/`     |
| `icdc-model-props.yml`              | `python tests/term_verify/icdc_term_verify.py`     | `reports/term_value/ICDC/`     |
| `cds-model-props-4.yml`             | `python tests/term_verify/cds_term_verify.py`      | `reports/term_value/CDS/`      |
| `ccdi-dcc-model-props-3.yml`        | `python tests/term_verify/ccdi_dcc_term_verify.py` | `reports/term_value/CCDI-DCC/` |


- **Source:** CBIIT / model release artifacts (same tree as `mdb/data-models-yaml/` in `termValue_verification_scripts`).

Each model writes final reports as `{prefix}_term_endpoint_verification_report.csv` and `{prefix}_term_endpoint_verification_report.md` (prefixes: `ccdi_`, `c3dc_`, `ctdc_`, `icdc_`, `cds_`, `ccdi_dcc_`).

#### 3.8.3 Architecture

Each `tests/term_verify/*_term_verify.py` module defines a thin subclass of [TermVerifyPipeline](../src/sts_test_framework/term_verify_pipeline.py). The base class implements the shared extract / enrich / verify stages and CLI; each subclass defines `parse_yaml()` and any model-specific overrides (for example CDS skips handle-to-value enrichment; CCDI-DCC may fetch remote enum YAML and uses a known-missing allowlist). Shared helpers such as `verify_row`, `strip_inline_yaml_comment`, and `clean_enum_value` live in [term_verify_utils.py](../src/sts_test_framework/term_verify_utils.py).

#### 3.8.4 Pipeline stages (extract → enrich → verify)

Each runner executes **three stages** against its default YAML (override with the CLI `--yaml` path when supported):

1. **Extract** — Parse the YAML and list every enumerated value per property (often the term **handle** in STS, not the human-readable label). Writes a summary CSV and a flat “query” CSV.
2. **Enrich** — Call the live STS API: discover model version, map each property to a node, and (for most models) page `GET .../property/{propHandle}/terms` to fill `term_value` with the API **value** for each YAML handle. Rows also get `model_handle`, `version_string`, `node_handle`.
3. **Verify** — For each row, the client performs:
  `GET {STS_BASE_URL}/model/{modelHandle}/version/{versionString}/node/{nodeHandle}/property/{propHandle}/term/{encodedTermValue}`
   (path segments are URL-encoded; `STS_BASE_URL` includes `/v2`, same as elsewhere in this doc). A row **passes** if the response is **200**, the body is a **JSON array**, and **at least one** element has `"value"` equal to the string used in the path.
   **What goes in `{encodedTermValue}`:**
  - **CCDI, C3DC, CTDC, ICDC** — The enriched `term_value` (handle → value from `/terms`). Rows with no resolved `term_value` are skipped for HTTP.
  - **CCDI-DCC** — Same enrich as above; verify uses `(term_value or enum_value)` when non-empty after trim (legacy behavior). Extract may **fetch remote** `http(s)` **YAML** for some enum lines and merge values.
  - **CDS** — Enrich does **not** call `/terms`; it only fills model / version / node. The path segment is the YAML `enum_value` directly.

#### 3.8.5 How to run

**All commons** (from repo root):

```bash
bash scripts/run_all_term_verify.sh
```

**One commons** (repeat `PYTHONPATH=src` if you have not run `pip install -e .`):

```bash
PYTHONPATH=src python tests/term_verify/ccdi_term_verify.py
```

**Against a specific STS base** (optional; otherwise `STS_BASE_URL` or the default QA URL from config is used):

```bash
PYTHONPATH=src python tests/term_verify/ccdi_term_verify.py --base-url https://sts-qa.cancer.gov/v2
PYTHONPATH=src python tests/term_verify/c3dc_term_verify.py --base-url https://sts-qa.cancer.gov/v2
PYTHONPATH=src python tests/term_verify/ctdc_term_verify.py --base-url https://sts-qa.cancer.gov/v2
PYTHONPATH=src python tests/term_verify/icdc_term_verify.py --base-url https://sts-qa.cancer.gov/v2
PYTHONPATH=src python tests/term_verify/cds_term_verify.py --base-url https://sts-qa.cancer.gov/v2
PYTHONPATH=src python tests/term_verify/ccdi_dcc_term_verify.py --base-url https://sts-qa.cancer.gov/v2
```

`[project.scripts]` in [pyproject.toml](../pyproject.toml) exposes `sts-test` for the OpenAPI CLI only; term-verify runners are the `python tests/term_verify/<model>_term_verify.py` commands above.

#### 3.8.6 Outputs and intermediate artifacts

Artifacts are written under `reports/term_value/<MODEL>/` by default (`--out-dir` overrides). The flow is always: **summary + query CSV → enriched CSV → verification report**.


| Stage       | Typical filename                                   | What it represents                                                                                                                                                               |
| ----------- | -------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Extract** | `{prefix}enum_properties_summary.csv`              | One row per YAML property with an `Enum` block: property id, description, enum count, pipe-separated enum strings.                                                               |
| **Extract** | `{prefix}enum_terms_for_verification.csv`          | One row per candidate term: each `(prop_handle, enum_value)` from the YAML. Empty columns are filled in later stages.                                                            |
| **Enrich**  | `{prefix}enum_terms_for_verification_enriched.csv` | Same rows after STS calls: `model_handle`, `version_string`, `node_handle`, and (except **CDS**) `term_value` from paginated `GET .../property/.../terms`. Main input to verify. |
| **Verify**  | `{prefix}term_endpoint_verification_report.csv`    | One row per HTTP check: `http_status`, `passed`, `notes`. Skipped rows (e.g. no resolvable URL value) do not appear.                                                             |


A Markdown companion `{prefix}term_endpoint_verification_report.md` is also written (summary, counts, short failure preview; full detail in the CSV). For triage, use the final `.md` for a readable summary and the `.csv` for per-row filtering.

#### 3.8.7 Column reference (CSVs)

**Shared columns:**


| Column                                            | Meaning                                                                                                                                          |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `prop_handle`                                     | Property key from the YAML (STS property handle).                                                                                                |
| `description`                                     | Property `Desc:` text from the YAML (where present).                                                                                             |
| `enum_count`                                      | Number of enum entries for that property (summary CSV only).                                                                                     |
| `enum_values`                                     | Pipe-separated enum strings for that property (summary CSV only).                                                                                |
| `enum_value`                                      | Single enum line from the YAML. For CCDI-like models this is usually the **term handle**; for CDS it is already the string used in the term URL. |
| `term_value`                                      | STS term **value** from `/terms` via handle→value; empty until enrich except CDS omits this column in extract/enriched CSVs.                     |
| `model_handle` / `version_string` / `node_handle` | Resolved STS path segments for the term GET.                                                                                                     |
| `http_status`                                     | HTTP status from the term-by-value GET.                                                                                                          |
| `passed`                                          | `True` if status is 200, body is a JSON array, and some element has `"value"` matching the checked string.                                       |
| `notes`                                           | Short diagnostic when `passed` is false.                                                                                                         |


**Model-specific report CSV columns:**

- **CCDI, C3DC, CTDC, ICDC** — `prop_handle`, `enum_value`, `term_value`, `http_status`, `passed`, `notes`. Only rows with non-empty enriched `term_value` are verified.
- **CCDI-DCC** — Same columns; the URL may use `term_value` or `enum_value`. Extract may merge enums from remote `http(s)` YAML when an enum line is a URL.
- **CDS** — `prop_handle`, `enum_value`, `http_status`, `passed`, `notes` only (no `term_value`); the URL uses `enum_value` directly.

#### 3.8.8 Flags and CCDI-DCC allowlist

**Useful flags** (term-verify CLIs; forwarded by `run_all_term_verify.sh`):

- **`--base-url`** — STS v2 root including `/v2` (overrides `STS_BASE_URL` for that run).
- **`--limit N`** — Verify at most the first N rows (after enrich).
- **`--warn-only`** — Exit **0** even when some rows fail (failures still appear in reports).

```bash
python tests/term_verify/ctdc_term_verify.py --limit 50
python tests/term_verify/ctdc_term_verify.py --warn-only
```

**CCDI-DCC only:** A fixed allowlist of `(prop_handle, enum_value)` pairs (see `KNOWN_MISSING_IN_STS_DB` in `tests/term_verify/ccdi_dcc_term_verify.py`) marks rows expected to be missing from the STS graph DB. Those rows still appear as **failed** in the CSV/MD, but the process exits **0** unless there is at least one **non-allowlisted** failure. Use `--warn-only` to force exit **0** when any unexpected failure exists.

---

## 4. Project structure

### 4.1 Layout

```
sts-spec-test-automation/
├── README.md                 # Entry point: install, web UI + CLI run paths (complement to this doc)
├── launcher.py               # Cross-platform: spawns Flask, opens browser (see §4.3)
├── launcher.command          # macOS Finder double-click → launcher.py
├── launcher.bat              # Windows Explorer double-click → launcher.py
├── pyproject.toml            # Package metadata and core dependencies
├── requirements.txt          # pip install -r: core deps, Flask (UI), boto3 (optional parser_agent / Bedrock)
├── ui/
│   ├── app.py                # Flask app: /run, /stream (SSE), /status, /stop
│   └── templates/
│       └── index.html        # Test runner UI (single page + SSE client)
├── spec/
│   └── v2.json               # OpenAPI spec for STS v2 (source of truth; do not edit by hand unless you own the API)
├── src/sts_test_framework/   # Main framework code
│   ├── __init__.py
│   ├── loader.py              # Load spec file; get paths/schemas; normalize paths
│   ├── client.py              # HTTP client (GET, base URL, timeout, SSL); APIResponse
│   ├── discover.py            # Live discovery → test_data dict
│   ├── generator.py           # spec + test_data → list of test cases
│   ├── cli.py                 # Command-line entry (--spec, --base-url, --report, --tags)
│   ├── runners/
│   │   ├── functional.py      # Run cases, assert status (and optional shape)
│   │   └── contract.py        # Optional: validate 200 responses against schema
│   └── reporters/
│       ├── report.py          # Aggregate results; write JSON report
│       └── html_report.py     # Write HTML report
│   ├── term_verify_pipeline.py # Base class for all term-verify pipelines (extract/enrich/verify/CLI)
│   └── term_verify_utils.py    # Shared utilities: verify_row, strip_inline_yaml_comment, clean_enum_value
├── tests/
│   ├── conftest.py            # Pytest fixtures: spec, api_client, test_data, generated_cases
│   ├── unit/                  # Unit tests: runner helpers (mocked APIResponse only)
│   │   ├── test_pagination_pair_shape.py
│   │   ├── test_pagination_assert_shape.py
│   │   └── test_model_pvs_skip_oob_shape.py
│   ├── test_manual/           # Hand-written tests (e.g. /id by type, model-pvs dedup)
│   │   ├── test_id_by_type.py
│   │   └── test_model_pvs_no_duplicates.py
│   └── test_generated/        # Dynamic tests: one test per generated case
│       └── test_from_spec.py   # Uses pytest_generate_tests to parametrize by case
├── data/data-models-yaml/     # Vendored property YAML; catalog and pipeline: §3.8
├── logs/                      # Captured tee logs from convenience scripts (manual, autogenerated, term-verify, full suite)
├── parser_agent/              # Optional AI (Bedrock) log parser: detect failures in a log → Markdown summary
├── reports/                   # Default output for timestamped report_*.json and report_*.html
│   ├── agent-summaries/       # parser_agent output: summary_*.md when AWS creds are set and failures exist
│   └── term_value/            # YAML-driven term-by-value reports (CCDI, C3DC, CTDC, ICDC, CDS, CCDI-DCC, …)
└── docs/
    └── ONBOARDING.md          # This document (full onboarding)
```

**Why this layout?**

- **ui/**, **launcher.*** – Optional **STS Test Runner** web UI (Flask) and double-click / `python launcher.py` entry points; see [§4.3](#43-web-test-runner-ui-how-it-is-built).
- **spec/** – Keeps the API contract in one place; the rest of the code only reads it.
- **src/sts_test_framework/** – Reusable library: loader, client, discover, generator, runners, reporters. The CLI and pytest both use these.
- **tests/conftest.py** – Shared fixtures so that both manual and generated tests get the same `api_client` and `test_data` without repeating setup.
- **test_manual/** vs **test_generated/** vs **unit/** – Manual tests are for things that don’t fit the “one endpoint, one positive/negative case” pattern (e.g. `/id` by entity type, model-PVS duplicate checks). **Unit** tests under `tests/unit/` exercise `functional.py` helpers with mocks (no live API). **Full term-by-value coverage per commons** (YAML → enrich → verify) is run via standalone scripts under `tests/term_verify/` (e.g. `python tests/term_verify/ccdi_term_verify.py`), not pytest. Generated tests are the bulk of coverage and come from the spec.
- **Term-verify architecture** -- Each `tests/term_verify/*_term_verify.py` script is a thin subclass of `TermVerifyPipeline` (in `src/sts_test_framework/term_verify_pipeline.py`). The base class implements the shared extract/enrich/verify stages and CLI; each subclass only defines `parse_yaml()` and any model-specific overrides. Shared utilities (`verify_row`, `strip_inline_yaml_comment`, `clean_enum_value`) live in `src/sts_test_framework/term_verify_utils.py`.

### 4.2 Design principles

These choices apply across the generated suite, manual tests, and term-verify pipelines.

- **Spec-driven tests** – When the API spec changes, you re-run the generator instead of rewriting many hand-maintained cases. The spec remains the contract the framework enforces.
- **Discovery instead of hardcoding** – Real model/node/property/tag values can differ between environments. Runtime discovery lets the same tests run wherever the API has data.
- **Positive and negative cases** – Coverage includes invalid IDs and bad parameters so the API returns documented errors (404/422), not opaque 500s or wrong bodies.
- **Single HTTP client** – All requests share one configurable client (base URL, timeout, SSL), so switching environments or adding logging stays straightforward.
- **Several ways to run** – **Web UI** ([§5.0](#50-web-test-runner-ui-recommended)) for local runs with environment and suite pickers; **pytest** for developers and CI; **CLI** and shell scripts for full runs, timestamped reports, and automation (e.g. scheduled jobs).
- **JSON + HTML reports** – JSON for tooling and metrics; HTML for humans and CI artifacts.

### 4.3 Web test runner UI (how it is built)

The **STS Test Runner** is a small **Flask** application under `ui/` plus cross-platform launchers at the repo root.

**Stack**

- **Backend:** `ui/app.py` — `Flask` app with a Jinja template `ui/templates/index.html` for the main page.
- **Frontend:** The template loads JavaScript that opens an **EventSource** connection to **`GET /stream/<run_id>`** (Server-Sent Events) to append live **stdout/stderr** lines from the test subprocess.

**HTTP routes** (see module docstring in `ui/app.py`)

| Route | Role |
| ----- | ---- |
| `GET /` | Serve the UI |
| `POST /run` | Start a suite; JSON body: `env` (qa \| stage \| prod), `suite` (full \| manual \| autogenerated \| term_verify); returns `run_id` |
| `GET /stream/<run_id>` | SSE: `log` events (line text) then final `done` (exit code, stage) |
| `POST /stop/<run_id>` | Terminate the run’s process group |
| `GET /status` | JSON: idle \| running \| done, elapsed time, suite, env, exit code (used by `launcher.py` to wait for readiness) |

**Run flow**

1. User chooses presets; browser calls **`POST /run`**.
2. Server builds **`subprocess.Popen`** with `cwd=PROJECT_ROOT`, sets **`STS_BASE_URL`** from an internal map (`ENVIRONMENTS`), and prepends **`src`** to **`PYTHONPATH`** so scripts resolve `sts_test_framework`.
3. **`SUITES`** maps suite keys to the same argv as the convenience scripts (e.g. `bash scripts/run_full_suite.sh`, `python scripts/run_autogenerated_tests.py`).
4. A background thread reads the process **stdout** line-by-line into a **queue**; the SSE generator drains the queue. For **full** suite, **stage** (1/3–3/3) is inferred from markers in the shell script output.
5. Only **one run at a time**; a second `POST /run` while busy returns **409**.

**Launchers**

- **`launcher.py`** picks a free port starting at **5678**, spawns `python -m flask --app ui/app.py run --port <port> --no-reload` in a subprocess, waits until **`GET /status`** responds, then opens the default browser. Do **not** set **`WERKZEUG_RUN_MAIN`** in that subprocess: with Flask 3 / Werkzeug 3 it can trigger a code path that expects **`WERKZEUG_SERVER_FD`** and crashes with `KeyError`.
- **`launcher.command`** (macOS) and **`launcher.bat`** (Windows) `cd` to the repo, activate `.venv` if present, and run **`launcher.py`**.

**Extension points**

- Add or change **STS environments:** edit **`ENVIRONMENTS`** in `ui/app.py`.
- Add or change **suites:** edit **`SUITES`** (keep parity with `scripts/` for predictable reports).
- UX: **`ui/templates/index.html`** (layout, labels, SSE handling).

**Limitations**

- **Custom base URLs** not in the UI dropdown still require **CLI** / **`export STS_BASE_URL`**.
- **Windows:** suites **`full`**, **`manual`**, and **`term_verify`** invoke **`bash`**; without Git Bash (or another `bash` on `PATH`), use **autogenerated** only from the UI or run from **Git Bash** / WSL. **Stop** uses Unix-style process groups (`os.killpg`); behavior may differ on Windows if process group semantics differ.
- **macOS / Linux:** `bash` is normally available.

---

## 5. How to run the framework

For what each **suite** covers, see [§3.6](#36-three-runnable-test-suites-overview)–[§3.8](#38-term-by-value-yaml--sts).

### 5.0 Web test runner UI (recommended)

After [§5.1 Prerequisites](#51-prerequisites) (venv, `pip install -r requirements.txt`, `pip install -e .`), you can drive the same workflows as [§5.8](#58-convenience-shell-scripts) from a browser.

**Start the UI**

| Platform | Action |
| -------- | ------ |
| **macOS** | Double-click [`launcher.command`](../launcher.command), or from a terminal with venv active: **`python launcher.py`** |
| **Windows** | Double-click [`launcher.bat`](../launcher.bat), or from a terminal with venv active: **`python launcher.py`** |

The launcher prints the URL (default **http://localhost:5678**; if that port is in use, the next free port is chosen). Your browser should open automatically once the server is ready.

**In the browser**

1. Select **STS environment:** QA, stage, or prod (maps to the same URLs as in `ui/app.py` — equivalent to setting `STS_BASE_URL` for that run).
2. Select **suite:** **Full** (manual → autogenerated → term-verify), or one of **Manual**, **Autogenerated**, **Term verify** only.
3. Click run; watch the **live log**. Use **Stop** to terminate the subprocess tree (same as interrupting a script).
4. When finished, open reports under **`reports/`** (and **`logs/`** if scripts tee there). Which artifact to open: [§7.2](#72-which-file-should-i-open).

**Windows:** For **Full**, **Manual**, or **Term verify**, ensure **`bash`** is on `PATH` (e.g. **Git Bash**). **Autogenerated** does not need `bash`.

**When to use CLI instead**

- CI, cron, or any **headless** automation.
- **Custom** `STS_BASE_URL` or extra **environment variables** not exposed in the UI.
- **Forwarded arguments** (e.g. `bash scripts/run_manual_tests.sh -m nullcde`).

Implementation details: [§4.3](#43-web-test-runner-ui-how-it-is-built).

### 5.1 Prerequisites

- **Python 3.9+**
- Install dependencies and the package so `sts_test_framework` is importable. The optional **AI parser agent** (`parser_agent`, LLM-assisted via Amazon Bedrock) runs only when `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_REGION` are all set—used by `run_manual_tests.sh`, `run_autogenerated_tests.py`, `run_all_term_verify.sh`, and `run_full_suite.sh` (each prints a short notice at the start and skips `python3 parser_agent/...` when unset; requires **boto3** when enabled). Use `requirements.txt` (includes boto3) or `pip install -e ".[agent]"` when you use the parser. See [§5.8](#58-convenience-shell-scripts) and [§7.4](#74-optional-ai-failure-summaries-parser-agent).
  ```bash
  cd mdb/sts-test-framework-agent
  pip install -r requirements.txt
  pip install -e .
  ```
  Or use a virtual environment (recommended):
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate   # or .venv\Scripts\activate on Windows
  pip install -r requirements.txt
  pip install -e .
  ```

### 5.2 Configuration: environment variables

The framework does **not** read a repo config file and does **not** auto-load `.env`. It reads **environment variables** (e.g. `os.getenv("STS_BASE_URL")`). Control the base URL, SSL behavior, and report directory by **setting those variables** before pytest or the CLI, or pass `--base-url` to the CLI only.

**How do I set the variables?**

**1) Command line (one-off run)**  
Prefix the variable for a single command (pytest or CLI):

```bash
STS_BASE_URL=https://sts-qa.cancer.gov/v2 pytest tests/ -v
STS_BASE_URL=https://sts-qa.cancer.gov/v2 python -m sts_test_framework.cli --report reports/
```

For the **CLI only**, you can instead pass `--base-url` (overrides `STS_BASE_URL` for that invocation):

```bash
python -m sts_test_framework.cli --base-url https://sts-qa.cancer.gov/v2 --report reports/
```

Pytest has **no** `--base-url` flag; it always uses `STS_BASE_URL` from the environment (or the default QA URL).

**2) Shell session (current terminal)**  
Export so every command in that session uses the value:

```bash
export STS_BASE_URL=https://sts-qa.cancer.gov/v2
pytest tests/ -v
python -m sts_test_framework.cli --report reports/
```

**3) CI (e.g. GitHub Actions)**  
Set the variables in the job's `env` block so each run targets the right environment (see "Running against QA, stage, or prod" below).

**Variable reference:**

Implementation detail: base URL resolution lives in [sts_test_framework.config.sts_base_url()](../src/sts_test_framework/config.py) (`STS_BASE_URL` or default QA). Pytest prints `STS environment: <url>` at the start of each run (see `tests/conftest.py`).


| Variable                    | Meaning                                                                                                                                                                                                         | Default                                          |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------ |
| `STS_BASE_URL`              | Base URL of the STS v2 API (pytest, CLI, and `APIClient`; include `/v2`)                                                                                                                                        | `https://sts-qa.cancer.gov/v2`                   |
| `STS_SSL_VERIFY`            | Set to `false` to disable SSL certificate verification (e.g. local/dev with self-signed certs)                                                                                                                  | `true`                                           |
| `REPORT_DIR`                | Directory where the CLI writes timestamped `report_YYYY-MM-DDTHH-MM-SS.json` and `.html` (each run gets its own files)                                                                                          | `reports`                                        |
| `STS_MODELS`                | Comma-separated model handles for `scripts/run_autogenerated_tests.py` only (subset of models)                                                                                                                  | (all models in script)                           |
| `STS_DEDUP_LIMIT`           | Total discovered cases for `test_model_pvs_no_duplicates.py`; split across `MAJOR_MODELS` (fair: `limit // n` plus remainder to first models). Default **140** with **7** models → **20** properties per model. | `140`                                            |
| `STS_PARALLEL_WORKERS`      | Max models to run concurrently in `scripts/run_autogenerated_tests.py` (default `1` sequential; increase e.g. `2`, `8` for parallel)                                                                            | `1`                                              |
| `CADSR_BASE_URL`            | Root URL for the caDSR REST API (manual modules; paths like `/DataElement/{publicId}`). See [§3.7.1](#371-cadsr-and-legacy-cde-pvs-reference).                                                                  | `https://cadsrapi.cancer.gov/rad/NCIAPI/1.0/api` |
| `CADSR_DESIGNATION_TYPES`   | Optional: comma-separated `Designations[].type` values to **limit** which names must appear in STS; unset or `*` means **all** types. See [§3.7.1](#371-cadsr-and-legacy-cde-pvs-reference).                    | (unset = all)                                    |
| `CADSR_GET_MAX_ATTEMPTS`    | Manual caDSR DataElement GET: max attempts (including the first try) before failing on retryable errors. See [§3.7.1](#371-cadsr-and-legacy-cde-pvs-reference).                                                 | `4`                                              |
| `CADSR_GET_RETRY_DELAY_SEC` | Seconds to wait between retryable caDSR DataElement GET attempts. See [§3.7.1](#371-cadsr-and-legacy-cde-pvs-reference).                                                                                        | `2.0`                                            |


**Optional parser agent** (`run_manual_tests.sh`, `run_autogenerated_tests.py`, `run_all_term_verify.sh`, `run_full_suite.sh`): Bedrock summaries run only when all of `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_REGION` are set and non-empty. If any is missing, each script skips invoking the parser (no boto3 import). Shared bash helpers live in `scripts/parser_agent_hook.sh`. Requires **boto3** when enabled.

`STS_QA_URL` is **not** read by the framework—use `STS_BASE_URL` for QA (or any environment).

If you don’t set these, the defaults are used. The framework needs **network access** to the STS server for discovery and for running the tests.

#### Running against QA, stage, or prod

The **same tests** run against any environment; only the **base URL** (and optionally SSL) changes. Set `STS_BASE_URL` to the v2 base URL of the environment you want to hit.

**Examples (replace with your real URLs if different):**


| Environment | Typical use                | Set `STS_BASE_URL` to (example)              |
| ----------- | -------------------------- | -------------------------------------------- |
| **Prod**    | Final validation           | `https://sts.cancer.gov/v2`                  |
| **Stage**   | Pre-release checks         | `https://sts-stage.cancer.gov/v2`            |
| **QA**      | Feature testing, debugging | `https://sts-qa.cancer.gov/v2`               |
| **Local**   | Dev server                 | `http://localhost:8000/v2` (or your dev URL) |


**From the command line:**

```bash
# Run against QA
STS_BASE_URL=https://sts-qa.cancer.gov/v2 pytest tests/ -v

# Run against QA and write reports
STS_BASE_URL=https://sts-qa.cancer.gov/v2 python -m sts_test_framework.cli --report reports/

# Or use --base-url (CLI only; overrides env var)
python -m sts_test_framework.cli --base-url https://sts-qa.cancer.gov/v2 --report reports/
```

**In CI**, set the variable per job so each pipeline runs against the right environment:

```yaml
# Example: GitHub Actions – QA job
- name: Run STS tests against QA
  env:
    STS_BASE_URL: https://sts-qa.cancer.gov/v2
  run: python -m sts_test_framework.cli --report reports/

# Example: Prod job (e.g. after deploy)
- name: Run STS tests against prod
  env:
    STS_BASE_URL: https://sts.cancer.gov/v2
  run: python -m sts_test_framework.cli --report reports/
```

**Local or dev with self-signed certificates:**  
If your dev server uses HTTPS with a self-signed cert, set `STS_SSL_VERIFY=false` so the client doesn’t reject the certificate (use only in dev, not prod):

```bash
STS_BASE_URL=https://my-dev-server.local/v2 STS_SSL_VERIFY=false pytest tests/ -v
```

### 5.3 Three ways to run: web UI, pytest, CLI

The framework can be run in **three** complementary ways. The **web UI** ([§5.0](#50-web-test-runner-ui-recommended)) wraps the same shell scripts and sets `STS_BASE_URL` from presets—best for **local** interactive runs. **pytest** and the **CLI** share the same spec, discovery, and generator for generated coverage; the difference is how you invoke them and what artifacts you get.

|                | **Web UI**                                                                                    | **pytest**                                                                                                                                | **CLI**                                                                                                                                |
| -------------- | --------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| **What it is** | Flask app + browser; starts subprocesses for full / manual / autogenerated / term-verify.     | Standard Python test runner; each generated case is one pytest test.                                                                      | A standalone script that runs the framework and writes report files.                                                                   |
| **Output**     | Live log in browser; same `reports/` and `logs/` as the underlying scripts.                   | Pytest’s usual pass/fail output (and any pytest plugins, e.g. html). Does *not* write the framework’s report files unless you add a hook. | Always writes timestamped `report_*.json` and `report_*.html` to the folder you choose (each run gets its own pair).                   |
| **Best for**   | Picking QA/stage/prod and a suite without typing shell commands.                              | Day-to-day development, debugging, running a single test or subset, IDE integration.                                                      | Getting the framework’s reports every time, scripts/cron/CI, or using options like `--tags` / `--no-negative` without touching pytest. |


**Use the web UI when:** You want to pick **QA / stage / prod** and a **suite** from the browser, see a **live log**, and avoid shell one-liners locally ([§5.0](#50-web-test-runner-ui-recommended)).

**Use pytest when:** You want to run one test or a subset (e.g. only `test_manual`), use your IDE’s “Run Test” button, or integrate STS tests into a larger pytest suite. You don’t need the framework’s HTML/JSON reports for that run.

**Use the CLI when:** You want `report.json` and `report.html` written after every run, you’re calling from a script or CI job, or you want to pass `--tags id,model` or `--no-negative` on the command line. The CLI exits with code 0 (all passed) or 1 (any failed), which is easy for CI to interpret.

### 5.4 Run with pytest (recommended for day-to-day work)

For **timestamped HTML/JSON reports** for the OpenAPI-generated GET suite (especially **per data model**), use `python scripts/run_autogenerated_tests.py` or `python -m sts_test_framework.cli --report ...` rather than pytest alone. The `tests/test_generated/` tree remains the pytest-based way to run the same generated cases when you want IDE integration or a single-process `pytest tests/ -v` run.

From the project root:

```bash
pytest tests/ -v
```

- **-v** = verbose (one line per test).
- This runs both **manual** tests (e.g. `test_manual/test_root.py`) and **generated** tests (`test_generated/test_from_spec.py`). The generated tests are created at **collection time**: pytest calls the generator and gets one test per case.

To run only manual or only generated:

```bash
pytest tests/test_manual/ -v
pytest tests/test_generated/ -v
```

**Example:** You’re fixing a bug and want to run only the “models” tests. With pytest you can run `pytest tests/test_generated/ -v -k "models"` (if test ids include the tag) or add a pytest marker later. With the CLI you’d run `python -m sts_test_framework.cli --tags models`.

### 5.5 Run with the CLI (for reports and scriptable runs)

The CLI loads the spec, runs discovery, generates cases, runs them, and **always** writes JSON + HTML reports. It does **not** use pytest.

```bash
python -m sts_test_framework.cli
```

Defaults: spec = `spec/v2.json`, base URL = `STS_BASE_URL` or `https://sts-qa.cancer.gov/v2` (same default as `DEFAULT_STS_BASE_URL` in [sts_test_framework/config.py](../src/sts_test_framework/config.py)), report dir = `reports/`. For **prod**, **stage**, or **local**, set `STS_BASE_URL` or pass `--base-url` (see [§5.2](#52-configuration-environment-variables)).

**Example:** Your CI job runs after every deploy. You run `python -m sts_test_framework.cli --report reports/` and publish `reports/report.html` as an artifact so the team can open it and see which endpoints passed or failed. You don’t need pytest in that job—just the CLI and the report files.

**Useful options:**

```bash
# Custom spec and base URL
python -m sts_test_framework.cli --spec spec/v2.json --base-url https://sts.cancer.gov/v2

# Write reports to a specific folder
python -m sts_test_framework.cli --report reports/

# Run only certain endpoint groups (by OpenAPI tag)
python -m sts_test_framework.cli --tags id,model,models

# Run only positive cases (skip negative 404/422 tests)
python -m sts_test_framework.cli --no-negative

# Test a specific data model (e.g. PSDC, CTDC)
python -m sts_test_framework.cli --report reports/ --model PSDC

# Use the latest release version for that model (no pre-release hash)
python -m sts_test_framework.cli --report reports/ --model PSDC --release
```

- `--model <handle>` – Model handle to test (e.g. `PSDC`, `C3DC`, `CDS`). Discovery uses this model and its version for all path parameters. If omitted, the first model returned by `/models/` is used.
- `--release` – Use the latest **release** version from `/model/{handle}/versions`. A release version is one whose string has no hyphen (e.g. `2.1.0`). If the model has no release versions, the first available version is used. Without `--release`, the first version in the list (which may be a pre-release) is used.

When any test fails, the CLI exits with code 1 so CI can detect failure.

### 5.6 Running all data models in one go (multi-model runner)

To run the full test suite once **per data model** (CDS, CCDI, CCDI-DCC, ICDC, CTDC, C3DC, PSDC) and get separate reports per model, use the **multi-model runner** script:

```bash
# From project root; uses STS_BASE_URL (default: https://sts-qa.cancer.gov/v2)
python scripts/run_autogenerated_tests.py
```

**Behavior:**

- Runs the CLI once per model with `--model <handle>` and `--release`, **sequentially** by default (`STS_PARALLEL_WORKERS=1`). Set `STS_PARALLEL_WORKERS` to `2`, `8`, etc. to run up to that many models at a time.
- Writes reports to `reports/<model>/` (e.g. `reports/PSDC/report_2025-03-12T14-30-45.html` and `.json`). Each run gets timestamped files so previous reports are not overwritten.
- Exits with code **1** if any model run fails, so CI can detect failure.
- Prints a per-model `[PASS]`/`[FAIL]` line as each model completes and a summary at the end with wall-clock time.

**Environment variables:** Same as the [§5.2 variable reference](#52-configuration-environment-variables) for `STS_BASE_URL`, `STS_MODELS`, and `STS_PARALLEL_WORKERS`. This script defaults to all models **CDS, CCDI, CCDI-DCC, ICDC, CTDC, C3DC, PSDC** when `STS_MODELS` is unset, and writes reports under `reports/<ModelHandle>/` (not the flat `reports/` used by a single CLI run).

**Example – run only PSDC and CTDC:**

```bash
STS_MODELS=PSDC,CTDC python scripts/run_autogenerated_tests.py
```

**Example – run against prod:**

```bash
STS_BASE_URL=https://sts.cancer.gov/v2 python scripts/run_autogenerated_tests.py
```

### 5.7 What happens when you run (under the hood)

Whether you use **pytest** or the **CLI**, the same pipeline runs: load spec → create client → discover → generate cases → run cases. The CLI then adds the report step.

**Short summary:**

1. **Load spec** – Read `spec/v2.json` (or the path you gave); parse as JSON or YAML into a dict with paths and schemas.
2. **Create client** – HTTP client with the chosen base URL (and optional SSL verify from env).
3. **Discovery** – GET models → nodes → properties → terms, GET tags; build `test_data` with real handles and IDs.
4. **Generate cases** – For each GET operation in the spec, build positive (200) and optionally negative (404/422) cases using `test_data`.
5. **Run** – For each case, GET the path (with params), compare status to expected, optionally check response shape; record pass/fail and duration.
6. **Report** – Aggregate results, write timestamped `report_YYYY-MM-DDTHH-MM-SS.json` and `.html` (CLI only); each run gets its own files.

A more detailed breakdown of each step is below.

---

#### Step 1: Load the spec

- **What happens:** The framework reads the spec file from disk (e.g. `spec/v2.json`). The file may be JSON or YAML; the loader tries to parse it as JSON first, then falls back to YAML if needed.
- **Result:** A Python dictionary with at least:
  - `paths` – each key is a path template (e.g. `/v2/models/`, `/v2/id/{id}`); each value describes the HTTP methods and their parameters and responses.
  - `components.schemas` – reusable response/request body schemas (e.g. `Model`, `Node`, `Entity`).
- **Used by:** The generator reads `paths` to know every endpoint and its parameters; the contract runner (if used) reads `components.schemas` to validate response bodies.

---

#### Step 2: Create the HTTP client

- **What happens:** An `APIClient` instance is created with the base URL (from `--base-url`, or from the `STS_BASE_URL` environment variable, or the default `https://sts-qa.cancer.gov/v2` in `[sts_test_framework/config.py](../src/sts_test_framework/config.py)`). The client also reads `STS_SSL_VERIFY` from the environment to decide whether to verify HTTPS certificates.
- **Result:** A single client used for all subsequent requests. Every request is `GET`; the client builds the full URL as `base_url + path` (and appends query parameters when provided). Each response is wrapped in an `APIResponse` object (status code, body, parsed JSON if applicable, and request duration).
- **Used by:** Discovery and the test run both use this client.

---

#### Step 3: Discovery

- **What happens:** The framework calls the live API once to collect real IDs and values. It does **not** use the spec for this; it follows a fixed sequence of requests:
  1. **GET** the models list (e.g. `/models/`). From the response it takes the **first** model’s `handle`, `version`, and `nanoid` and stores them in a `test_data` dict.
  2. **GET** the nodes for that model (path like `/model/{modelHandle}/version/{versionString}/nodes`). From the first few nodes it then:
    - **GET** the properties for each node (path like `.../node/{nodeHandle}/properties`). It keeps the first property’s `handle` and `nanoid`, and the node’s `handle` and `nanoid`.
    - For up to a few properties, **GET** the terms (path like `.../property/{propHandle}/terms`). When it finds a non-empty term list, it takes one term’s `value` and stores it (so we have a real value for the “get term by value” endpoint).
  3. **GET** the tags list (`/tags/`). It takes the first tag’s `key`, `value`, and `nanoid`.
  4. Optionally **GET** the model-pvs endpoint for that model and property to mark that model-pvs data is available.
- **Result:** A `test_data` dictionary with keys such as `model_handle`, `model_version`, `node_handle`, `prop_handle`, `term_value`, `tag_key`, `tag_value`, and various `*_nanoid` values. If any request fails or returns no data, the corresponding keys may be missing; the generator will then skip building positive cases for endpoints that need those values.
- **Used by:** The generator uses `test_data` to fill path and query parameters when building positive test cases.

---

#### Step 4: Generate test cases

- **What happens:** The generator walks every path and HTTP method in the spec (for STS v2, only GET). For each operation it:
  - Reads the **path parameters** (e.g. `id`, `modelHandle`, `versionString`, `nodeHandle`) and **query parameters** (e.g. `skip`, `limit`) from the spec.
  - **Positive case:** It tries to resolve each path parameter from `test_data` (e.g. `modelHandle` → `test_data["model_handle"]`). If it can resolve all of them, it builds a concrete path by substituting those values into the template (e.g. `/v2/model/ccdi/version/1.0/nodes` → normalized to `/model/ccdi/version/1.0/nodes`). It sets default query parameters (e.g. `skip=0`, `limit=10`) where the spec defines them. It then appends one case with `expected_status: 200` and the operation’s summary and response schema ref.
  - **Negative case:** If the spec documents a 404 or 422 response for that operation, the generator adds a second case that uses an **invalid** value (e.g. `invalid_nonexistent_xyz`) for the path parameters. That case expects 404 or 422.
  - **Extra generated case types** (pagination, skip-OOB, etc.): see [§3.3.1](#331-advanced-pagination-skip-oob-and-reporting-quirks).
- **Filtering:** If you passed `--tags` (CLI) or an equivalent filter, only operations whose OpenAPI `tags` match that list are included. If you passed `--no-negative`, negative cases are not added.
- **Result:** A list of **case** dicts. Each case has at least: `path`, `params` (query or `None`), `expected_status`, `operation_id`, `summary`, `tag`, `negative`, and optionally `response_schema_ref`.
- **Used by:** The functional runner (and optionally the contract runner) runs one request per case.

---

#### Step 5: Run the cases (functional run)

- **What happens:** For each case in the list, the runner:
  1. Calls `client.get(path, params)`. The client sends a GET request to `base_url + path` with the given query string, and records the start time. When the response arrives, it parses the body as JSON (if possible) and stores status code, body, parsed JSON, and **duration** in an `APIResponse`.
  2. Compares `response.status_code` to the case’s `expected_status`. If they match, the case is marked passed; otherwise it’s failed and an error message is stored (e.g. “Expected 200, got 404” plus a snippet of the body).
  3. For **positive cases that expected 200** and have a non-null JSON body, the runner optionally runs a **basic shape check**: it looks at the case’s `response_schema_ref` (e.g. `Node`, `Model`) and verifies that the response is an object (or list/int where appropriate) and that expected top-level keys (e.g. `nanoid`) are present. If the shape check fails, the case is marked failed and the error message is updated.
  4. Appends a **result** dict to the list: `operation_id`, `path`, `expected_status`, `actual_status`, `passed`, `duration`, `error` (if any), `tag`, `negative`.
- **Result:** A list of result dicts, one per case, each with pass/fail and timing. No files are written in this step.
- **Used by:** The reporting step (CLI) or, in pytest, the test pass/fail and duration are reported by pytest itself.

**Pytest note:** When you run pytest, **collection** runs the generator (using the same loader, client, and discovery) so that each case becomes one pytest test. **Execution** then runs those tests; each test calls `api_client.get(path, params)` and asserts on status (and basic shape). So the “run” step is the same logic, but invoked once per test by pytest.

---

#### Step 6: Report (CLI only)

- **What happens:** After the functional run, the CLI:
  1. **Aggregates** the result list: total count, passed/failed counts, counts per OpenAPI tag, and per-operation pass/fail and duration. It also computes a **P95 duration** (95th percentile of request durations in milliseconds) from the list of durations.
  2. **Writes a timestamped JSON report** to the report directory: `report_YYYY-MM-DDTHH-MM-SS.json` (e.g. `report_2025-03-12T14-30-45.json`). The file contains the summary (total, passed, failed, by_tag, by_operation, durations_ms, p95_ms, errors) plus the full list of result dicts.
  3. **Writes a timestamped HTML report** to the same directory: `report_YYYY-MM-DDTHH-MM-SS.html`. The HTML is a table: one row per case, with columns for operation ID, summary, path, status (Pass/Fail), expected/actual status, duration, and error message. The summary (total, passed, failed, P95) is shown at the top.
- **Result:** Two files per run in the report directory; each run gets its own pair so previous reports are not overwritten. The CLI then prints a one-line summary (e.g. “Result: 33/41 passed”) and exits with code 0 if all passed or 1 if any failed.

When you run **pytest** only, step 6 does not run unless you add a pytest hook or plugin that calls the same aggregation and report-writing code after the test run.

### 5.8 Convenience shell scripts

These wrap common workflows from the project root. See also **[RUNBOOK.md](RUNBOOK.md)** for a short summary table.

**`scripts/run_manual_tests.sh`**

- Runs: `pytest tests/test_manual/ -v --html=reports/manual_tests.html --self-contained-html`
- Extra arguments are forwarded to pytest (e.g. `-m nullcde`, `-k test_name`).
- Output: standalone **pytest-html** report at `reports/manual_tests.html`. This is separate from the framework CLI’s `report_*.html` (from `python -m sts_test_framework.cli`). The project depends on `pytest-html` for this path.
- After pytest, **parser_agent** runs only if **`AWS_ACCESS_KEY_ID`**, **`AWS_SECRET_ACCESS_KEY`**, and **`AWS_REGION`** are all set (optional Bedrock failure summaries; needs boto3). Otherwise the script prints a short notice and exits with pytest’s status only. Sources `scripts/parser_agent_hook.sh`.

**`scripts/run_autogenerated_tests.py`**

- Runs the STS CLI once per data model (see script docstring for `STS_MODELS`, `STS_PARALLEL_WORKERS`).
- Writes a capture log under `logs/autogenerated_*.log` and, when the three AWS variables are set, runs **parser_agent** on that log after all model runs (same messages and skip behavior as `run_manual_tests.sh`).

**`scripts/run_all_term_verify.sh`**

- Runs every `tests/term_verify/*_term_verify.py` with **limited parallelism** (default **2** concurrent commons pipelines via `STS_TERM_VERIFY_WORKERS`; set to `1` for strictly sequential runs).
- Sets `PYTHONPATH` to include `src/` so `from sts_test_framework...` imports resolve.
- Forwards all arguments to each script (e.g. `--warn-only`, `--limit 50`). Log lines from parallel jobs may interleave in the terminal.
- For per-commons scripts, outputs, and flags, see [§3.8 Term-by-value](#38-term-by-value-yaml--sts).
- After all scripts finish, **parser_agent** runs on the term-verify tee log only when the three AWS variables are set (same hook as `run_manual_tests.sh`).

**`scripts/run_full_suite.sh`**

- Runs the three pipelines **in order**: `run_manual_tests.sh` → `run_autogenerated_tests.py` → `run_all_term_verify.sh`.
- **Always runs all three** stages even if one fails; prints per-stage pass/fail and a short summary. **Exit code 1** if any stage failed (so CI still goes red).
- Does **not** forward command-line arguments; use each script alone when you need `-m nullcde`, `STS_MODELS`, `--warn-only`, etc.
- After the summary, **parser_agent** runs on the **full-suite** tee log only when the three AWS variables are set (stage 1 may also run the parser on the manual log when AWS is set, so two parser passes on different logs are possible).

---

## 6. How to add or change tests

### 6.1 Adding a manual test

Manual tests are for behavior that isn’t “one endpoint, one status check.” Examples: root/health, or “models count equals length of models list.”

1. Add a new file under `tests/test_manual/`, e.g. `test_consistency.py`.
2. Write a function whose name starts with `test`_ and accepts the fixtures you need (e.g. `api_client`, `test_data`).
3. Use `api_client.get(path, params)` and assert on `response.status_code` and, if needed, `response.json()`.

Example (already in the project):

```python
# tests/test_manual/test_root.py
def test_root_returns_200(api_client):
    response = api_client.get("/")
    assert response.status_code == 200
```

You get `api_client` and `test_data` from `conftest.py`; no need to load the spec or run discovery yourself.

### 6.2 Changing what gets discovered

If a new endpoint needs a new kind of ID (e.g. a “study” id), you add the discovery logic in `src/sts_test_framework/discover.py`:

1. Add one or more GET requests to obtain that ID (or list of IDs).
2. Put the result in the `data` dict (e.g. `data["study_id"] = ...`).
3. In `generator.py`, in `_resolve_path_params()` (and optionally `_resolve_query_params()`), add a branch for the new parameter name and set `values[name]` from `test_data` (e.g. `test_data["study_id"]`). If discovery didn’t find a value, return `None` for that endpoint so no positive case is generated until data exists.

### 6.3 Changing how cases are generated

- **New positive/negative rules** – Edit `generator.py`. For example, to add a negative case that sends an invalid query param (e.g. `skip=-1`) and expects 422, you’d add logic that builds a case with that param and `expected_status: 422`.
- **Filter by tag** – When running, use `--tags id,model` (CLI) or, if you add a pytest option, filter the cases in the generator with `tag_filter`.
- **Skip certain operations** – In `_iter_ops()` or in the loop in `generate_cases()`, skip path templates or operation IDs you don’t want to test.
- **Root and count endpoints** – The root endpoint (`/`) is intentionally excluded from the suite. For **count** endpoints (e.g. `.../nodes/count`, `.../properties/count`, `.../entities/count`), invalid path parameters yield **200 with body 0**; **422** is reserved for invalid query parameters (e.g. negative skip/limit).

### 6.4 Adding or changing assertions (functional runner)

In `src/sts_test_framework/runners/functional.py`, each case is run with `client.get(path, params)`. The current logic:

- Asserts `response.status_code == expected_status`.
- For 200, optionally runs `_check_basic_shape(response, case)` (e.g. object has expected keys for a given schema ref).

To add stricter checks (e.g. “every item in the list has a `nanoid`”), extend `_check_basic_shape` or add a new helper and call it from `run_functional_tests` for 200 responses.

### 6.5 Contract validation (optional)

To validate 200 responses against the OpenAPI response schema:

1. Ensure `jsonschema` (and optionally `openapi-spec-validator`) is installed.
2. Call `run_contract_tests(client, cases, spec)` from `runners.contract` (e.g. from the CLI or a separate script).
3. Merge or report contract results alongside functional results. The contract runner uses the spec’s `components.schemas` and the operation’s response schema to validate JSON bodies.

---

## 7. Reports and CI

### 7.1 Report contents

The CLI writes **timestamped** report files so each run keeps its own reports (no overwrite): `report_YYYY-MM-DDTHH-MM-SS.json` and `report_YYYY-MM-DDTHH-MM-SS.html` (e.g. `report_2025-03-12T14-30-45.json`).

- **report_*.json** – Full summary (total/passed/failed, by tag, by operation, durations, errors) plus the list of all results (one per case) with status, duration, and error message if failed.
- **report_*.html** – Human-readable table: operation ID, summary, path, status (Pass/Fail), expected/actual status, duration, error message.

Use the JSON for metrics and automation; use the HTML for quick inspection.

The default **CLI** path exercises the **functional** runner only; it does **not** run **contract** validation (`runners.contract` / `jsonschema` on 200 bodies). To use contract checks, call `run_contract_tests` from a custom script or extended entry point ([§6.5](#65-contract-validation-optional)).

### 7.2 Which file should I open?


| Goal                                                                | Open this                                                                                                                                       |
| ------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| Run **all three** report pipelines in one command                   | `bash scripts/run_full_suite.sh` — then open the artifacts below (`manual_tests.html`, per-model `report_*.html`, term-verify `*.md` / `*.csv`) |
| Did every generated GET pass (single CLI run)?                      | Latest `reports/report_*.html` from `python -m sts_test_framework.cli --report reports/`                                                        |
| Did generated GETs pass **per data model**?                         | Newest `reports/<ModelHandle>/report_*.html` from `python scripts/run_autogenerated_tests.py`                                                   |
| Automate pass rate / export failures                                | The same run’s `report_*.json`                                                                                                                  |
| Manual pytest results as HTML                                       | `reports/manual_tests.html` from `bash scripts/run_manual_tests.sh`                                                                             |
| Manual pytest failed (no HTML run)                                  | Pytest console output; or re-run with `run_manual_tests.sh`                                                                                     |
| Did YAML enum terms resolve in STS?                                 | Latest `reports/term_value/<COMMONS>/*_term_endpoint_verification_report.md` (and matching `.csv` for detail)                                   |
| AI **failure summary** after a run (AWS creds set; failures in log) | Newest `reports/agent-summaries/summary_*.md`                                                                                                   |


### 7.3 Running in CI (e.g. GitHub Actions)

Example:

```yaml
- name: Run STS v2 API tests
  env:
    STS_BASE_URL: ${{ vars.STS_BASE_URL }}
  run: |
    pip install -e .
    python -m sts_test_framework.cli --spec spec/v2.json --report reports/
```

Or run pytest and optionally run the CLI for reports:

```yaml
- run: pip install -e .
- run: pytest tests/ -v --tb=short
- run: python -m sts_test_framework.cli --report reports/
```

If any case fails, the CLI exits with code 1. You can publish the contents of `reports/` (or the latest `report_*.html`) as an artifact so the team can open the report after each run. Use `--quiet` in CI if you want minimal log output.

### 7.4 Optional AI failure summaries (parser agent)

The **parser_agent** module is an **optional**, **informational** helper: it **parses a capture log** for test failures (`[parser_agent/detect.py](../parser_agent/detect.py)`), and when failures are found, calls **Amazon Bedrock** to produce a short Markdown interpretation (`[parser_agent/summarize.py](../parser_agent/summarize.py)`). It **does not** change pytest, CLI, or shell exit codes (the CLI entry point always exits 0 so local runs and CI are not blocked by Bedrock errors).

**Output:** timestamped files under `reports/agent-summaries/summary_<timestamp>.md` (see `[parser_agent/report.py](../parser_agent/report.py)`).

**When it runs automatically:** only if `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_REGION` are all set and **boto3** is installed. The convenience drivers source `scripts/parser_agent_hook.sh` and invoke `python3 parser_agent/main.py <logfile>` after the relevant stage; timing per script is described in [§5.8](#58-convenience-shell-scripts). If the required variables are not set, the call to Bedrock is skipped.

**Manual run** (from repo root, after a failing run produced a log):

```bash
python3 parser_agent/main.py logs/manual_2026-03-25T00-00-00.log
```

**Optional:** override the Bedrock model with `**BEDROCK_MODEL_ID`** (default in `[parser_agent/config.py](../parser_agent/config.py)`). `**AWS_DEFAULT_REGION`** is read as the region when setting up the client.

---

## 8. Glossary

- **API** – Application Programming Interface; here, the HTTP API of the STS server.
- **Base URL** – The root URL of the STS v2 API including `/v2` (default in tests: `https://sts-qa.cancer.gov/v2`; prod example: `https://sts.cancer.gov/v2`). All request paths are appended to this.
- **Discovery** – The one-time process of calling the API to get real IDs and values (model handle, node handle, tag key/value, etc.) used to build test requests.
- **Endpoint** – One path + method combination (e.g. GET `/v2/models/`).
- **Fixture** – In pytest, a reusable piece of setup (e.g. `api_client`, `test_data`) provided to test functions by name.
- **Generator** – The code that turns the OpenAPI spec plus discovery data into a list of **test cases** (path, params, expected status, etc.).
- **Negative test** – A test that sends invalid or missing input and expects an error response (404 or 422).
- **OpenAPI** – A standard format (YAML/JSON) for describing REST APIs (paths, parameters, responses, schemas).
- **Operation** – One HTTP method on one path in the spec (e.g. GET `/v2/id/{id}`).
- **Path parameter** – A part of the URL that varies (e.g. `{id}` in `/v2/id/{id}`). Values come from discovery or are faked for negative tests.
- **Positive test** – A test that sends valid input and expects success (200).
- **Query parameter** – Key-value in the URL after `?` (e.g. `skip=0`, `limit=10`).
- **Schema** – In OpenAPI, the description of a response body (e.g. “object with fields nanoid, handle, version”). Used for contract validation.
- **Spec** – The OpenAPI specification file (`spec/v2.json`); the “contract” of the API.
- **Tag** – In OpenAPI, a label on an operation (e.g. `id`, `model`, `models`). Used to group endpoints and to filter which tests to run (`--tags`).
- **test_data** – The dictionary produced by discovery (model_handle, node_handle, etc.) used to fill path and query parameters when generating cases.

---

## 9. Troubleshooting and FAQ

**Web UI / launcher**

- **Port in use:** `launcher.py` tries **5678**, then **5679**, etc., until a port is free. Open the URL printed in the terminal.
- **Flask not found:** Run `pip install -r requirements.txt` in your venv (`flask` is listed there).
- **`KeyError: 'WERKZEUG_SERVER_FD'`:** The launcher must **not** set `WERKZEUG_RUN_MAIN` on the Flask subprocess (see [§4.3](#43-web-test-runner-ui-how-it-is-built)). If you changed `launcher.py`, remove that env var.
- **Windows: `bash` not found** when running **Full**, **Manual**, or **Term verify** from the UI: install **Git Bash** and ensure `bash` is on `PATH`, or run those suites from a Git Bash terminal using the shell scripts; use **Autogenerated** from the UI without `bash`.

**No test cases generated**

- Discovery may have failed (e.g. no models, or network error). Check that `STS_BASE_URL` is correct and the server is reachable. Run with pytest or CLI and look for errors during discovery; add print/logging in `discover.py` if needed.
- If you use `--tags`, ensure at least one operation has that tag in the spec.

**Tests pass locally but fail in CI**

- CI may use a different base URL or environment with different or no data. Set `STS_BASE_URL` (and optionally `STS_SSL_VERIFY`) in CI. If the CI environment has no data, discovery will return an empty dict and many positive cases will not be generated.

**Root test expects 200 but gets 404**

- The root path `/` may not be implemented on the server you’re hitting. The spec says it returns 200; if the server doesn’t, either fix the server or relax the test (e.g. accept 200 or 404) if that’s acceptable for your use.

**Negative tests fail (e.g. expected 422, got 200)**

- Some APIs return 200 with an empty or default result instead of 422 for invalid params. You can adjust the generator to not add a negative case for that operation, or change the expected status if the API behavior is documented that way.

**How do I add a new endpoint that’s in the spec?**

- If it’s a GET with path parameters, ensure discovery provides the needed values (add them in `discover.py`) and that `_resolve_path_params()` in `generator.py` maps those param names to `test_data` keys. No new test file is required; the generator will pick up the new path from the spec.

**Where do I document our team’s conventions?**

- Use this ONBOARDING.md for how the framework works and how to maintain it. Use the README for quick start (web UI first, then CLI), install, and high-level purpose.

---

For quick reference and install/run commands, see the [README](../README.md). This guide is the single place for full onboarding, design context, and maintenance guidance.