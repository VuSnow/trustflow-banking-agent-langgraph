# transaction_categories

## 1. Muc dich bang

Danh muc phan loai giao dich cho phan tich va category confirmation.

**Nhom:** Master/reference data

## 2. Ngu canh nghiep vu

- Bang nay phuc vu luong xu ly cua cac agent trong he thong TrustFlow.
- Du lieu duoc dung de truy van read model, xac thuc thong tin va truy vet audit.
- Day la mock data cho demo, khong phai core ledger van hanh that.

## 3. Columns

| Column | Type | Meaning | Example Values From Data | Nullable | Key / Relationship | Notes |
|---|---|---|---|---|---|---|
| category_id | UUID string | Dinh danh ban ghi | fa45defc-de8f-5173-8b0a-366b8533fd0e, 82fa388e-becc-53b4-9980-e141ca144df8, acc0d9f0-977e-5858-9981-7c22f26df124 | No | - | - |
| category_code | string | Ma tham chieu nghiep vu | FOOD, SHOPPING, TRANSPORT | No | - | - |
| category_name | string | Truong du lieu nghiep vu | An uong, Mua sam, Di chuyen | No | - | - |
| category_group | enum string | Truong du lieu nghiep vu | SPENDING, SPENDING, SPENDING | No | - | - |

## 4. Important Values / Enums

| Column | Value | Meaning | Example Use Case |
|---|---|---|---|
| category_group | BILL | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| category_group | CASH | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| category_group | FEE | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| category_group | INCOME | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| category_group | OTHER | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| category_group | SPENDING | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| category_group | TRANSFER | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |

## 5. Relationships

- Khong co quan he FK truc tiep.

## 6. Simple Usage Examples

```sql
SELECT * FROM transaction_categories LIMIT 5;
```
