# customers

## 1. Muc dich bang

Luu thong tin khach hang theo CIF de scope du lieu cho cac agent.

**Nhom:** Master/reference data

## 2. Ngu canh nghiep vu

- Bang nay phuc vu luong xu ly cua cac agent trong he thong TrustFlow.
- Du lieu duoc dung de truy van read model, xac thuc thong tin va truy vet audit.
- Day la mock data cho demo, khong phai core ledger van hanh that.

## 3. Columns

| Column | Type | Meaning | Example Values From Data | Nullable | Key / Relationship | Notes |
|---|---|---|---|---|---|---|
| customer_id | UUID string | Dinh danh ban ghi | 7650a268-4eb3-51ea-ab03-4f6c2ff80501, d4d57dd1-7371-56f6-8d63-85a901ae446b, 305bb4b9-0eda-5bf8-bdb5-680d8b561552 | No | PK | - |
| cif_no | string | Ma/so nghiep vu | CIF000001, CIF000002, CIF000003 | No | Unique | - |
| full_name | string | Truong du lieu nghiep vu | Tran Van Lan, Do Huu An, Pham Thanh Dung | No | - | - |
| phone_number | numeric | Truong du lieu nghiep vu | 0733218196, 0386379402, 0961559407 | No | - | - |
| email | string | Truong du lieu nghiep vu | tran.van.lan@example.com, do.huu.an@example.com, pham.thanh.dung@example.com | No | - | - |
| kyc_level | enum string | Truong du lieu nghiep vu | BASIC, VERIFIED, VERIFIED | No | - | - |
| status | enum string | Trang thai/muc do theo workflow | ACTIVE, ACTIVE, CLOSED | No | - | Gia tri phai khop enum cua workflow hien tai |
| created_at | timestamp string | Moc thoi gian | 2023-12-28 10:13:36, 2023-08-30 12:41:45, 2024-08-11 00:47:04 | No | - | - |

## 4. Important Values / Enums

| Column | Value | Meaning | Example Use Case |
|---|---|---|---|
| kyc_level | BASIC | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| kyc_level | ENHANCED | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| kyc_level | VERIFIED | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| status | ACTIVE | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| status | CLOSED | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| status | SUSPENDED | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |

## 5. Relationships

- Khong co quan he FK truc tiep.

## 6. Simple Usage Examples

```sql
SELECT * FROM customers LIMIT 5;
SELECT * FROM customers WHERE cif_no = 'CIF000001' LIMIT 10;
```
