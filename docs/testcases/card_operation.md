# Card Operation — Test Cases

> User test: `CIF000006` (has 2 cards)  
> Cards:  
>   - **** **** **** 4223 (DEBIT NAPAS) — ACTIVE  
>   - **** **** **** 8515 (DEBIT MASTERCARD) — ACTIVE  
> Mock OTP: `123456`  
> Operations: VIEW_CARD_INFO, LOCK_CARD, UNLOCK_CARD, REPORT_LOST

---

## TC1: View card — Multi-card disambiguation

**User:** `CIF000006`

| # | Role | Message |
|---|------|---------|
| 1 | User | xem thẻ của tôi |
| 2 | Bot | Bạn có 2 thẻ:<br><br>  1. **** **** **** 4223 (DEBIT NAPAS) — ACTIVE<br>  2. **** **** **** 8515 (DEBIT MASTERCARD) — ACTIVE<br><br>Bạn muốn thao tác với thẻ nào? (Nhập số thứ tự) |
| 3 | User | 1 |
| 4 | Bot | Thông tin thẻ:<br><br>• Số thẻ: **** **** **** 4223<br>• Loại: DEBIT<br>• Mạng: NAPAS<br>• Trạng thái: ACTIVE<br>• Tài khoản liên kết: 4124782613 |

**Expected step 2:** `flow_status=COLLECTING`, `pending_question.expected_type=enum`  
**Expected step 4:** `flow_status=null`, `status=success` (no confirmation needed for VIEW)

---

## TC2: Lock card — Direct resolution by last4

**User:** `CIF000006`

| # | Role | Message |
|---|------|---------|
| 1 | User | khóa thẻ đuôi 4223 |
| 2 | Bot | Xác nhận khóa tạm thời thẻ **** **** **** 4223 (DEBIT NAPAS)?<br><br>⚠️ Thẻ sẽ không thể sử dụng cho đến khi bạn mở khóa. |
| 3 | User | đồng ý |
| 4 | Bot | ✅ Đã khóa tạm thời thẻ **** **** **** 4223. |

**Expected step 2:** `flow_status=WAITING_CARD_CONFIRMATION`, `auth_required=confirm`  
**Expected step 4:** `flow_status=null`, card status in DB = `TEMP_LOCKED`

---

## TC3: Unlock card — Confirm + OTP

**Precondition:** Card 4223 must be in `TEMP_LOCKED` status (run TC2 first).

**User:** `CIF000006`

| # | Role | Message |
|---|------|---------|
| 1 | User | mở khóa thẻ đuôi 4223 |
| 2 | Bot | Xác nhận mở khóa thẻ **** **** **** 4223 (DEBIT NAPAS)? |
| 3 | User | xác nhận |
| 4 | Bot | Tôi đã gửi mã OTP đến số điện thoại đăng ký của bạn.<br>Vui lòng nhập OTP để mở khóa thẻ **** **** **** 4223. |
| 5 | User | 123456 |
| 6 | Bot | ✅ Đã mở khóa thẻ **** **** **** 4223. |

**Expected step 2:** `flow_status=WAITING_CARD_CONFIRMATION`, `auth_required=confirm`  
**Expected step 4:** `flow_status=WAITING_OTP`, `auth_required=otp`  
**Expected step 6:** `flow_status=null`, card status in DB = `ACTIVE`

---

## TC4: Report lost — Multi-card + Strong warning + Decline

**User:** `CIF000006`

| # | Role | Message |
|---|------|---------|
| 1 | User | báo mất thẻ |
| 2 | Bot | Bạn có 2 thẻ:<br><br>  1. **** **** **** 4223 (DEBIT NAPAS) — ACTIVE<br>  2. **** **** **** 8515 (DEBIT MASTERCARD) — ACTIVE<br><br>Bạn muốn thao tác với thẻ nào? (Nhập số thứ tự) |
| 3 | User | 2 |
| 4 | Bot | ⚠️ **CẢNH BÁO**: Báo mất thẻ **** **** **** 8515 (DEBIT MASTERCARD)?<br><br>Hành động này là **VĨNH VIỄN** — thẻ sẽ bị vô hiệu hóa và không thể mở khóa lại.<br>Bạn có chắc chắn không? |
| 5 | User | không |
| 6 | Bot | Đã hủy giao dịch. |

**Expected step 2:** `flow_status=COLLECTING`, `pending_question.expected_type=enum`  
**Expected step 4:** `flow_status=WAITING_CARD_CONFIRMATION`, `auth_required=confirm`  
**Expected step 6:** `flow_status=null`, card status unchanged

---

## TC5: Report lost — Confirm execution

**User:** `CIF000006`

| # | Role | Message |
|---|------|---------|
| 1 | User | báo mất thẻ mastercard |
| 2 | Bot | ⚠️ **CẢNH BÁO**: Báo mất thẻ **** **** **** 8515 (DEBIT MASTERCARD)?<br><br>Hành động này là **VĨNH VIỄN** — thẻ sẽ bị vô hiệu hóa và không thể mở khóa lại.<br>Bạn có chắc chắn không? |
| 3 | User | có |
| 4 | Bot | ✅ Đã báo mất thẻ **** **** **** 8515. Thẻ đã bị vô hiệu hóa vĩnh viễn. |

**Expected step 2:** `flow_status=WAITING_CARD_CONFIRMATION`, `auth_required=confirm` (direct resolution via network hint "mastercard")  
**Expected step 4:** `flow_status=null`, card status in DB = `LOST`

---

## TC6: Lock card — Invalid status (already locked)

**Precondition:** Card 4223 in `TEMP_LOCKED` status.

**User:** `CIF000006`

| # | Role | Message |
|---|------|---------|
| 1 | User | khóa thẻ đuôi 4223 |
| 2 | Bot | Thẻ hiện đang ở trạng thái TEMP_LOCKED, không thể khóa. |

**Expected step 2:** `flow_status=null`, `status=success` (completed with error message)

---

## TC7: Unlock card — Invalid status (already active)

**User:** `CIF000006`

| # | Role | Message |
|---|------|---------|
| 1 | User | mở khóa thẻ đuôi 4223 |
| 2 | Bot | Thẻ hiện đang ở trạng thái ACTIVE, không thể mở khóa. |

**Expected step 2:** `flow_status=null`, completed with validation error

---

## TC8: View single card by hint — No disambiguation needed

**User:** `CIF000006`

| # | Role | Message |
|---|------|---------|
| 1 | User | xem thông tin thẻ napas |
| 2 | Bot | Thông tin thẻ:<br><br>• Số thẻ: **** **** **** 4223<br>• Loại: DEBIT<br>• Mạng: NAPAS<br>• Trạng thái: ACTIVE<br>• Tài khoản liên kết: 4124782613 |

**Expected step 2:** `flow_status=null`, direct resolution by network hint → single match → show info

---

## Architecture Notes

### Flow Pattern
```
Intent Classifier → CARD_OPERATION
  → CardOperationExtractor (pure LLM: extracts operation + card hints)
  → _resolve_card() (SQL lookup by hints → single match or disambiguation list)
  → Confirmation (LOCK: confirm only, UNLOCK: confirm+OTP, REPORT_LOST: confirm with strong warning)
  → _execute_card_operation() (calls card_tools.lock_card/unlock_card/report_lost_card)
```

### Security Levels
| Operation | Confirmation | OTP | Reversible |
|-----------|-------------|-----|-----------|
| VIEW_CARD_INFO | No | No | N/A (read-only) |
| LOCK_CARD | Yes | No | Yes (can unlock) |
| UNLOCK_CARD | Yes | Yes | Yes (can re-lock) |
| REPORT_LOST | Yes (strong warning) | No | No (permanent) |

### OTP Binding
- Hash: `sha256(card_id:operation)` — prevents hash reuse across operations
- Only UNLOCK_CARD requires OTP (elevated security for enabling access)

### Key Files
- `backend/agents/card_operation.py` — CardOperationExtractor (LLM entity extraction)
- `backend/prompts/card_operation.py` — CARD_EXTRACT_SYSTEM_PROMPT
- `backend/graphs/orchestrator.py` — _handle_card_collecting(), _resolve_card(), _execute_card_operation()
- `backend/tools/card_tools.py` — lock_card, unlock_card, report_lost_card (DB operations)
- `backend/models/flow.py` — CardDraft model
