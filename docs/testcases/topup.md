# Top-Up (Phone/Wallet) — Test Cases

> User test: `CIF000001`  
> Mock OTP: `123456`  
> Phone amount limits: 10,000 — 500,000 VND  
> Wallet amount limits: 10,000 — 10,000,000 VND

---

## TC1: Full happy path — Phone + Amount in one message

**User:** `CIF000001`

| # | Role | Message |
|---|------|---------|
| 1 | User | nạp 50k cho 0986123456 |
| 2 | Bot | Xác nhận nạp tiền:<br><br>• Số điện thoại: 0986123456<br>• Nhà mạng: Viettel<br>• Số tiền: 50,000 VND<br><br>Bạn xác nhận nạp tiền không? |
| 3 | User | ok |
| 4 | Bot | Tôi đã gửi mã OTP đến số điện thoại đăng ký của bạn.<br>Vui lòng nhập OTP để hoàn tất nạp tiền.<br><br>Nạp 50,000 VND cho 0986123456 (Viettel). |
| 5 | User | 123456 |
| 6 | Bot | Nạp tiền thành công.<br><br>Mã giao dịch: TOPUP...<br>Thời gian: ...<br>Số điện thoại: 0986123456<br>Nhà mạng: Viettel<br>Số tiền: 50,000 VND<br>Số dư còn lại: ... VND |

**Expected step 2:** `flow_status=WAITING_TOPUP_CONFIRMATION`, `auth_required=confirm`  
**Expected step 4:** `flow_status=WAITING_OTP`, `auth_required=otp`  
**Expected step 6:** `flow_status=null`, `status=completed`, `data.executed=true`

---

## TC2: Missing phone → Ask phone → Confirmation

**User:** `CIF000001`

| # | Role | Message |
|---|------|---------|
| 1 | User | nạp điện thoại 100k |
| 2 | Bot | Bạn muốn nạp tiền cho số điện thoại nào? |
| 3 | User | 0912345678 |
| 4 | Bot | Xác nhận nạp tiền:<br><br>• Số điện thoại: 0912345678<br>• Nhà mạng: Mobifone<br>• Số tiền: 100,000 VND<br><br>Bạn xác nhận nạp tiền không? |

**Expected step 2:** `flow_status=COLLECTING`, pending_question.slot=`topup_target`  
**Expected step 4:** `flow_status=WAITING_TOPUP_CONFIRMATION`

---

## TC3: Missing amount → Ask amount → Confirmation

**User:** `CIF000001`

| # | Role | Message |
|---|------|---------|
| 1 | User | nạp tiền cho 0986123456 |
| 2 | Bot | Bạn muốn nạp bao nhiêu cho số 0986123456? |
| 3 | User | 200k |
| 4 | Bot | Xác nhận nạp tiền:<br><br>• Số điện thoại: 0986123456<br>• Nhà mạng: Viettel<br>• Số tiền: 200,000 VND<br><br>Bạn xác nhận nạp tiền không? |

**Expected step 2:** `flow_status=COLLECTING`, pending_question.slot=`topup_amount`  
**Expected step 4:** `flow_status=WAITING_TOPUP_CONFIRMATION`

---

## TC4: Cancel during confirmation

| # | Role | Message |
|---|------|---------|
| 1 | User | nạp 50k cho 0986123456 |
| 2 | Bot | Xác nhận nạp tiền... |
| 3 | User | hủy |
| 4 | Bot | Đã hủy giao dịch. |

**Expected step 4:** `flow_status=null`

---

## TC5: Amount too high (phone max = 500k)

| # | Role | Message |
|---|------|---------|
| 1 | User | nạp 1 triệu cho 0912345678 |
| 2 | Bot | Số tiền nạp phải từ 10,000 đến 500,000 VND. |

**Expected:** `flow_status=COLLECTING`, amount rejected, asks for valid amount

---

## TC6: Amount too low

| # | Role | Message |
|---|------|---------|
| 1 | User | nạp 5k cho 0912345678 |
| 2 | Bot | Số tiền nạp phải từ 10,000 đến 500,000 VND. |

**Expected:** `flow_status=COLLECTING`, amount rejected

---

## TC7: Provider detection — Vinaphone

| # | Role | Message |
|---|------|---------|
| 1 | User | nạp 100k cho số 0881234567 |
| 2 | Bot | Xác nhận nạp tiền:<br>• Số điện thoại: 0881234567<br>• Nhà mạng: Vinaphone<br>• Số tiền: 100,000 VND<br><br>Bạn xác nhận nạp tiền không? |

**Expected:** Provider = Vinaphone (prefix 088)

---

## TC8: Provider detection — Mobifone

| # | Role | Message |
|---|------|---------|
| 1 | User | nạp 200k cho 0931234567 |
| 2 | Bot | ... Nhà mạng: Mobifone ... |

**Expected:** Provider = Mobifone (prefix 093)

---

## TC9: Provider hint only — Missing phone + amount

| # | Role | Message |
|---|------|---------|
| 1 | User | nạp tiền Viettel |
| 2 | Bot | Bạn muốn nạp tiền cho số điện thoại nào? |
| 3 | User | 0961234567 |
| 4 | Bot | Bạn muốn nạp bao nhiêu cho số 0961234567? |
| 5 | User | 100k |
| 6 | Bot | Xác nhận nạp tiền... Nhà mạng: Viettel ... |

**Expected:** Multi-step collecting, provider kept from initial hint

---

## TC10: Wrong OTP → Retry

| # | Role | Message |
|---|------|---------|
| 1-4 | ... | *(reach WAITING_OTP)* |
| 5 | User | 111111 |
| 6 | Bot | Mã OTP không đúng. Còn 2 lần thử. Vui lòng nhập lại. |

**Expected:** `flow_status=WAITING_OTP` (still active)

---

## TC11: Cancel during OTP

| # | Role | Message |
|---|------|---------|
| 1-4 | ... | *(reach WAITING_OTP)* |
| 5 | User | hủy |
| 6 | Bot | Đã hủy giao dịch. |

**Expected:** `flow_status=null`

---

## TC12: Interrupt locked flow during OTP

| # | Role | Message |
|---|------|---------|
| 1-4 | ... | *(reach WAITING_OTP for topup)* |
| 5 | User | tôi muốn chuyển tiền |
| 6 | Bot | Bạn đang có giao dịch chờ xác thực OTP:<br><br>Chuyển 50,000 VND đến 0986123456<br><br>Để tiếp tục việc khác, bạn cần:<br>1. Nhập OTP để hoàn tất giao dịch<br>2. Hủy giao dịch này<br><br>Bạn muốn nhập OTP hay hủy giao dịch? |

**Expected:** `flow_status=WAITING_OTP`, interrupted_intent stored

---

## TC13: Insufficient balance

| # | Role | Message |
|---|------|---------|
| 1 | User | nạp 500k cho 0912345678 |
| 2 | Bot | Xác nhận nạp tiền... |
| 3 | User | ok |
| 4 | Bot | *(OTP sent)* |
| 5 | User | 123456 |
| 6 | Bot | Nạp tiền thất bại: Số dư không đủ. ... |

**Expected:** Executor returns INSUFFICIENT_FUNDS error *(only if account balance < 500k)*

---

## Flow State Machine

```
COLLECTING ──────→ WAITING_TOPUP_CONFIRMATION ──→ WAITING_OTP ──→ EXECUTING ──→ COMPLETED
    │                        │                         │
    │ (ask phone/amount/     │ (cancel)                │ (cancel/expired/max_attempts)
    │  invalid amount)       └── CANCELLED             └── CANCELLED
    └── COLLECTING
```

## Key Design Points

1. **TopUpExtractor** (LLM): extracts phone, amount, provider, type — no tools/SQL needed
2. **Orchestrator validates**: phone format (10 digits starting with 0), amount range
3. **Carrier detection**: deterministic prefix matching (not LLM)
4. **OTP hash**: `sha256(topup_target:amount:topup_provider)` — prevents tampering
5. **Executor**: `TopUpExecutor` — debit account, insert transaction record
6. **No recipient verification** — carriers/wallets are trusted
7. **Amount limits**: phone 10k–500k, wallet 10k–10M
