# billers

## 1. Muc dich bang

Danh muc nha cung cap hoa don (dien, nuoc, internet, phone).

**Nhom:** Master/reference data

## 2. Ngu canh nghiep vu

- Bang nay phuc vu luong xu ly cua cac agent trong he thong TrustFlow.
- Du lieu duoc dung de truy van read model, xac thuc thong tin va truy vet audit.
- Day la mock data cho demo, khong phai core ledger van hanh that.

## 3. Columns

| Column | Type | Meaning | Example Values From Data | Nullable | Key / Relationship | Notes |
|---|---|---|---|---|---|---|
| biller_id | UUID string | Dinh danh ban ghi | 561cbccd-d404-5833-a5e8-ba6158e9d5a7, 91bab014-7091-5a41-b9a5-7fb9f2fedcc2, da19a037-7425-578c-b215-9721338a9344 | No | PK | - |
| biller_code | string | Ma tham chieu nghiep vu | EVN_HANOI, EVN_HCMC, EVN_DANANG | No | Unique | - |
| biller_name | string | Truong du lieu nghiep vu | EVN Ha Noi, EVN Ho Chi Minh, EVN Da Nang | No | - | - |
| biller_type | enum string | Truong du lieu nghiep vu | ELECTRICITY, ELECTRICITY, ELECTRICITY | No | - | - |
| provider | enum string | Truong du lieu nghiep vu | EVN, EVN, EVN | No | - | - |
| status | enum string | Trang thai/muc do theo workflow | ACTIVE, ACTIVE, ACTIVE | No | - | Gia tri phai khop enum cua workflow hien tai |

## 4. Important Values / Enums

| Column | Value | Meaning | Example Use Case |
|---|---|---|---|
| biller_type | ELECTRICITY | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| biller_type | INTERNET | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| biller_type | PHONE_POSTPAID | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| biller_type | WATER | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |

## 5. Relationships

- Khong co quan he FK truc tiep.

## 6. Simple Usage Examples

```sql
SELECT * FROM billers LIMIT 5;
```
