# TrustFlow Agent Flow Test Cases

## 1. Scope

This file defines integration-style conversation test cases for these agent flows:
- TRANSACTION
- BILL_PAYMENT
- TOP_UP
- CARD_OPERATION
- ACCOUNT_OPERATION
- FRAUD_REPORT
- DATA_QUERY
- FINANCE_ADVISOR
- FINANCE_PLANNING
- QA

The test cases are aligned with regenerated CSV data in `data/csv` and current routing/flow behavior.

## 2. Shared Fixtures (from regenerated data)

- Customer A: `cif_no = CIF000001`
- Customer A payment accounts:
  - Primary: `31243292127` (ACTIVE, is_primary=True)
  - Secondary: `527177449058` (ACTIVE)
- Customer A saved bill account:
  - `customer_bill_code = PD915929556`
  - Linked biller: `EVN_DANANG`
  - Latest unpaid bill amount: `2,364,471`
- Card customer sample:
  - `cif_no = CIF000013`
  - `card_id = 5943f137-22d2-5650-b80e-98c1cfb2031c` (ACTIVE)
- Fraud sample reported account:
  - `account_no = 26940539672`, `bank_code = STB`, `risk_level = CRITICAL`
- Interest rate sample:
  - `SAVINGS_ONLINE_12M`, annual_rate `5.0`

## 3. Transaction Flow (TRANSACTION)

### TX-01 Basic transfer by saved recipient
- User turns:
  1. "Chuyen 2 trieu cho Pham Van Son"
  2. "ok"
  3. "123456"
- Expected:
  - Router enters `COLLECTING` -> `WAITING_RECIPIENT_CONFIRMATION` (if multi-candidate) or `WAITING_DRAFT_CONFIRMATION`.
  - After confirm: move to `WAITING_OTP`.
  - OTP `123456` executes transfer and closes flow.
- Pass criteria:
  - New successful transaction row exists.
  - Audit event contains transaction executed.

### TX-02 Modify draft during confirmation
- User turns:
  1. "Chuyen 5 trieu cho nguoi giao dich gan nhat"
  2. "doi thanh 3 trieu"
  3. "xac nhan"
  4. "123456"
- Expected:
  - At confirmation state, message 2 is classified as `MODIFY_DRAFT`.
  - Amount updated to 3,000,000 before OTP.
- Pass criteria:
  - Executed transaction amount is 3,000,000, not 5,000,000.

### TX-03 Blocked by critical fraud recipient
- User turns:
  1. "Chuyen 1 trieu den tai khoan 26940539672 STB"
- Expected:
  - Recipient verification succeeds.
  - Guardrail detects `CRITICAL` risk and blocks execution (no OTP phase).
- Pass criteria:
  - No outgoing transaction inserted.
  - User receives explicit block warning.

## 4. Bill Payment Flow (BILL_PAYMENT)

### BILL-01 Pay specific electricity bill
- User turns:
  1. "Thanh toan hoa don dien EVN"
  2. "1" (if biller/bill list shown)
  3. "dong y"
  4. "123456"
- Expected:
  - Flow states: `COLLECTING` -> `WAITING_BILLER_SELECTION` -> `WAITING_BILL_CONFIRMATION` -> `WAITING_OTP`.
- Pass criteria:
  - Bill status changes from `UNPAID` to `PAID`.
  - A BILL_PAYMENT transaction is created.

### BILL-02 Pay all unpaid bills
- User turns:
  1. "Thanh toan tat ca hoa don"
  2. "xac nhan"
  3. "123456"
- Expected:
  - Extractor returns `pay_all = true`.
  - System builds batch confirmation summary.
- Pass criteria:
  - All currently due unpaid bills for user are paid.

### BILL-03 Ambiguous bill type
- User turns:
  1. "Thanh toan hoa don"
- Expected:
  - Extractor keeps `biller_type = null`.
  - System asks clarification or selection list.
- Pass criteria:
  - No execution happens before explicit bill selection/confirmation.

## 5. Top-Up Flow (TOP_UP)

### TOPUP-01 Phone top-up complete flow
- User turns:
  1. "Nap 50k cho 0986123456"
  2. "ok"
  3. "123456"
- Expected:
  - Extract `topup_target`, provider, amount.
  - Move `WAITING_TOPUP_CONFIRMATION` -> `WAITING_OTP`.
- Pass criteria:
  - PHONE_TOPUP transaction created.
  - Source balance reduced by 50,000.

### TOPUP-02 Missing amount then provide amount
- User turns:
  1. "Nap dien thoai cho 0912345678"
  2. "100 nghin"
  3. "dong y"
  4. "123456"
- Expected:
  - First turn asks for missing amount.
  - Amount normalization to 100,000.
- Pass criteria:
  - Top-up success with exact amount 100,000.

### TOPUP-03 Over limit rejection
- User turns:
  1. "Nap 2 trieu cho 0986123456"
  2. "xac nhan"
  3. "123456"
- Expected:
  - TopUpExecutor rejects because phone top-up max is 500,000.
- Pass criteria:
  - No debit transaction committed.
  - User receives `AMOUNT_TOO_HIGH` style message.

## 6. Card Operation Flow (CARD_OPERATION)

### CARD-01 View card info
- User turns:
  1. "Xem thong tin the cua toi"
- Expected:
  - Operation `VIEW_CARD_INFO`.
  - If multiple cards, system returns list or asks disambiguation.
- Pass criteria:
  - Response includes card status/type/network data.

### CARD-02 Lock card and then unlock
- User turns:
  1. "Khoa the"
  2. "xac nhan"
  3. "Mo khoa the vua khoa"
  4. "xac nhan"
  5. "123456"
- Expected:
  - Lock operation sets status to `TEMP_LOCKED`.
  - Unlock requires card in `TEMP_LOCKED` and usually OTP path.
- Pass criteria:
  - Card status returns to `ACTIVE` after unlock.

### CARD-03 Report lost card
- User turns:
  1. "Bao mat the"
  2. "dong y"
- Expected:
  - Operation `REPORT_LOST`.
  - Card status becomes `LOST` permanently.
- Pass criteria:
  - Repeated unlock attempt is rejected for lost card.

## 7. Account Operation Flow (ACCOUNT_OPERATION)

### ACC-01 View account information
- User turns:
  1. "Xem danh sach tai khoan cua toi"
- Expected:
  - Agent calls `get_user_accounts` and returns info directly.
- Pass criteria:
  - Response includes account_no, type, balances, status, primary flag.

### ACC-02 Open new account product
- User turns:
  1. "Mo them tai khoan moi"
  2. "Chon CURRENT_VND"
  3. "xac nhan"
- Expected:
  - Agent lists account products first if not specified.
  - Draft created for OPEN_ACCOUNT.
- Pass criteria:
  - Draft has product_code and confirmation prompt.

### ACC-03 Close account not allowed if primary/balance > 0
- User turns:
  1. "Dong tai khoan 31243292127"
- Expected:
  - Agent checks account detail.
  - Reject close when account is primary or balance not zero.
- Pass criteria:
  - Response explains close constraint reason.

## 8. Fraud Report Flow (FRAUD_REPORT)

### FRAUD-01 Check account risk
- User turns:
  1. "Tai khoan 26940539672 STB co an toan khong?"
- Expected:
  - Must call risk check tool.
  - Return warning due CRITICAL risk.
- Pass criteria:
  - JSON response operation = CHECK_ACCOUNT_RISK.

### FRAUD-02 Report fraud with full payload in one turn
- User turns:
  1. "Toi muon bao cao lua dao: TK 26940539672 STB, mat 3500000, lien he qua Zalo, ly do gia danh cong an, hau qua mat tien, co bang chung"
- Expected:
  - If required fields complete, save report immediately.
- Pass criteria:
  - New row in `fraud_reports`.
  - Aggregation in `reported_accounts` updated.

### FRAUD-03 Multi-turn missing fields collection
- User turns:
  1. "Toi bi lua dao"
  2. Provide partial details
  3. Provide remaining details
- Expected:
  - First response asks all required items together.
  - Follow-up asks one missing field at a time.
- Pass criteria:
  - Report saved only after required fields are complete.

## 9. Data Query Flow (DATA_QUERY)

### DQ-01 Balance and account list question
- User turns:
  1. "Tong so du cac tai khoan thanh toan cua toi la bao nhieu?"
- Expected:
  - Call text2sql service with user-scoped question (`cif_no`).
  - Return Vietnamese summary.
- Pass criteria:
  - Response status `info_response` and row_count > 0.

### DQ-02 Empty result handling
- User turns:
  1. "Cho toi danh sach giao dich thu nhap tu nam 2010"
- Expected:
  - If query result empty, summarize as no matching data.
- Pass criteria:
  - User gets graceful empty-data message.

### DQ-03 Clarification path
- User turns:
  1. "Thong ke cho toi"
- Expected:
  - text2sql may return `needs_clarification`.
- Pass criteria:
  - Assistant returns clarification questions, no fabricated metrics.

## 10. Finance Advisor Flow (FINANCE_ADVISOR)

### FA-01 Spending analysis by category
- User turns:
  1. "Phan tich chi tieu thang nay cua toi"
- Expected:
  - Agent uses finance tools and may return chart metadata in `visualizations`.
- Pass criteria:
  - Narrative and visualization totals are consistent.

### FA-02 Compare this month vs previous month
- User turns:
  1. "So sanh chi tieu thang nay voi thang truoc"
- Expected:
  - Grouped comparison summary with delta and top increase/decrease.
- Pass criteria:
  - Response includes period totals and signed delta.

### FA-03 Follow-up uses memory
- User turns:
  1. "Muc chi tieu lon nhat la gi?"
  2. "Vay neu cat bot 20% thi sao?"
- Expected:
  - Domain memory reused to avoid unnecessary recomputation when possible.
- Pass criteria:
  - Follow-up answer remains context-aware and consistent.

## 11. Finance Planning Flow (FINANCE_PLANNING)

### FP-01 User provides salary day
- User turns:
  1. "Lap ke hoach chi tieu den ngay nhan luong 25"
- Expected:
  - Extract salary_day=25.
  - Return daily/weekly budget + essential/flexible split.
- Pass criteria:
  - Data payload has `salary_day`, `days_until_salary`, `daily_budget`.

### FP-02 Missing salary day then ask clarification
- User turns:
  1. "Toi muon song den luong"
- Expected:
  - If cannot infer salary day confidently, ask user for salary day.
- Pass criteria:
  - Response asks explicit 1-31 salary day question.

### FP-03 Salary day inferred from history
- User turns:
  1. "Tu van chia chi tieu den ky luong toi"
- Expected:
  - Agent attempts salary day inference from incoming salary-like transactions.
- Pass criteria:
  - If inference confidence >= threshold, plan is returned without extra question.

## 12. QA Flow (QA)

### QA-01 Product policy question
- User turns:
  1. "Lai suat tiet kiem online 12 thang la bao nhieu?"
- Expected:
  - QA tool queries LightRAG and answers in Vietnamese.
- Pass criteria:
  - Answer is concise and policy-focused, no internal-system mention.

### QA-02 Multi-part policy question
- User turns:
  1. "Mo the tin dung can giay to gi va phi thuong nien bao nhieu?"
- Expected:
  - Agent may run multiple retrieval calls then synthesize.
- Pass criteria:
  - Response covers both documents and fee aspects.

### QA-03 Social/ambiguous small-talk handling
- User turns:
  1. "Hello"
- Expected:
  - No forced retrieval needed.
  - Reply naturally and politely in Vietnamese.
- Pass criteria:
  - Simple greeting response, no hallucinated policy details.

## 13. Cross-Flow Router Regression Cases

### ROUTE-01 Interrupt during WAITING_OTP
- Steps:
  1. Start transfer and reach OTP step.
  2. Send unrelated intent: "Cho toi xem thong tin the".
- Expected:
  - Router returns `INTERRUPT_LOCKED_FLOW` behavior (or asks cancel/finish current OTP flow first).

### ROUTE-02 Cancel in limited confirmation state
- Steps:
  1. Start bill payment and reach confirmation.
  2. Send "huy".
- Expected:
  - Active flow cancelled cleanly.
  - No side effects in transactions/bills.

### ROUTE-03 Pending question numeric answer
- Steps:
  1. Trigger recipient/biller candidate list.
  2. Reply "2".
- Expected:
  - Router maps numeric input to `ANSWER_PENDING_QUESTION` with chosen option.

## 14. Suggested Automation Tags

- `@critical`: TX-03, BILL-01, TOPUP-03, CARD-03, FRAUD-02, ROUTE-01
- `@smoke`: TX-01, BILL-03, TOPUP-01, ACC-01, QA-01
- `@regression`: all cases above
