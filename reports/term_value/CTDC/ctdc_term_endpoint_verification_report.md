# CTDC term endpoint verification report

**Base URL:** `https://sts-qa.cancer.gov/v2`

**Endpoint:** `GET {base}/model/{modelHandle}/version/{versionString}/node/{nodeHandle}/property/{propHandle}/term/{termValue}`

**Input:** `ctdc_enum_terms_for_verification_enriched.csv`

**Rows skipped (no API `term_value`):** 2 (YAML handle could not be resolved from paginated `/terms`; `/term/{termValue}` requires the Term **value**, not the handle.)

**Rows verified (HTTP):** 438

**Passed:** 438

**Failed:** 0


**Full results:** `ctdc_term_endpoint_verification_report.csv`
