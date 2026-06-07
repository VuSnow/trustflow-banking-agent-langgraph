# interest_rates

## 1. Muc dich bang

Bang tham chieu lai suat tiet kiem/vay de tu van tai chinh.

**Nhom:** Master/reference data

## 2. Ngu canh nghiep vu

- Bang nay phuc vu luong xu ly cua cac agent trong he thong TrustFlow.
- Du lieu duoc dung de truy van read model, xac thuc thong tin va truy vet audit.
- Day la mock data cho demo, khong phai core ledger van hanh that.

## 3. Columns

| Column | Type | Meaning | Example Values From Data | Nullable | Key / Relationship | Notes |
|---|---|---|---|---|---|---|
| id | UUID string | Truong du lieu nghiep vu | 5c292c0b-f70c-5d1a-94d0-19e5723107ad, ec800139-6fb2-531d-8929-9c4cf5d30709, 0c902f7f-81fe-5d94-8178-fcf34d2a9eab | No | - | - |
| product_code | string | Ma tham chieu nghiep vu | DEMAND_VND, SAVINGS_ONLINE_1M, SAVINGS_ONLINE_3M | No | - | - |
| product_type | enum string | Truong du lieu nghiep vu | SAVINGS, SAVINGS, SAVINGS | No | - | - |
| product_name | string | Truong du lieu nghiep vu | Tien gui khong ky han, Tiet kiem online 1 thang, Tiet kiem online 3 thang | No | - | - |
| currency | enum string | Truong du lieu nghiep vu | VND, VND, VND | No | - | - |
| term_months | numeric | Truong du lieu nghiep vu | 1, 3, 6 | Yes | - | - |
| annual_rate | numeric | Gia tri tai chinh | 0.1, 2.9, 3.4 | No | - | - |
| min_amount | numeric | Truong du lieu nghiep vu | 0, 1000000, 1000000 | No | - | - |
| max_amount | string | Truong du lieu nghiep vu | - | Yes | - | - |
| customer_segment | enum string | Truong du lieu nghiep vu | ALL, ALL, ALL | No | - | - |
| channel | enum string | Truong du lieu nghiep vu | ALL, ONLINE, ONLINE | No | - | - |
| effective_from | date string | Truong du lieu nghiep vu | 2026-01-01, 2026-01-01, 2026-01-01 | No | - | - |
| effective_to | string | Truong du lieu nghiep vu | - | Yes | - | - |
| status | enum string | Trang thai/muc do theo workflow | ACTIVE, ACTIVE, ACTIVE | No | - | Gia tri phai khop enum cua workflow hien tai |
| created_at | timestamp string | Moc thoi gian | 2026-01-01 00:00:00, 2026-01-01 00:00:00, 2026-01-01 00:00:00 | No | - | - |

## 4. Important Values / Enums

| Column | Value | Meaning | Example Use Case |
|---|---|---|---|
| product_type | LOAN | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| product_type | SAVINGS | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| channel | ALL | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| channel | COUNTER | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| channel | ONLINE | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |

## 5. Relationships

- Khong co quan he FK truc tiep.

## 6. Simple Usage Examples

```sql
SELECT * FROM interest_rates LIMIT 5;
```
