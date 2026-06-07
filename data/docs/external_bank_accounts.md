# external_bank_accounts

## 1. Muc dich bang

Directory tai khoan lien ngan hang de verify nguoi nhan ngoai SHB.

**Nhom:** Master/reference data

## 2. Ngu canh nghiep vu

- Bang nay phuc vu luong xu ly cua cac agent trong he thong TrustFlow.
- Du lieu duoc dung de truy van read model, xac thuc thong tin va truy vet audit.
- Day la mock data cho demo, khong phai core ledger van hanh that.

## 3. Columns

| Column | Type | Meaning | Example Values From Data | Nullable | Key / Relationship | Notes |
|---|---|---|---|---|---|---|
| id | numeric | Truong du lieu nghiep vu | 1, 2, 3 | No | - | - |
| account_no | numeric | Ma/so nghiep vu | 50833678092, 2569374686398, 036073771506 | No | - | - |
| account_holder_name | string | Truong du lieu nghiep vu | Le Hoang Hung, Hoang Van Oanh, Tran Minh Hieu | No | - | - |
| bank_code | enum string | Ma tham chieu nghiep vu | VCB, TCB, BIDV | No | - | - |
| bank_name | string | Truong du lieu nghiep vu | Vietcombank, Techcombank, BIDV | No | - | - |
| id_number | numeric | Truong du lieu nghiep vu | 089653224099, 040816218312, 090101061022 | No | - | - |
| phone | numeric | Truong du lieu nghiep vu | 0355879772, 0737285839, 0964900288 | No | - | - |
| status | enum string | Trang thai/muc do theo workflow | ACTIVE, ACTIVE, ACTIVE | No | - | Gia tri phai khop enum cua workflow hien tai |
| created_at | timestamp string | Moc thoi gian | 2024-04-12 23:55:02, 2021-10-28 08:57:37, 2021-08-16 00:59:20 | No | - | - |

## 4. Important Values / Enums

| Column | Value | Meaning | Example Use Case |
|---|---|---|---|
| bank_code | ACB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| bank_code | BIDV | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| bank_code | CTG | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| bank_code | MB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| bank_code | STB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| bank_code | TCB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| bank_code | TPB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| bank_code | VCB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| bank_code | VIB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| bank_code | VPB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |

## 5. Relationships

- Khong co quan he FK truc tiep.

## 6. Simple Usage Examples

```sql
SELECT * FROM external_bank_accounts LIMIT 5;
```
