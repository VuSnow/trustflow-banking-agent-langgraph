# Transaction Category Classification — Test Cases

> Trigger: After OTP success for TRANSACTION flow  
> User test: `CIF000001`  
> Mock OTP: `123456`  
> Categories from: `transaction_categories` table (direction=OUT, excludes INCOME)

---

## TC1: Confirm predicted category

**User:** `CIF000001`

| # | Role | Message |
|---|------|---------|
| 1 | User | chuyển 1 triệu cho Tuấn |
| 2 | Bot | Tôi tìm thấy người nhận... Đây có đúng không? |
| 3 | User | ok |
| 4 | Bot | Vui lòng kiểm tra thông tin... Xác nhận? |
| 5 | User | ok |
| 6 | Bot | Tôi đã gửi mã OTP... |
| 7 | User | 123456 |
| 8 | Bot | Giao dịch thành công...<br><br>📂 Giao dịch này thuộc loại: **Chuyen khoan**<br>Đúng không? Hoặc chọn:<br>  1. Chuyen khoan gia dinh<br>  2. Tien thue nha<br>  3. Khac<br>  4. An uong<br>  5. Mua sam<br>(Gõ "bỏ qua" nếu không muốn phân loại) |
| 9 | User | ok |
| 10 | Bot | ✅ Đã phân loại: **Chuyen khoan** |

**Expected step 8:** `flow_status=WAITING_CATEGORY_CONFIRMATION`, `auth_required=category_confirm`  
**Expected step 10:** `flow_status=null`, category saved to DB

---

## TC2: Select alternative category by number

| # | Role | Message |
|---|------|---------|
| 1-8 | ... | *(reach WAITING_CATEGORY_CONFIRMATION, predicted=TRANSFER)* |
| 9 | User | 1 |
| 10 | Bot | ✅ Đã phân loại: **Chuyen khoan gia dinh** |

**Expected:** Routes as `ANSWER_PENDING_QUESTION`, saves alternative's category_id

---

## TC3: Skip — "bỏ qua"

| # | Role | Message |
|---|------|---------|
| 1-8 | ... | *(reach WAITING_CATEGORY_CONFIRMATION)* |
| 9 | User | bỏ qua |
| 10 | Bot | 📂 Đã lưu phân loại: **Chuyen khoan** |

**Expected:** Routes as `CANCEL_ACTIVE_FLOW`, saves **predicted** value to DB

---

## TC4: User switches to new question (QA)

| # | Role | Message |
|---|------|---------|
| 1-8 | ... | *(reach WAITING_CATEGORY_CONFIRMATION)* |
| 9 | User | SHB có bao nhiêu chi nhánh? |
| 10 | Bot | *(QA answer about SHB branches)* |

**Expected:**  
- Routes as `CLASSIFY_NEW_INTENT`  
- Auto-saves predicted category to DB  
- Logs: `[CATEGORY] Auto-saved predicted=TRANSFER for ref=... (user switched intent)`  
- flow_status=null, processes new intent normally

---

## TC5: User switches to new transaction

| # | Role | Message |
|---|------|---------|
| 1-8 | ... | *(reach WAITING_CATEGORY_CONFIRMATION)* |
| 9 | User | chuyển 500k cho Lan |
| 10 | Bot | *(starts new transaction flow)* |

**Expected:**  
- Auto-saves predicted category for previous transaction  
- Starts new TRANSACTION flow with COLLECTING status  
- Previous transaction's category_id updated in DB

---

## TC6: History-based prediction (FAMILY_TRANSFER)

**Precondition:** Previous transfers to Tuấn categorized as FAMILY_TRANSFER

| # | Role | Message |
|---|------|---------|
| 1-7 | ... | *(complete transfer to Tuấn with OTP)* |
| 8 | Bot | ... 📂 Giao dịch này thuộc loại: **Chuyen khoan gia dinh** ... |

**Expected:** LLM uses counterparty history to predict FAMILY_TRANSFER instead of TRANSFER

---

## TC7: No history — defaults to TRANSFER

**User:** `CIF000001` transferring to a new counterparty

| # | Role | Message |
|---|------|---------|
| 1-7 | ... | *(complete transfer to new person with OTP)* |
| 8 | Bot | ... 📂 Giao dịch này thuộc loại: **Chuyen khoan** ... |

**Expected:** No history → LLM defaults to TRANSFER with moderate confidence

---

## TC8: Category only for TRANSACTION (not bill/topup)

**User:** `CIF000002`

| # | Role | Message |
|---|------|---------|
| 1 | User | đóng cước điện thoại trả sau |
| ... | ... | *(complete bill payment with OTP)* |
| N | Bot | Thanh toán thành công. *(no category question)* |

**Expected:** Category prediction NOT triggered for BILL_PAYMENT/TOP_UP flows

---

## Flow State Machine

```
TRANSACTION FLOW:
  ... → WAITING_OTP → EXECUTING → COMPLETED
                                       ↓
                           WAITING_CATEGORY_CONFIRMATION
                                  /    |    \
                                 /     |     \
                        confirm  pick  skip  switch_intent
                           ↓      ↓     ↓         ↓
                      save     save   save      save predicted
                    predicted  chosen predicted  + route new intent
                           \     |     /         ↓
                            \    |    /    CLASSIFY_NEW_INTENT
                             ↓   ↓   ↓
                          flow = null (done)
```

## Key Design Points

1. **Post-execution soft ask** — Not blocking; user can freely switch intent  
2. **lock_level = flexible** — Category confirmation doesn't lock the flow  
3. **Auto-save on abandon** — Predicted value always saved to DB (never lost)  
4. **History-aware** — Uses last 5 transactions to same counterparty for prediction  
5. **Same-group alternatives first** — FAMILY_TRANSFER, RENT shown before FOOD, SHOPPING  
6. **Only for TRANSACTION** — Bill/TopUp already have deterministic categories  
7. **DB update via `transaction_ref`** — Uses `CategoryClassifier.update_category()`
