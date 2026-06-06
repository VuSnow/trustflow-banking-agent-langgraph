# Bill Payment — Test Cases

> User test: `CIF000002` (có 1 biller điện EVN_SOUTH, 2 biller internet VNPT, 1 biller phone VNPT)  
> User test: `CIF000001` (có 3 biller điện → trigger selection)  
> Mock OTP: `123456`

---

## TC1: Single biller, single unpaid bill → Direct confirmation

**User:** `CIF000002`

| # | Role | Message |
|---|------|---------|
| 1 | User | thanh toán hóa đơn điện |
| 2 | Bot | Hóa đơn điện cần thanh toán:<br>• Nhà cung cấp: EVN Mien Nam<br>• Mã khách hàng: PD989388663<br>• Kỳ thanh toán: 2026-05<br>• Số tiền: 623,000 VND<br>• Hạn thanh toán: 2026-06-10<br><br>Bạn xác nhận thanh toán không? |

**Expected:** `flow_status=WAITING_BILL_CONFIRMATION`, `auth_required=confirm`

---

## TC2: Confirm → OTP → Execute

Tiếp TC1:

| # | Role | Message |
|---|------|---------|
| 3 | User | ok |
| 4 | Bot | Tôi đã gửi mã OTP đến số điện thoại đăng ký của bạn.<br>Vui lòng nhập OTP để hoàn tất thanh toán.<br><br>Thanh toán: EVN Mien Nam — 623,000 VND. |
| 5 | User | 123456 |
| 6 | Bot | Thanh toán thành công.<br><br>Mã giao dịch: BILL...<br>Thời gian: ...<br>Nhà cung cấp: EVN Mien Nam<br>Mã khách hàng: PD989388663<br>Kỳ: 2026-05<br>Số tiền: 623,000 VND<br>Số dư còn lại: ... VND |

**Expected step 4:** `flow_status=WAITING_OTP`, `auth_required=otp`  
**Expected step 6:** `flow_status=null`, `status=completed`, `data.executed=true`

---

## TC3: Multiple billers → Selection

**User:** `CIF000001`

| # | Role | Message |
|---|------|---------|
| 1 | User | thanh toán hóa đơn điện |
| 2 | Bot | Bạn có 3 tài khoản điện đã đăng ký:<br><br>1. EVN Ha Noi — PD111222333 (Nha bo me)<br>2. EVN Mien Nam — PD444555666 (Cong ty)<br>3. EVN Mien Trung — PD867472238 (Nha Ha Noi)<br><br>Bạn muốn thanh toán cho tài khoản nào? (Nhập số thứ tự) |

**Expected:** `flow_status=COLLECTING`, pending_question.slot=`biller_choice`

---

## TC4: Biller selection → Bill confirmation

Tiếp TC3:

| # | Role | Message |
|---|------|---------|
| 3 | User | 1 |
| 4 | Bot | Hóa đơn điện cần thanh toán:<br>• Nhà cung cấp: EVN Ha Noi<br>• Mã khách hàng: PD111222333<br>• ...<br><br>Bạn xác nhận thanh toán không? |

**Expected:** `flow_status=WAITING_BILL_CONFIRMATION`  
*(Nếu không có hóa đơn UNPAID → "Không có hóa đơn điện chưa thanh toán cho mã ...")*

---

## TC5: Multiple internet billers → Selection

**User:** `CIF000002`

| # | Role | Message |
|---|------|---------|
| 1 | User | đóng tiền internet |
| 2 | Bot | Bạn có 2 tài khoản internet đã đăng ký:<br><br>1. VNPT Internet Ha Noi — PI543340540 (Wifi nha)<br>2. VNPT Internet HCM — PI945489578 (Internet nha)<br><br>Bạn muốn thanh toán cho tài khoản nào? (Nhập số thứ tự) |

**Expected:** `flow_status=COLLECTING`, pending_question.expected_type=`recipient_choice`

---

## TC6: Alias filter → Direct match

**User:** `CIF000001`

| # | Role | Message |
|---|------|---------|
| 1 | User | thanh toán hóa đơn điện nhà Hà Nội |
| 2 | Bot | *(Nếu có bill UNPAID)*: Hóa đơn điện cần thanh toán... Bạn xác nhận?<br>*(Nếu không có bill)*: Không có hóa đơn điện chưa thanh toán. |

**Expected:** Alias "Nha Ha Noi" matched → PD867472238 (EVN Mien Trung). Skips selection.

---

## TC7: Pay all bills

**User:** `CIF000002`

| # | Role | Message |
|---|------|---------|
| 1 | User | thanh toán tất cả hóa đơn |
| 2 | Bot | Bạn có N hóa đơn chưa thanh toán:<br><br>1. VNPT Internet HCM — kỳ 2026-05 — 220,000 VND (hạn 2026-06-15)<br>2. VNPT Dien thoai tra sau — kỳ 2026-05 — 185,000 VND (hạn 2026-06-20)<br><br>Tổng cộng: 405,000 VND<br><br>Bạn muốn thanh toán tất cả không? |
| 3 | User | xác nhận |
| 4 | Bot | OTP đã gửi... Thanh toán: ... — 405,000 VND. |
| 5 | User | 123456 |
| 6 | Bot | Thanh toán thành công. Mã giao dịch: BILL... |

**Expected step 2:** `flow_status=WAITING_BILL_CONFIRMATION`, shows total  
**Expected step 6:** `status=completed`

---

## TC8: Phone postpaid bill

**User:** `CIF000002`

| # | Role | Message |
|---|------|---------|
| 1 | User | đóng cước điện thoại trả sau |
| 2 | Bot | Hóa đơn điện thoại trả sau cần thanh toán:<br>• Nhà cung cấp: VNPT Dien thoai tra sau<br>• Mã khách hàng: PP986082452<br>• Kỳ thanh toán: 2026-05<br>• Số tiền: 185,000 VND<br>• Hạn thanh toán: 2026-06-20<br><br>Bạn xác nhận thanh toán không? |

**Expected:** `flow_status=WAITING_BILL_CONFIRMATION`, biller_type=`PHONE_POSTPAID`

---

## TC9: Cancel during confirmation

| # | Role | Message |
|---|------|---------|
| 1 | User | thanh toán hóa đơn điện |
| 2 | Bot | *(bill confirmation)* |
| 3 | User | hủy |
| 4 | Bot | Đã hủy giao dịch. |

**Expected step 4:** `flow_status=null`, flow cleared

---

## TC10: Wrong OTP

| # | Role | Message |
|---|------|---------|
| 1-4 | ... | *(reach WAITING_OTP)* |
| 5 | User | 111111 |
| 6 | Bot | Mã OTP không đúng. Còn 2 lần thử. Vui lòng nhập lại. |

**Expected:** `flow_status=WAITING_OTP` (still active)

---

## TC11: No registered biller

**User:** Một user không có biller đăng ký (hoặc filter loại không có)

| # | Role | Message |
|---|------|---------|
| 1 | User | thanh toán hóa đơn nước |
| 2 | Bot | Bạn chưa đăng ký tài khoản thanh toán nước nào. |

**Expected:** `flow_status=COLLECTING`, informational message

---

## TC12: Provider name filter

**User:** `CIF000002`

| # | Role | Message |
|---|------|---------|
| 1 | User | đóng tiền internet VNPT |
| 2 | Bot | *(nếu 1 match)* Bill confirmation<br>*(nếu nhiều match)* Selection list |

**Expected:** Filters by biller_name_hint="VNPT" → chỉ show VNPT billers

---

## Flow State Machine

```
COLLECTING ──────→ WAITING_BILL_CONFIRMATION ──→ WAITING_OTP ──→ EXECUTING ──→ COMPLETED
    │                        │                        │
    │ (biller selection)     │ (cancel)               │ (cancel/expired)
    └──── COLLECTING         └──── CANCELLED          └──── CANCELLED
```

## Key Design Points

1. **Extractor chỉ extract**: biller_type, alias_hint, biller_name_hint, pay_all
2. **BillResolver** (SQL): tìm registered billers → lookup unpaid bills
3. **Orchestrator decides**: single/multi biller → selection or direct confirm
4. **OTP hash**: `sha256(bill_id:amount:customer_bill_code)` — prevents tampering
5. **Executor**: `BillPaymentExecutor` — debit account, mark bill PAID, insert transaction
