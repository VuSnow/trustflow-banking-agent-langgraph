# action_requests

## 1. Muc dich bang

Luu draft va trang thai xu ly cac hanh dong nhay cam cua agent.

**Nhom:** Workflow/action store

## 2. Ngu canh nghiep vu

- Bang nay phuc vu luong xu ly cua cac agent trong he thong TrustFlow.
- Du lieu duoc dung de truy van read model, xac thuc thong tin va truy vet audit.
- Day la mock data cho demo, khong phai core ledger van hanh that.

## 3. Columns

| Column | Type | Meaning | Example Values From Data | Nullable | Key / Relationship | Notes |
|---|---|---|---|---|---|---|
| action_id | UUID string | Dinh danh ban ghi | 10a66751-e588-52b3-8c89-c500d10fd465, bbd8c20a-2e83-5670-a6b3-a43703812c12, 9e07d189-c48d-5ff0-bbc2-cb437f37e4e3 | No | - | - |
| cif_no | string | Ma/so nghiep vu | CIF000057, CIF000055, CIF000019 | No | FK -> customers.cif_no | - |
| action_type | enum string | Truong du lieu nghiep vu | TRANSFER, TRANSFER, TRANSFER | No | - | - |
| status | enum string | Trang thai/muc do theo workflow | EXECUTED, PENDING_CONFIRMATION, MISSING_INFO | No | - | Gia tri phai khop enum cua workflow hien tai |
| user_text | string | Noi dung mo ta | Gui tien cho me 5 trieu, Chuyen tien thue nha thang nay, Chuyen cho Minh 2 trieu nhu thang truoc | No | - | - |
| api_name | string | Truong du lieu nghiep vu | external_transfer_api, external_transfer_api, external_transfer_api | No | - | - |
| api_payload | JSON string | Truong du lieu nghiep vu | {"from_account_no": "5861793271040", "to_account_no": "95429618446", "to_bank_code": "BIDV", "to_name": "Pham Duc Yen", "amount": 49177401, "currency": "VND", "description": "Chuyen tien cho Yen"}, {"from_account_no": "2959391725", "to_account_no": "438612590472", "to_bank_code": "VIB", "to_name": "Tran Anh Lan", "amount": 24918275, "currency": "VND", "description": "Chuyen tien cho Lan"}, {} | No | - | JSON payload phuc vu truy vet hoac dieu phoi flow |
| resolved_entities | JSON string | Truong du lieu nghiep vu | {"beneficiary_name": "Pham Duc Yen", "amount": 49177401, "bank_code": "BIDV"}, {"beneficiary_name": "Tran Anh Lan", "amount": 24918275, "bank_code": "VIB"}, {"beneficiary_name": "Le Van Minh", "amount": 3400034, "bank_code": "CTG"} | No | - | JSON payload phuc vu truy vet hoac dieu phoi flow |
| missing_fields | JSON string | Truong du lieu nghiep vu | [], [], ["to_bank_code", "to_name"] | No | - | JSON payload phuc vu truy vet hoac dieu phoi flow |
| risk_score | numeric | Truong du lieu nghiep vu | 0.13, 0.36, 0.54 | No | - | - |
| risk_tier | enum string | Trang thai/muc do theo workflow | GREEN, YELLOW, YELLOW | No | - | - |
| requires_confirmation | boolean | Truong du lieu nghiep vu | True, True, True | No | - | Co/khong theo logic nghiep vu |
| requires_otp | boolean | Truong du lieu nghiep vu | True, True, True | No | - | Co/khong theo logic nghiep vu |
| created_at | timestamp string | Moc thoi gian | 2026-05-12 18:35:17, 2026-04-28 07:49:54, 2026-05-22 15:14:01 | No | - | - |
| updated_at | timestamp string | Moc thoi gian | 2026-05-12 18:35:44, 2026-04-28 07:54:26, 2026-05-22 15:15:10 | No | - | - |

## 4. Important Values / Enums

| Column | Value | Meaning | Example Use Case |
|---|---|---|---|
| action_type | BILL_PAYMENT | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| action_type | CARD_LIMIT_CHANGE | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| action_type | CARD_LOCK | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| action_type | CARD_UNLOCK | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| action_type | PHONE_TOPUP | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| action_type | TRANSFER | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| status | BLOCKED | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| status | DRAFT | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| status | EXECUTED | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| status | FAILED | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| status | MISSING_INFO | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| status | PENDING_CONFIRMATION | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| status | PENDING_OTP | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| status | READY_TO_EXECUTE | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| risk_tier | GREEN | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| risk_tier | ORANGE | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| risk_tier | RED | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| risk_tier | YELLOW | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |

## 5. Relationships

- action_requests.cif_no -> customers.cif_no

## 6. Simple Usage Examples

```sql
SELECT * FROM action_requests LIMIT 5;
SELECT * FROM action_requests WHERE cif_no = 'CIF000001' LIMIT 10;
```
