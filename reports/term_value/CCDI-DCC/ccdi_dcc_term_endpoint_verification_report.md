# CCDI-DCC term endpoint verification report

**Base URL:** `https://sts-qa.cancer.gov/v2`

**Endpoint:** `GET {base}/model/{modelHandle}/version/{versionString}/node/{nodeHandle}/property/{propHandle}/term/{termValue}`

**Input:** `ccdi_dcc_enum_terms_for_verification_enriched.csv`

**Rows skipped (neither `term_value` nor `enum_value` usable):** 0

**URL term:** `(term_value or '') or (enum_value or '')` must be non-empty after strip (legacy). Prefer API `term_value` from `/terms` when enrich resolved the handle.

**Rows verified (HTTP):** 3954

**Passed:** 3942

**Failed:** 12

**Exit code (without `--warn-only`):** process exits **1** only if there is at least one failed row **not** listed under [Known missing in STS DB](#known-missing-in-sts-db) below. Per-row `passed` in the CSV is unchanged.

**Failed rows matching known-missing allowlist (exit ignored):** 11

**Failed rows not allowlisted (would fail the run):** 1

## Known missing in STS DB

These `(prop_handle, enum_value)` pairs are in the model enum but confirmed absent from the STS DB; they remain `passed=False` in the CSV for visibility.

| prop_handle | enum_value |
|-------------|------------|
| diagnosis | Chondroma, NOS |
| file_type | cnn |
| file_type | cnr |
| file_type | mzid |
| file_type | parquet |
| file_type | psm |
| file_type | selfsm |
| file_type | sf |
| library_source_molecule | Not Applicable |
| library_strategy | CITE-Seq |
| submitted_diagnosis | Chondroma, NOS |

## Failed rows (first 50)

| prop_handle | enum_value (handle) | term_value | http_status | notes |
|-------------|---------------------|------------|-------------|-------|
| file_type | cnn |  | 404 | non-200 |
| file_type | cnr |  | 404 | non-200 |
| file_type | mzid |  | 404 | non-200 |
| file_type | mzml |  | 404 | non-200 |
| file_type | parquet |  | 404 | non-200 |
| file_type | psm |  | 404 | non-200 |
| file_type | sf |  | 404 | non-200 |
| file_type | selfsm |  | 404 | non-200 |
| library_strategy | CITE-Seq |  | 404 | non-200 |
| library_source_molecule | Not Applicable |  | 404 | non-200 |
| diagnosis | Chondroma, NOS |  | 404 | non-200 |
| submitted_diagnosis | Chondroma, NOS |  | 404 | non-200 |

**Full results:** `ccdi_dcc_term_endpoint_verification_report.csv`
