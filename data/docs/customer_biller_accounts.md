# customer_biller_accounts

## 1. Muc dich bang

Lien ket khach hang voi ma khach hang tai biller de truy xuat hoa don.

**Nhom:** Master/reference data

## 2. Ngu canh nghiep vu

- Bang nay phuc vu luong xu ly cua cac agent trong he thong TrustFlow.
- Du lieu duoc dung de truy van read model, xac thuc thong tin va truy vet audit.
- Day la mock data cho demo, khong phai core ledger van hanh that.

## 3. Columns

| Column | Type | Meaning | Example Values From Data | Nullable | Key / Relationship | Notes |
|---|---|---|---|---|---|---|
| customer_biller_account_id | UUID string | Dinh danh ban ghi | cc9c6130-5a30-5082-a79c-0d679825f36d, 46f294a4-f281-534b-a29a-38cf19aed95d, e10da766-5b9a-5637-8986-4e0eb4779710 | No | PK | - |
| cif_no | string | Ma/so nghiep vu | CIF000001, CIF000002, CIF000004 | No | FK -> customers.cif_no | - |
| biller_id | UUID string | Dinh danh ban ghi | da19a037-7425-578c-b215-9721338a9344, aa643e7e-8e96-5d5a-be2f-93f48b8eb59f, 561cbccd-d404-5833-a5e8-ba6158e9d5a7 | No | FK -> billers.biller_id | - |
| customer_bill_code | string | Ma tham chieu nghiep vu | PD915929556, PD778476227, PD996981471 | No | - | - |
| alias | string | Truong du lieu nghiep vu | Nha bo me, Nha Ha Noi, Nha bo me | No | - | - |
| status | enum string | Trang thai/muc do theo workflow | ACTIVE, ACTIVE, ACTIVE | No | - | Gia tri phai khop enum cua workflow hien tai |
| last_paid_at | timestamp string | Moc thoi gian | 2026-03-15 02:23:22, 2026-04-25 13:03:31, 2026-02-21 00:45:30 | Yes | - | - |

## 4. Important Values / Enums

| Column | Value | Meaning | Example Use Case |
|---|---|---|---|
| status | ACTIVE | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| status | INACTIVE | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |

## 5. Relationships

- customer_biller_accounts.cif_no -> customers.cif_no
- customer_biller_accounts.biller_id -> billers.biller_id

## 6. Simple Usage Examples

```sql
SELECT * FROM customer_biller_accounts LIMIT 5;
SELECT * FROM customer_biller_accounts WHERE cif_no = 'CIF000001' LIMIT 10;
```
