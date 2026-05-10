# Example ODCS v3.1.0 Contracts

Reference contracts that exercise the full breadth of the Open Data Contract Standard v3.1.0.
Each file is valid ODCS and can be passed directly to `datacontract-faker`.

```bash
datacontract-faker generate --contract examples/ecommerce_orders.yaml      --rows 500 --format parquet --output out/ecommerce.parquet
datacontract-faker generate --contract examples/financial_transactions.yaml --rows 200 --format json    --output out/financial.json
```

---

## `ecommerce_orders.yaml` — E-Commerce Orders Platform

**Domain:** Retail / Commerce

| Feature | Where |
|---|---|
| All 9 `logicalType` values | `orders` and `customers` models |
| All string `format` values (email, uuid, uri, hostname, ipv4, byte) | `order_id`, `customer_email`, `referrer_url`, `client_hostname`, `ip_address`, `device_fingerprint` |
| Nested `object` field | `shipping_address`, `payment_method`, `primary_address` |
| `array` of objects | `line_items` (with full sub-schema), `consent_records` |
| `array` of scalars | `tags` (string items, no `name`) |
| `minimum` / `maximum` on number | `subtotal_amount`, `total_amount`, `discount_percent` |
| `minimum` / `maximum` on date | `customers.date_of_birth` (age-gate: max `2008-01-01`) |
| `minimum` / `maximum` on timestamp | `orders.delivered_at` |
| `minLength` / `maxLength` / `pattern` | `currency` (ISO 4217), `phone_number` (E.164), `locale` (BCP 47), `country_code`, `sku` |
| `examples` as closed vocabulary | `status`, `tier`, `channel`, `payment_method.type` |
| `integer format` i32, i64 | `item_count`, `lifetime_order_count` |
| `number format` f64 | `subtotal_amount`, `total_amount`, `lifetime_spend` |
| `primaryKey`, `unique`, `required` | `order_id`, `customer_id`, `email` |
| `criticalDataElement` | `order_id`, `total_amount`, `created_at`, `email` |
| `classification` (public / restricted / confidential) | Throughout both models |
| `encryptedName` | `email`, `phone_number`, `date_of_birth`, `payment_method.token` |
| `partitioned` + `partitionKeyPosition` | `orders.created_at` |
| `transformSourceObjects` + `transformLogic` | `total_amount` |
| Quality — `library` type | `nullValues mustBe: 0`, `duplicateValues mustBe: 0`, `rowCount mustBeGreaterThan: 0` |
| Quality — `sql` type | `total_amount_additive_consistency`, `refunded_ratio_sanity` (uses `mustNotBeBetween`) |
| Quality — `custom` (great-expectations) | `email_format_check` |
| Quality — `text` type | `freshness_expectation` |
| All 7 quality `dimension` values | accuracy, completeness, conformity, consistency, coverage, timeliness, uniqueness |
| `businessImpact: operational` | Multiple rules on `orders` |
| `schedule` / `scheduler` | `orders_must_exist` (cron) |
| Schema-level `relationships` (FK) | `orders.customer_id → customers.customer_id` |
| Property-level `relationships` (FK) | `orders.customer_id` |
| `servers` (snowflake + postgresql) | Top-level |
| `team`, `roles`, `slaProperties` | Top-level |
| `authoritativeDefinitions`, `customProperties` | Top-level and per-model |
| `description` object (purpose/limitations/usage) | Top-level |

---

## `financial_transactions.yaml` — Financial Transactions Ledger

**Domain:** Banking / Fintech / Compliance

| Feature | Where |
|---|---|
| 3 schema objects with cross-model FKs | `accounts`, `transactions`, `journal_entries` |
| `integer format` i64, u64 | `balance_cents` (signed), `amount_cents` (unsigned) |
| `number format` f64 | `exchange_rate`, `risk_assessment.risk_score` |
| `minimum` / `maximum` on date with bounds | `booking_date`, `effective_date`, `opened_at` |
| `minimum` on timestamp | `created_at` (`2010-01-01T00:00:00Z`), `audit_trail.occurred_at` |
| `minimum` on integer | `amount_cents` (must be ≥ 1 — no zero transactions) |
| `minimum` / `maximum` on number | `exchange_rate`, `risk_score` (0.00–100.00) |
| Nested `object` | `counterparty` (with tokenised IBAN), `risk_assessment` |
| `array` of objects | `audit_trail` (ordered status-change events) |
| `array` of scalars with `examples` | `risk_assessment.flags` (AML codes) |
| `pattern` for financial identifiers | `bic_swift` (ISO 9362), `gl_account_code`, `model_version` |
| `encryptedName` (PCI-DSS vault tokens) | `account_number_token`, `iban_token`, `counterparty.name_token`, `counterparty.iban_token` |
| `classification: confidential` throughout | `balance_cents`, `iban_token`, `counterparty` |
| `criticalDataElement` on financial fields | `balance_cents`, `amount_cents`, `booking_date` |
| `partitioned` | `transactions.booking_date`, `journal_entries.effective_date` |
| Quality — all 8 operators | `mustBe`, `mustNotBe`, `mustBeGreaterThan`, `mustBeGreaterOrEqualTo`, `mustBeLessThan`, `mustBeLessOrEqualTo`, `mustBeBetween`, `mustNotBeBetween` |
| Quality — `library` metrics | nullValues, missingValues, invalidValues, duplicateValues, rowCount |
| Quality — `sql` (complex analytical) | Balance consistency, AML CTR threshold check, journal balance check, even-entry count |
| Quality — `custom` (soda) | `account_fk_integrity` (referential integrity check) |
| `businessImpact: regulatory` | Throughout — PSD2, AMLD6, SOX compliance |
| Multi-FK schema-level relationships | `journal_entries` → `transactions` AND `accounts` |
| `authoritativeDefinitions` with regulatory URL | EBA PSD2 regulation link (`type: tutorial`) |
| `customProperties` for compliance metadata | `regulatoryFramework`, `pciDssScope`, `dpoContact` |
| `slaProperties` with 100% completeness | Regulatory zero-loss requirement |

---

## ODCS v3.1.0 Feature Coverage

| Spec feature | Covered in |
|---|---|
| All 9 `logicalType` values | ecommerce |
| All `string.format` values | ecommerce |
| `integer.format` (i32, i64, u64) | both |
| `number.format` (f64) | both |
| `minLength`, `maxLength` | both |
| `pattern` | both |
| `minimum`, `maximum` (number/integer) | both |
| `minimum`, `maximum` (date, timestamp) | both |
| `minItems`, `maxItems`, `uniqueItems` | ecommerce |
| Nested `object` with `properties` | both |
| `array` of objects (no `name` on `items`) | both |
| `array` of scalars | both |
| `examples` as pick-list | both |
| `primaryKey`, `primaryKeyPosition` | both |
| `unique`, `required` | both |
| `partitioned`, `partitionKeyPosition` | both |
| `criticalDataElement` | both |
| `classification` (public/restricted/confidential) | both |
| `encryptedName` | both |
| `transformSourceObjects`, `transformLogic` | ecommerce |
| Property-level `relationships` | both |
| Schema-level `relationships` | both |
| Multi-FK schema-level relationships | financial |
| Quality `type: library` | both |
| Quality `type: sql` | both |
| Quality `type: custom` (soda, great-expectations) | both |
| Quality `type: text` | ecommerce |
| All 7 `dimension` values | ecommerce |
| All 8 operator variants | financial |
| `businessImpact` (operational, regulatory) | both |
| `schedule` / `scheduler` | ecommerce |
| `description` object (purpose/limitations/usage) | both |
| `servers` (multiple types) | both |
| `team` with `members` | both |
| `roles` with approvers | both |
| `slaProperties` | both |
| `authoritativeDefinitions` | both |
| `customProperties` | both |
| `tags` at contract and model level | both |
| `contractCreatedTs` | both |
