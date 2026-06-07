# merchants

## 1. Muc dich bang

Danh muc merchant cho giao dich the va phan tich chi tieu.

**Nhom:** Master/reference data

## 2. Ngu canh nghiep vu

- Bang nay phuc vu luong xu ly cua cac agent trong he thong TrustFlow.
- Du lieu duoc dung de truy van read model, xac thuc thong tin va truy vet audit.
- Day la mock data cho demo, khong phai core ledger van hanh that.

## 3. Columns

| Column | Type | Meaning | Example Values From Data | Nullable | Key / Relationship | Notes |
|---|---|---|---|---|---|---|
| merchant_id | UUID string | Dinh danh ban ghi | a7ebff1a-de7e-5a29-9580-65e0a6129d5c, 32e826b7-fef8-5745-8d32-fedd1ab1712a, ba1e4498-b0df-598f-9a86-f5db51c8c749 | No | PK | - |
| merchant_name | string | Truong du lieu nghiep vu | Lotte Mart, Sendo, Baemin | No | - | - |
| merchant_category | enum string | Truong du lieu nghiep vu | SHOPPING, ECOMMERCE, FOOD | No | - | - |
| mcc_code | numeric | Ma tham chieu nghiep vu | 5691, 5399, 5812 | No | - | - |
| city | string | Truong du lieu nghiep vu | Hai Phong, Ho Chi Minh, Can Tho | No | - | - |
| country | enum string | Truong du lieu nghiep vu | VN, VN, VN | No | - | - |
| status | enum string | Trang thai/muc do theo workflow | ACTIVE, ACTIVE, ACTIVE | No | - | Gia tri phai khop enum cua workflow hien tai |

## 4. Important Values / Enums

| Column | Value | Meaning | Example Use Case |
|---|---|---|---|
| merchant_category | DIGITAL_WALLET | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| merchant_category | ECOMMERCE | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| merchant_category | ELECTRONICS | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| merchant_category | ENTERTAINMENT | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| merchant_category | FOOD | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| merchant_category | GROCERY | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| merchant_category | SHOPPING | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| merchant_category | TRANSPORT | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| status | ACTIVE | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| status | INACTIVE | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |

## 5. Relationships

- Khong co quan he FK truc tiep.

## 6. Simple Usage Examples

```sql
SELECT * FROM merchants LIMIT 5;
```
