# cards

## 1. Muc dich bang

Luu thong tin the de xu ly khoa/mo khoa/bao mat va xem thong tin the.

**Nhom:** Master/reference data

## 2. Ngu canh nghiep vu

- Bang nay phuc vu luong xu ly cua cac agent trong he thong TrustFlow.
- Du lieu duoc dung de truy van read model, xac thuc thong tin va truy vet audit.
- Day la mock data cho demo, khong phai core ledger van hanh that.

## 3. Columns

| Column | Type | Meaning | Example Values From Data | Nullable | Key / Relationship | Notes |
|---|---|---|---|---|---|---|
| card_id | UUID string | Dinh danh ban ghi | 5943f137-22d2-5650-b80e-98c1cfb2031c, aef534b2-eb28-5b1e-b26a-d25cc412c438, 988b3f7b-ff84-50b8-ba7e-08520072e350 | No | PK | - |
| cif_no | string | Ma/so nghiep vu | CIF000013, CIF000013, CIF000067 | No | FK -> customers.cif_no | - |
| account_no | numeric | Ma/so nghiep vu | 8299229959, 8299229959, 9010016761 | No | FK -> accounts.account_no | - |
| masked_card_no | string | Ma/so nghiep vu | **** **** **** 7187, **** **** **** 7168, **** **** **** 5303 | No | - | - |
| card_type | enum string | Truong du lieu nghiep vu | CREDIT, DEBIT, CREDIT | No | - | - |
| card_network | enum string | Truong du lieu nghiep vu | VISA, MASTERCARD, VISA | No | - | - |
| credit_limit | numeric | Gia tri tai chinh | 121406577, 180706923, 141890899 | Yes | - | - |
| available_limit | numeric | Truong du lieu nghiep vu | 74652964, 171433839, 56817641 | Yes | - | - |
| status | enum string | Trang thai/muc do theo workflow | ACTIVE, ACTIVE, ACTIVE | No | - | Gia tri phai khop enum cua workflow hien tai |
| issued_at | timestamp string | Moc thoi gian | 2023-08-01 08:14:22, 2025-10-28 08:10:19, 2023-09-15 23:54:18 | No | - | - |

## 4. Important Values / Enums

| Column | Value | Meaning | Example Use Case |
|---|---|---|---|
| card_type | CREDIT | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| card_type | DEBIT | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| card_network | MASTERCARD | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| card_network | NAPAS | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| card_network | VISA | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| status | ACTIVE | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| status | EXPIRED | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| status | LOST | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| status | TEMP_LOCKED | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |

## 5. Relationships

- cards.cif_no -> customers.cif_no
- cards.account_no -> accounts.account_no

## 6. Simple Usage Examples

```sql
SELECT * FROM cards LIMIT 5;
SELECT * FROM cards WHERE cif_no = 'CIF000001' LIMIT 10;
```
