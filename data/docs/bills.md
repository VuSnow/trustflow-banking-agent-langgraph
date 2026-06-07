# bills

## 1. Muc dich bang

Luu hoa don theo ky va trang thai thanh toan cho luong bill payment.

**Nhom:** Billing workflow

## 2. Ngu canh nghiep vu

- Bang nay phuc vu luong xu ly cua cac agent trong he thong TrustFlow.
- Du lieu duoc dung de truy van read model, xac thuc thong tin va truy vet audit.
- Day la mock data cho demo, khong phai core ledger van hanh that.

## 3. Columns

| Column | Type | Meaning | Example Values From Data | Nullable | Key / Relationship | Notes |
|---|---|---|---|---|---|---|
| bill_id | UUID string | Dinh danh ban ghi | 6938d349-0afc-58b5-a748-b39ec6123cf9, 5bf62ed5-d929-58dd-930b-436bcc01e88d, 4107eeaa-8710-5048-ab94-8a746882d9de | No | PK | - |
| biller_code | string | Ma tham chieu nghiep vu | EVN_DANANG, EVN_DANANG, EVN_SOUTH | No | FK -> billers.biller_code | - |
| customer_bill_code | string | Ma tham chieu nghiep vu | PD915929556, PD915929556, PD778476227 | No | FK -> customer_biller_accounts.customer_bill_code | - |
| bill_period | enum string | Truong du lieu nghiep vu | 2026-06, 2026-05, 2026-06 | No | - | - |
| amount_due | numeric | Gia tri tai chinh | 2364471, 1291137, 1491947 | No | - | - |
| due_date | date string | Truong du lieu nghiep vu | 2026-06-10, 2026-05-10, 2026-06-10 | No | - | - |
| status | enum string | Trang thai/muc do theo workflow | UNPAID, PAID, UNPAID | No | - | Gia tri phai khop enum cua workflow hien tai |
| created_at | timestamp string | Moc thoi gian | 2026-05-30 09:00:00, 2026-04-27 09:00:00, 2026-06-03 09:00:00 | No | - | - |
| paid_at | timestamp string | Moc thoi gian | 2026-05-09 23:00:00, 2026-05-07 04:00:00, 2026-04-05 18:00:00 | Yes | - | - |

## 4. Important Values / Enums

| Column | Value | Meaning | Example Use Case |
|---|---|---|---|
| status | PAID | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| status | UNPAID | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |

## 5. Relationships

- bills.biller_code -> billers.biller_code
- bills.customer_bill_code -> customer_biller_accounts.customer_bill_code

## 6. Simple Usage Examples

```sql
SELECT * FROM bills LIMIT 5;
```
