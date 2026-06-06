# Transaction (Transfer Money) — Test Cases

> User test: `CIF000001` (có beneficiary "Bui Duc Tuan" — ACB, saved beneficiary)  
> Mock OTP: `123456`  
> Bank code hiện tại: `SHB`

---

## TC1: Transfer by beneficiary name — Full happy path

**User:** `CIF000001`

| # | Role | Message |
|---|------|---------|
| 1 | User | chuyển 2 triệu cho Tuấn |
| 2 | Bot | Tôi tìm thấy người nhận:<br>• Tên: Bui Duc Tuan<br>• Ngân hàng: ACB<br>• Số tài khoản: ****0556<br><br>Đây có đúng là người bạn muốn chuyển không? |
| 3 | User | đúng rồi |
| 4 | Bot | Vui lòng kiểm tra thông tin giao dịch:<br><br>Từ tài khoản: ****XXXX<br>Đến: Bui Duc Tuan<br>Ngân hàng: ACB<br>Số tài khoản: ****0556<br>Số tiền: 2,000,000 VND<br>Phí giao dịch: 5,500 VND<br>Tổng tiền trừ: 2,005,500 VND<br>Nội dung: Chuyển tiền<br><br>Bạn xác nhận thực hiện giao dịch này chứ? |
| 5 | User | xác nhận |
| 6 | Bot | Tôi đã gửi mã OTP đến số điện thoại đăng ký của bạn.<br>Vui lòng nhập OTP để hoàn tất giao dịch.<br><br>Giao dịch: chuyển 2,000,000 VND đến Bui Duc Tuan. |
| 7 | User | 123456 |
| 8 | Bot | Giao dịch thành công.<br><br>Mã giao dịch: TXN...<br>Thời gian: ...<br>Từ tài khoản: ****XXXX<br>Người nhận: Bui Duc Tuan<br>Ngân hàng: ACB<br>Số tài khoản nhận: ****0556<br><br>Số tiền chuyển: 2,000,000 VND<br>Phí giao dịch: 5,500 VND<br>Tổng tiền đã trừ: 2,005,500 VND<br>Số dư còn lại: ... VND |

**Expected step 2:** `flow_status=WAITING_RECIPIENT_CONFIRMATION`, `auth_required=confirm`  
**Expected step 4:** `flow_status=WAITING_DRAFT_CONFIRMATION`, `auth_required=confirm`  
**Expected step 6:** `flow_status=WAITING_OTP`, `auth_required=otp`  
**Expected step 8:** `flow_status=null`, `status=completed`, `data.executed=true`

---

## TC2: Transfer without amount → Ask amount

**User:** `CIF000001`

| # | Role | Message |
|---|------|---------|
| 1 | User | chuyển tiền cho Tuấn |
| 2 | Bot | Bạn muốn chuyển bao nhiêu tiền? |
| 3 | User | 3 triệu |
| 4 | Bot | Tôi tìm thấy người nhận:<br>• Tên: Bui Duc Tuan<br>• Ngân hàng: ACB<br>• Số tài khoản: ****0556<br><br>Đây có đúng là người bạn muốn chuyển không? |

**Expected step 2:** `flow_status=COLLECTING`, pending_question.slot=`amount`  
**Expected step 4:** `flow_status=WAITING_RECIPIENT_CONFIRMATION`

---

## TC3: Transfer by direct account number

**User:** `CIF000001`

| # | Role | Message |
|---|------|---------|
| 1 | User | chuyển 500k vào 5332557597 ACB |
| 2 | Bot | Tôi tìm thấy người nhận:<br>• Tên: Hoang Anh Mai<br>• Ngân hàng: ACB<br>• Số tài khoản: ****7597<br><br>Đây có đúng là người bạn muốn chuyển không? |

**Expected:** `flow_status=WAITING_RECIPIENT_CONFIRMATION`, recipient resolved via account lookup

---

## TC4: Transfer to last recipient (past transaction)

**User:** `CIF000001`

| # | Role | Message |
|---|------|---------|
| 1 | User | chuyển 1tr cho người tôi chuyển lần trước |
| 2 | Bot | Tôi tìm thấy người nhận:<br>• Tên: ...<br>• Ngân hàng: ...<br>• Số tài khoản: ****...<br><br>Đây có đúng là người bạn muốn chuyển không? |

**Expected:** `flow_status=WAITING_RECIPIENT_CONFIRMATION`, resolved from transaction history

---

## TC5: Multiple beneficiaries with same name → Selection

**User:** User có nhiều beneficiary cùng tên

| # | Role | Message |
|---|------|---------|
| 1 | User | chuyển 1 triệu cho Nguyễn Văn A |
| 2 | Bot | Tôi tìm thấy 2 người tên "Nguyễn Văn A":<br><br>1. Nguyễn Văn A — Vietcombank — ****1234<br>2. Nguyễn Văn A — Techcombank — ****5678<br><br>Bạn muốn chuyển cho ai? (Nhập số thứ tự) |
| 3 | User | 1 |
| 4 | Bot | Tôi tìm thấy người nhận: ... Đây có đúng là người bạn muốn chuyển không? |

**Expected step 2:** `flow_status=COLLECTING`, pending_question.slot=`recipient_choice`  
**Expected step 4:** `flow_status=WAITING_RECIPIENT_CONFIRMATION`

---

## TC6: Recipient not found

**User:** `CIF000001`

| # | Role | Message |
|---|------|---------|
| 1 | User | chuyển 1 triệu cho Nguyễn Quang Hải |
| 2 | Bot | Tôi không tìm thấy người nhận "Nguyễn Quang Hải" trong danh sách.<br>Vui lòng cung cấp số tài khoản và ngân hàng, hoặc kiểm tra lại tên. |

**Expected:** `flow_status=COLLECTING`, pending_question.slot=`recipient_query`

---

## TC7: Wrong OTP → Retry

| # | Role | Message |
|---|------|---------|
| 1-6 | ... | *(reach WAITING_OTP)* |
| 7 | User | 111111 |
| 8 | Bot | Mã OTP không đúng. Còn 2 lần thử. Vui lòng nhập lại. |
| 9 | User | 222222 |
| 10 | Bot | Mã OTP không đúng. Còn 1 lần thử. Vui lòng nhập lại. |
| 11 | User | 333333 |
| 12 | Bot | Đã vượt quá số lần nhập OTP. Giao dịch đã bị hủy vì lý do bảo mật. |

**Expected step 8:** `flow_status=WAITING_OTP` (still active)  
**Expected step 12:** `flow_status=null`, flow cancelled by system

---

## TC8: Cancel during OTP

| # | Role | Message |
|---|------|---------|
| 1-6 | ... | *(reach WAITING_OTP)* |
| 7 | User | hủy |
| 8 | Bot | Đã hủy giao dịch. |

**Expected:** `flow_status=null`, flow cleared

---

## TC9: Cancel during draft confirmation

| # | Role | Message |
|---|------|---------|
| 1-4 | ... | *(reach WAITING_DRAFT_CONFIRMATION)* |
| 5 | User | không, hủy đi |
| 6 | Bot | Đã hủy giao dịch. |

**Expected:** `flow_status=null`

---

## TC10: Interrupt locked flow (new intent during OTP)

| # | Role | Message |
|---|------|---------|
| 1-6 | ... | *(reach WAITING_OTP)* |
| 7 | User | tôi muốn kiểm tra số dư |
| 8 | Bot | Bạn đang có giao dịch chờ xác thực OTP:<br><br>Chuyển 2,000,000 VND đến Bui Duc Tuan<br><br>Để tiếp tục việc khác, bạn cần:<br>1. Nhập OTP để hoàn tất giao dịch<br>2. Hủy giao dịch này<br><br>Bạn muốn nhập OTP hay hủy giao dịch? |

**Expected:** `flow_status=WAITING_OTP`, interrupted_intent stored

---

## TC11: QA question — No flow created

**User:** `CIF000001`

| # | Role | Message |
|---|------|---------|
| 1 | User | ngân hàng SHB có bao nhiêu chi nhánh? |
| 2 | Bot | *(QA answer from knowledge base)* |

**Expected:** `flow_status=null`, `status=success`, no flow created

---

## TC12: Modify draft

| # | Role | Message |
|---|------|---------|
| 1-4 | ... | *(reach WAITING_DRAFT_CONFIRMATION, 2tr)* |
| 5 | User | đổi thành 3 triệu |
| 6 | Bot | *(new draft summary with 3,000,000 VND)* Bạn xác nhận thực hiện giao dịch này chứ? |

**Expected step 6:** `flow_status=WAITING_DRAFT_CONFIRMATION`, amount updated to 3,000,000

---

## TC13: Internal transfer (same bank SHB) → Fee = 0

**User:** `CIF000001` chuyển cho tài khoản SHB

| # | Role | Message |
|---|------|---------|
| 1 | User | chuyển 1 triệu vào 1234567890 SHB |
| 2 | Bot | Tôi tìm thấy người nhận: ... Đây có đúng không? |
| 3 | User | ok |
| 4 | Bot | ... Phí giao dịch: 0 VND<br>Tổng tiền trừ: 1,000,000 VND ... |

**Expected:** `transaction_type=INTERNAL_TRANSFER`, fee=0

---

## TC14: Fraud warning — High risk account

| # | Role | Message |
|---|------|---------|
| 1 | User | chuyển 5 triệu vào [tài khoản có báo cáo lừa đảo] |
| 2 | Bot | Tôi tìm thấy người nhận: ... Đây có đúng không? |
| 3 | User | ok |
| 4 | Bot | ⚠️ CẢNH BÁO: Tài khoản nhận có N báo cáo nghi ngờ lừa đảo với mức rủi ro CAO. Vui lòng cân nhắc kỹ trước khi tiếp tục.<br><br>*(draft summary)* ... Bạn xác nhận? |

**Expected:** Warning shown but transaction still allowed (risk=HIGH, not CRITICAL)

---

## TC15: Fraud block — Critical risk account

| # | Role | Message |
|---|------|---------|
| 1 | User | chuyển tiền vào [tài khoản bị block] |
| 2 | Bot | Tôi tìm thấy người nhận: ... Đây có đúng không? |
| 3 | User | ok |
| 4 | Bot | ⚠️ Tài khoản này đã bị xác nhận là tài khoản lừa đảo. Giao dịch không thể thực hiện. |

**Expected:** `flow_status=null`, flow cancelled by system (fraud_screening.risk_level=CRITICAL)

---

## Flow State Machine

```
COLLECTING ──→ WAITING_RECIPIENT_CONFIRMATION ──→ WAITING_DRAFT_CONFIRMATION ──→ WAITING_OTP ──→ EXECUTING ──→ COMPLETED
    │                    │                              │                           │
    │ (ask amount/       │ (cancel)                     │ (cancel/modify)           │ (cancel/expired/max_attempts)
    │  ask recipient/    └── CANCELLED                  └── CANCELLED /             └── CANCELLED
    │  multiple choice)                                      back to COLLECTING
    └── COLLECTING
```

## Key Design Points

1. **TransactionExtractor** (LLM): extracts amount, recipient_query, account_no, bank, note + generates `RecipientResolutionPlan`
2. **RecipientResolver** (SQL): executes plan → `find_by_name`, `find_by_account_no`, `find_last_transfer_recipient`
3. **TransactionValidator**: checks amount limits, balance, fraud screening
4. **OTP hash binding**: `sha256(amount:recipient_account_no:recipient_bank_code:source_account_no)` — prevents post-OTP tampering
5. **Fee logic**: `INTERNAL_TRANSFER` (same bank) = 0 VND, `INTERBANK_TRANSFER` = 5,500 VND
6. **Fraud screening**: HIGH = warning shown, CRITICAL = transaction blocked
