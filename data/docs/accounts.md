# accounts

## 1. Muc dich bang

Luu tai khoan ngan hang cua khach hang, dung cho xem so du va chon tai khoan nguon.

**Nhom:** Master/reference data

## 2. Ngu canh nghiep vu

- Bang nay phuc vu luong xu ly cua cac agent trong he thong TrustFlow.
- Du lieu duoc dung de truy van read model, xac thuc thong tin va truy vet audit.
- Day la mock data cho demo, khong phai core ledger van hanh that.

## 3. Columns

| Column | Type | Meaning | Example Values From Data | Nullable | Key / Relationship | Notes |
|---|---|---|---|---|---|---|
| account_id | UUID string | Dinh danh ban ghi | 6d253ff0-49a0-528a-be58-111a54d53b11, 71711e0b-a4f2-59f7-ab7d-bea0622956d8, 28c84f3a-fef9-53cd-99c3-dbf18b02705d | No | PK | - |
| account_no | numeric | Ma/so nghiep vu | 31243292127, 527177449058, 9986798079 | No | Unique | - |
| cif_no | string | Ma/so nghiep vu | CIF000001, CIF000001, CIF000002 | No | FK -> customers.cif_no | - |
| account_type | enum string | Truong du lieu nghiep vu | PAYMENT, PAYMENT, PAYMENT | No | - | - |
| currency | enum string | Truong du lieu nghiep vu | VND, VND, VND | No | - | - |
| balance | numeric | Gia tri tai chinh | 249582907, 167148945, 350452571 | No | - | - |
| available_balance | numeric | Gia tri tai chinh | 240389988, 153653568, 307780036 | No | - | - |
| status | enum string | Trang thai/muc do theo workflow | ACTIVE, ACTIVE, ACTIVE | No | - | Gia tri phai khop enum cua workflow hien tai |
| is_primary | boolean | Truong du lieu nghiep vu | True, False, True | No | - | Co/khong theo logic nghiep vu |
| closed_at | timestamp string | Moc thoi gian | 2025-06-07 03:29:04, 2025-04-22 05:53:30 | Yes | - | - |
| nickname | string | Truong du lieu nghiep vu | Du phong, Luong, Tiet kiem | Yes | - | - |
| opened_at | timestamp string | Moc thoi gian | 2025-06-19 04:08:10, 2024-07-26 19:32:02, 2025-07-28 20:15:08 | No | - | - |

## 4. Important Values / Enums

| Column | Value | Meaning | Example Use Case |
|---|---|---|---|
| account_type | PAYMENT | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| account_type | SAVINGS | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| status | ACTIVE | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| status | CLOSED | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| status | FROZEN | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |

## 5. Relationships

- accounts.cif_no -> customers.cif_no

## 6. Simple Usage Examples

```sql
SELECT * FROM accounts LIMIT 5;
SELECT * FROM accounts WHERE cif_no = 'CIF000001' LIMIT 10;
```
