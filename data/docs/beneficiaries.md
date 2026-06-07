# beneficiaries

## 1. Muc dich bang

Luu nguoi nhan da luu cua khach hang de resolve giao dich chuyen tien.

**Nhom:** Master/reference data

## 2. Ngu canh nghiep vu

- Bang nay phuc vu luong xu ly cua cac agent trong he thong TrustFlow.
- Du lieu duoc dung de truy van read model, xac thuc thong tin va truy vet audit.
- Day la mock data cho demo, khong phai core ledger van hanh that.

## 3. Columns

| Column | Type | Meaning | Example Values From Data | Nullable | Key / Relationship | Notes |
|---|---|---|---|---|---|---|
| beneficiary_id | UUID string | Dinh danh ban ghi | 4ac78c04-ea5a-5990-973d-52f58e78f498, 8ce5b028-4d19-5ea3-8316-15b336b9c8fa, d7cf976a-3217-5eda-ab79-823b9d2889fc | No | - | - |
| cif_no | string | Ma/so nghiep vu | CIF000001, CIF000001, CIF000002 | No | FK -> customers.cif_no | - |
| beneficiary_name | string | Truong du lieu nghiep vu | Pham Van Son, Hoang Quoc Vy, Pham Duc Cuong | No | - | - |
| beneficiary_account_no | numeric | Ma/so nghiep vu | 8104091570184, 714224109881, 958702070160 | No | - | - |
| beneficiary_bank_code | enum string | Ma tham chieu nghiep vu | VCB, CTG, TCB | No | - | - |
| beneficiary_bank_name | string | Truong du lieu nghiep vu | Vietcombank, VietinBank, Techcombank | No | - | - |
| nickname | string | Truong du lieu nghiep vu | Thue nha, Ban Hoa, Anh Nam | Yes | - | - |
| is_saved | boolean | Truong du lieu nghiep vu | True, True, False | No | - | Co/khong theo logic nghiep vu |
| last_used_at | timestamp string | Moc thoi gian | 2026-01-08 22:39:23, 2026-04-16 18:31:34, 2026-05-08 18:04:21 | Yes | - | - |
| created_at | timestamp string | Moc thoi gian | 2024-03-26 02:37:18, 2024-08-14 00:59:06, 2025-04-23 13:58:50 | No | - | - |

## 4. Important Values / Enums

| Column | Value | Meaning | Example Use Case |
|---|---|---|---|
| beneficiary_bank_code | ACB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| beneficiary_bank_code | BIDV | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| beneficiary_bank_code | CTG | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| beneficiary_bank_code | MB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| beneficiary_bank_code | STB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| beneficiary_bank_code | TCB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| beneficiary_bank_code | TPB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| beneficiary_bank_code | VCB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| beneficiary_bank_code | VIB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| beneficiary_bank_code | VPB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |

## 5. Relationships

- beneficiaries.cif_no -> customers.cif_no

## 6. Simple Usage Examples

```sql
SELECT * FROM beneficiaries LIMIT 5;
SELECT * FROM beneficiaries WHERE cif_no = 'CIF000001' LIMIT 10;
```
