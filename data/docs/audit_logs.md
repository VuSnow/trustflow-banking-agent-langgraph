# audit_logs

## 1. Muc dich bang

Luu audit trace bat bien cho tung buoc workflow.

**Nhom:** Audit log

## 2. Ngu canh nghiep vu

- Bang nay phuc vu luong xu ly cua cac agent trong he thong TrustFlow.
- Du lieu duoc dung de truy van read model, xac thuc thong tin va truy vet audit.
- Day la mock data cho demo, khong phai core ledger van hanh that.

## 3. Columns

| Column | Type | Meaning | Example Values From Data | Nullable | Key / Relationship | Notes |
|---|---|---|---|---|---|---|
| audit_id | UUID string | Dinh danh ban ghi | 90f87dd4-8505-5d93-ae3e-e54de5bdf06a, 84da15cb-f39c-5e94-9528-6964c70ddbc1, 4122fdbb-70ea-513f-b707-ad28c9c718a3 | No | - | - |
| action_id | UUID string | Dinh danh ban ghi | 10a66751-e588-52b3-8c89-c500d10fd465, 10a66751-e588-52b3-8c89-c500d10fd465, 10a66751-e588-52b3-8c89-c500d10fd465 | No | FK -> action_requests.action_id | - |
| cif_no | string | Ma/so nghiep vu | CIF000057, CIF000057, CIF000057 | No | FK -> customers.cif_no | - |
| event_type | string | Truong du lieu nghiep vu | USER_REQUEST_RECEIVED, INTENT_CLASSIFIED, ENTITY_EXTRACTED | No | - | - |
| actor | enum string | Truong du lieu nghiep vu | USER, ORCHESTRATOR, TRANSACTION_AGENT | No | - | - |
| event_payload | JSON string | Truong du lieu nghiep vu | {"event": "USER_REQUEST_RECEIVED", "action_type": "TRANSFER", "user_text": "Gui tien cho me 5 trieu"}, {"event": "INTENT_CLASSIFIED", "action_type": "TRANSFER"}, {"event": "ENTITY_EXTRACTED", "action_type": "TRANSFER"} | No | - | JSON payload phuc vu truy vet hoac dieu phoi flow |
| created_at | timestamp string | Moc thoi gian | 2026-05-12 18:35:20, 2026-05-12 18:35:22, 2026-05-12 18:35:25 | No | - | - |

## 4. Important Values / Enums

| Column | Value | Meaning | Example Use Case |
|---|---|---|---|
| actor | EXECUTOR | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| actor | GUARDIAN | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| actor | ORCHESTRATOR | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| actor | TRANSACTION_AGENT | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| actor | USER | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |

## 5. Relationships

- audit_logs.action_id -> action_requests.action_id
- audit_logs.cif_no -> customers.cif_no

## 6. Simple Usage Examples

```sql
SELECT * FROM audit_logs LIMIT 5;
SELECT * FROM audit_logs WHERE cif_no = 'CIF000001' LIMIT 10;
```
