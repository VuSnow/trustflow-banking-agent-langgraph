# api_call_logs

## 1. Muc dich bang

Luu request/response khi goi external API mock.

**Nhom:** API call log

## 2. Ngu canh nghiep vu

- Bang nay phuc vu luong xu ly cua cac agent trong he thong TrustFlow.
- Du lieu duoc dung de truy van read model, xac thuc thong tin va truy vet audit.
- Day la mock data cho demo, khong phai core ledger van hanh that.

## 3. Columns

| Column | Type | Meaning | Example Values From Data | Nullable | Key / Relationship | Notes |
|---|---|---|---|---|---|---|
| api_call_id | UUID string | Dinh danh ban ghi | 1fc9f267-0993-5fc0-a950-891c60d88548, ac784564-c041-51aa-aee0-3fdfc66de8ff, 3cc5f405-6f06-5d24-94b1-6092af95dfa9 | No | - | - |
| action_id | UUID string | Dinh danh ban ghi | 10a66751-e588-52b3-8c89-c500d10fd465, 95ff56b0-cd92-5fc7-9f5a-c0c32ebbf29f, 44888f96-0759-502c-a6c8-1401b62fa66e | No | FK -> action_requests.action_id | - |
| api_name | string | Truong du lieu nghiep vu | external_transfer_api, external_transfer_api, external_transfer_api | No | - | - |
| request_payload | JSON string | Truong du lieu nghiep vu | {"from_account_no": "5861793271040", "to_account_no": "95429618446", "to_bank_code": "BIDV", "to_name": "Pham Duc Yen", "amount": 49177401, "currency": "VND", "description": "Chuyen tien cho Yen"}, {"from_account_no": "08330165712", "to_account_no": "3034615626244", "to_bank_code": "CTG", "to_name": "Le Van Minh", "amount": 2287078, "currency": "VND", "description": "Chuyen tien cho Minh"}, {"from_account_no": "1039308705", "to_account_no": "5668633414", "to_bank_code": "TCB", "to_name": "Vo Minh Nhi", "amount": 43753536, "currency": "VND", "description": "Chuyen tien cho Nhi"} | No | - | JSON payload phuc vu truy vet hoac dieu phoi flow |
| response_payload | JSON string | Truong du lieu nghiep vu | {"external_reference": "EXTTRA000001", "status": "SUCCESS", "message": "Operation completed successfully"}, {"external_reference": "EXTTRA000002", "status": "SUCCESS", "message": "Operation completed successfully"}, {"external_reference": "EXTTRA000003", "status": "SUCCESS", "message": "Operation completed successfully"} | No | - | JSON payload phuc vu truy vet hoac dieu phoi flow |
| http_status | numeric | Truong du lieu nghiep vu | 200, 200, 200 | No | - | - |
| status | enum string | Trang thai/muc do theo workflow | SUCCESS, SUCCESS, SUCCESS | No | - | Gia tri phai khop enum cua workflow hien tai |
| created_at | timestamp string | Moc thoi gian | 2026-05-12 18:35:19, 2026-05-09 10:52:55, 2026-04-07 19:17:12 | No | - | - |

## 4. Important Values / Enums

| Column | Value | Meaning | Example Use Case |
|---|---|---|---|
| status | FAILED | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| status | SUCCESS | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |

## 5. Relationships

- api_call_logs.action_id -> action_requests.action_id

## 6. Simple Usage Examples

```sql
SELECT * FROM api_call_logs LIMIT 5;
```
