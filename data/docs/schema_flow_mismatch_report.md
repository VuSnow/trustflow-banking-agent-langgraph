# Schema vs Flow Mismatch Report

## Scope

Comparison baseline:
- Live database: `banking_mcp_test` (queried before applying regenerated SQL)
- Flow code: current backend agents/tools/router logic

Result: several runtime mismatches still exist in the live DB and can break agent flows.

## Findings

### Critical-1: `accounts` missing `is_primary` and `nickname`
- Flow code expectation:
  - `backend/tools/account_tools.py` selects `is_primary`, `nickname` and sorts by `is_primary`.
- Live DB reality:
  - `accounts` columns only include: `account_id, account_no, cif_no, account_type, currency, balance, available_balance, status, opened_at`.
- Impact:
  - `get_user_accounts` and `get_account_detail` can fail with `column does not exist`, breaking ACCOUNT_OPERATION flows.

### Critical-2: missing table `account_products`
- Flow code expectation:
  - `backend/tools/account_tools.py` queries `FROM account_products WHERE is_active = true`.
- Live DB reality:
  - table `account_products` not present.
- Impact:
  - OPEN_ACCOUNT flow cannot list products and draft creation is blocked.

### Critical-3: missing table `card_controls`
- Flow code expectation:
  - `backend/tools/card_tools.py` performs `LEFT JOIN card_controls cc ON c.card_id = cc.card_id`.
- Live DB reality:
  - table `card_controls` not present.
- Impact:
  - Card detail retrieval fails (CARD_OPERATION degraded/broken).

### High-1: card status enum mismatch (`LOCKED` vs `TEMP_LOCKED`/`LOST`)
- Flow code expectation:
  - lock sets `TEMP_LOCKED`, unlock requires `TEMP_LOCKED`, lost sets `LOST`.
- Live DB reality:
  - distinct statuses found: `ACTIVE, EXPIRED, LOCKED`.
- Impact:
  - lock/unlock/report-lost workflow may become inconsistent or blocked by unexpected statuses.

### High-2: `transactions.note` expected by resolver but absent in live DB
- Flow code expectation:
  - `backend/services/recipient_resolver.py` selects `amount, note` from transactions for "past transaction copy fields".
- Live DB reality:
  - `transactions` has `description` but no `note`.
- Impact:
  - note-copy behavior for "transfer to previous recipient" can fail and degrade UX.

## Alignment Status of Regenerated SQL

The regenerated schema in `data/sql/01_schema.sql` now includes:
- `accounts.is_primary`, `accounts.nickname`, `accounts.closed_at`
- `account_products`, `card_controls`, `card_limits`, `card_operation_requests`
- `transactions.note` (alongside `description`)
- card status set that supports `TEMP_LOCKED` and `LOST`

So, mismatch is primarily between **current live DB** and **current flow code**. Applying `data/sql/all_in_one.sql` will align schema with the implemented flow.

## Recommended Next Action

1. Apply regenerated schema+data:
   - `psql "postgresql://dungvu:dungvu@localhost:5432/banking_mcp_test" -f data/sql/all_in_one.sql`
2. Re-run smoke tests for ACCOUNT_OPERATION and CARD_OPERATION first.
3. Validate transaction "past recipient copy note" flow after migration.
