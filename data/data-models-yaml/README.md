# Data model YAML (vendored)

| File | CLI | Reports |
|------|-----|---------|
| **`ccdi-model-props.yml`** | `sts-ccdi-term-verify` | `reports/term_value/CCDI/` |
| **`c3dc-model-props.yml`** | `sts-c3dc-term-verify` | `reports/term_value/C3DC/` |
| **`ctdc_model_properties_file-2.yaml`** | `sts-ctdc-term-verify` | `reports/term_value/CTDC/` |
| **`icdc-model-props.yml`** | `sts-icdc-term-verify` | `reports/term_value/ICDC/` |
| **`cds-model-props-4.yml`** | `sts-cds-term-verify` | `reports/term_value/CDS/` |
| **`ccdi-dcc-model-props-3.yml`** | `sts-ccdi-dcc-term-verify` | `reports/term_value/CCDI-DCC/` |

- **Source:** CBIIT / model release artifacts (same tree as `mdb/data-models-yaml/` in `termValue_verification_scripts`).

### Architecture

Each `tests/term_verify/*_term_verify.py` script is a thin subclass of `TermVerifyPipeline` (`src/sts_test_framework/term_verify_pipeline.py`). The base class implements the shared extract/enrich/verify stages and CLI; each subclass only defines `parse_yaml()` and any model-specific overrides (e.g. CDS skips handle-to-value enrichment, CCDI-DCC has remote URL expansion and a known-missing allowlist). Shared utilities (`verify_row`, `strip_inline_yaml_comment`, `clean_enum_value`) live in `src/sts_test_framework/term_verify_utils.py`.

### Workflow (YAML-driven pipelines)

Each term-verify script runs **three stages** against a vendored property file:

1. **Extract** — Parse the YAML and list every enumerated value per property (often the term **handle** in STS, not the human-readable label). Write summary + “query” CSVs.

2. **Enrich** — Call the live STS API: discover model version, map each property to a node, and (for most models) page `GET .../property/{propHandle}/terms` to fill **`term_value`** = the API **value** for each YAML handle. Rows also get `model_handle`, `version_string`, `node_handle`.

3. **Verify** — For each row, call:

   `GET /v2/model/{modelHandle}/version/{versionString}/node/{nodeHandle}/property/{propHandle}/term/{termValue}`

   where **`{termValue}`** is URL-encoded. A row **passes** if the response is **200**, the body is a **JSON array**, and **at least one** element has `"value"` equal to the string used in the path (so you are checking that the term endpoint returns the expected term for that path segment).

   Model-specific rules for what goes in `{termValue}`:

   - **CCDI, C3DC, CTDC, ICDC** — Use the enriched **`term_value`** (handle → value from `/terms`). Rows with no resolved `term_value` are skipped for HTTP.
   - **CCDI-DCC** — Same enrich as above; **verify** uses `(term_value or enum_value)` if the legacy sheet would (non-empty after trim). **Extract** may **fetch remote `http(s)` YAML** for some enum entries and merge those values into the list.
   - **CDS** — **Enrich** does **not** call `/terms`; it only fills model/version/node. **`{termValue}`** is the YAML **`enum_value`** directly (legacy `verify_term_endpoint_from_sheet.py`).

### Output CSV artifacts (what each file is)

Artifacts are written under **`reports/term_value/<MODEL>/`** by default (`--out-dir` overrides).  
Each model uses a **filename prefix** tied to that CLI (e.g. `ccdi_`, `c3dc_`, `ctdc_`, `icdc_`, `cds_`, `ccdi_dcc_`). The **stage** is always: **summary + flat query → enriched → verification report**.

| Stage | Typical filename | What it represents |
|-------|------------------|--------------------|
| **Extract** | `{prefix}enum_properties_summary.csv` | **One row per YAML property** that has an `Enum` block: property id, description, how many enum lines, and all enum strings joined (pipe-separated) for a quick inventory. |
| **Extract** | `{prefix}enum_terms_for_verification.csv` | **One row per candidate term**: each `(prop_handle, enum_value)` from the YAML. This is the flat list that enrich and verify iterate. Empty columns are filled in the next stage(s). |
| **Enrich** | `{prefix}enum_terms_for_verification_enriched.csv` | Same rows as the query CSV, after calling STS: **`model_handle`**, **`version_string`**, **`node_handle`**, and (for all models **except CDS**) **`term_value`** = the API **value** for the YAML **handle** from paginated `GET .../property/.../terms`. This is the main input to **Verify**. |
| **Verify** | `{prefix}term_endpoint_verification_report.csv` | **One row per HTTP check** actually performed: which property/term was called, **`http_status`**, boolean **`passed`**, and **`notes`** (failure reason or empty). Rows skipped by the pipeline (e.g. no resolvable URL value) do not appear here. |

A **Markdown** companion **`{prefix}term_endpoint_verification_report.md`** is also written: human-readable summary, counts, and a short preview of failures (full detail stays in the CSV).

**Column reference (shared):**

| Column | Meaning |
|--------|---------|
| `prop_handle` | Property key from the YAML (STS property handle). |
| `description` | Property `Desc:` text from the YAML (where present). |
| `enum_count` | Number of enum entries for that property (summary CSV only). |
| `enum_values` | Pipe-separated list of enum strings for that property (summary CSV only). |
| `enum_value` | Single enum line from the YAML. For CCDI-like models this is usually the **term handle**; for CDS it is already the string used in the term URL. |
| `term_value` | STS Term **value** (display string) looked up from `/terms` via handle→value; empty until enrich **except** CDS (CDS extract/enriched **omit** this column). |
| `model_handle` / `version_string` / `node_handle` | Resolved STS path segments for `GET .../model/.../version/.../node/.../property/...`. |
| `http_status` | HTTP status from the term-by-value `GET`. |
| `passed` | `True` if status is 200, body is a JSON array, and some element has `"value"` matching the checked string. |
| `notes` | Short diagnostic when `passed` is false (e.g. non-200, not an array, no matching `value`). |

**Model-specific report columns:**

- **CCDI, C3DC, CTDC, ICDC** — Report CSV includes `prop_handle`, `enum_value`, `term_value`, `http_status`, `passed`, `notes`. Only rows with a non-empty enriched **`term_value`** are verified.
- **CCDI-DCC** — Same columns as above; the URL may use **`term_value` or `enum_value`** (legacy: first non-empty after trim). Extract may **merge enums from remote `http(s)` YAML** when an enum line is a URL.
- **CDS** — Report CSV has **`prop_handle`, `enum_value`, `http_status`, `passed`, `notes`** only (no `term_value` column); the URL uses **`enum_value`** directly.

For regeneration commands and per-model quirks, see each **`reports/term_value/<MODEL>/README.md`**.

```bash
pip install -e .
sts-ccdi-term-verify --base-url https://sts-qa.cancer.gov/v2
sts-c3dc-term-verify --base-url https://sts-qa.cancer.gov/v2
sts-ctdc-term-verify --base-url https://sts-qa.cancer.gov/v2
sts-icdc-term-verify --base-url https://sts-qa.cancer.gov/v2
sts-cds-term-verify --base-url https://sts-qa.cancer.gov/v2
sts-ccdi-dcc-term-verify --base-url https://sts-qa.cancer.gov/v2
```

Use `--warn-only` if you need exit code 0 while committing reports that still list per-row failures.
