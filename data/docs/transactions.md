# transactions

## 1. Muc dich bang

Lich su giao dich/read model cho text2sql, risk va bao cao.

**Nhom:** Read model / transaction history

## 2. Ngu canh nghiep vu

- Bang nay phuc vu luong xu ly cua cac agent trong he thong TrustFlow.
- Du lieu duoc dung de truy van read model, xac thuc thong tin va truy vet audit.
- Day la mock data cho demo, khong phai core ledger van hanh that.

## 3. Columns

| Column | Type | Meaning | Example Values From Data | Nullable | Key / Relationship | Notes |
|---|---|---|---|---|---|---|
| transaction_id | UUID string | Dinh danh ban ghi | 8bb38dee-3d86-5f6b-8de4-839d68454a4f, 911c836e-2772-5b06-a456-e9397d62d9e1, 614c4811-b9c5-5ec0-93be-fb46eebc10e3 | No | PK | - |
| transaction_ref | string | Truong du lieu nghiep vu | TXN202512000001, TXN202512000002, TXN202512000003 | No | Unique | - |
| cif_no | string | Ma/so nghiep vu | CIF000002, CIF000029, CIF000093 | No | FK -> customers.cif_no | - |
| account_no | numeric | Ma/so nghiep vu | 9986798079, 98454615679, 65564729293 | No | FK -> accounts.account_no | - |
| card_id | UUID string | Dinh danh ban ghi | e83835b8-0bc8-5cb4-8141-5720ef36b264, e83835b8-0bc8-5cb4-8141-5720ef36b264, fd1d4eb2-9d96-53a0-8f21-a466edac2151 | Yes | FK -> cards.card_id | - |
| transaction_time | timestamp string | Moc thoi gian | 2025-12-01 12:26:29, 2025-12-01 14:22:51, 2025-12-01 15:19:17 | No | - | - |
| amount | numeric | Gia tri tai chinh | 3220626, 996424, 1500000 | No | - | - |
| currency | enum string | Truong du lieu nghiep vu | VND, VND, VND | No | - | - |
| direction | enum string | Truong du lieu nghiep vu | OUT, OUT, OUT | No | - | - |
| transaction_type | enum string | Truong du lieu nghiep vu | CARD_PAYMENT, BILL_PAYMENT, CASH_WITHDRAWAL | No | - | - |
| category_id | UUID string | Dinh danh ban ghi | 4ecfbe52-8abc-53e2-b6a3-0bb910060f04, 90942bff-e299-5932-bde4-ea5aec361dd5, a57d1aed-a55d-5367-b993-6f9e4aac6c97 | No | FK -> transaction_categories.category_id | - |
| merchant_id | UUID string | Dinh danh ban ghi | fdf9d363-2a75-5cba-a44b-f32236ec5610, f56fa50f-fb61-5c75-b4d1-ffb62b61126c, eb59b3b8-4c38-5144-99e3-407c3208ebfd | Yes | FK -> merchants.merchant_id | - |
| biller_id | UUID string | Dinh danh ban ghi | c7aeadfb-8840-5a4d-b848-4ee75abae750, d3d0d0e0-a34b-50a6-9a0e-059d8b979ae6, 91bab014-7091-5a41-b9a5-7fb9f2fedcc2 | Yes | FK -> billers.biller_id | - |
| beneficiary_id | UUID string | Dinh danh ban ghi | 47ca8b7b-205e-5898-918b-5e011d720fff, 4cd53f49-f2b1-50ed-8917-faac70f4a2d8, ff0c645c-3212-5f9b-8ce6-1bf158bea27b | Yes | FK -> beneficiaries.beneficiary_id | - |
| counterparty_account_no | numeric | Ma/so nghiep vu | 814400040756, 106794975679, 0341528572 | Yes | - | - |
| counterparty_bank_code | enum string | Ma tham chieu nghiep vu | VCB, BIDV, BIDV | Yes | - | - |
| counterparty_name | string | Truong du lieu nghiep vu | Le Minh Hai, Nguyen Thi Vy, 0341528572 | Yes | - | - |
| channel | enum string | Truong du lieu nghiep vu | POS, MOBILE, ATM | No | - | - |
| note | string | Noi dung mo ta | Thanh toan tai Galaxy Cinema, Thanh toan hoa don water SAWACO PW418679207, Rut tien mat ATM | No | - | - |
| description | string | Noi dung mo ta | Thanh toan tai Galaxy Cinema, Thanh toan hoa don water SAWACO PW418679207, Rut tien mat ATM | No | - | - |
| status | enum string | Trang thai/muc do theo workflow | SUCCESS, SUCCESS, SUCCESS | No | - | Gia tri phai khop enum cua workflow hien tai |
| balance_after | numeric | Truong du lieu nghiep vu | 18984074, 157374711, 173508097 | Yes | - | - |
| external_reference | string | Truong du lieu nghiep vu | EXTCAR000001, EXTCAS000003, EXTBAN000004 | Yes | - | - |
| created_at | timestamp string | Moc thoi gian | 2025-12-01 12:26:37, 2025-12-01 14:22:55, 2025-12-01 15:19:25 | No | - | - |

## 4. Important Values / Enums

| Column | Value | Meaning | Example Use Case |
|---|---|---|---|
| direction | IN | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| direction | OUT | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| transaction_type | BANK_TRANSFER | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| transaction_type | BILL_PAYMENT | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| transaction_type | CARD_PAYMENT | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| transaction_type | CASH_DEPOSIT | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| transaction_type | CASH_WITHDRAWAL | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| transaction_type | FEE | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| transaction_type | INTEREST | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| transaction_type | PHONE_TOPUP | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| transaction_type | REFUND | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| transaction_type | SALARY | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| counterparty_bank_code | ACB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| counterparty_bank_code | BIDV | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| counterparty_bank_code | CTG | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| counterparty_bank_code | MB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| counterparty_bank_code | STB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| counterparty_bank_code | TCB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| counterparty_bank_code | TPB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| counterparty_bank_code | VCB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| counterparty_bank_code | VIB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| counterparty_bank_code | VPB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| channel | ATM | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| channel | CARD | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| channel | MOBILE | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| channel | POS | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| channel | QR | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| channel | WEB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| status | FAILED | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| status | PENDING | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| status | REVERSED | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| status | SUCCESS | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |

## 5. Relationships

- transactions.cif_no -> customers.cif_no
- transactions.account_no -> accounts.account_no
- transactions.card_id -> cards.card_id
- transactions.merchant_id -> merchants.merchant_id
- transactions.biller_id -> billers.biller_id
- transactions.beneficiary_id -> beneficiaries.beneficiary_id
- transactions.category_id -> transaction_categories.category_id

## 6. Simple Usage Examples

```sql
SELECT * FROM transactions LIMIT 5;
SELECT * FROM transactions WHERE cif_no = 'CIF000001' LIMIT 10;
```
