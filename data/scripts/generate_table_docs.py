"""Generate Markdown + HTML table descriptions from CSV mock data."""

import csv
import json
import os
from datetime import datetime
from html import escape
from pathlib import Path

BASE_DIR = Path(os.path.dirname(__file__)).parent
CSV_DIR = BASE_DIR / "csv"
DOCS_DIR = BASE_DIR / "docs"

TABLE_GROUP = {
    "customers": "Master/reference data",
    "accounts": "Master/reference data",
    "cards": "Master/reference data",
    "beneficiaries": "Master/reference data",
    "merchants": "Master/reference data",
    "billers": "Master/reference data",
    "customer_biller_accounts": "Master/reference data",
    "transaction_categories": "Master/reference data",
    "interest_rates": "Master/reference data",
    "transactions": "Read model / transaction history",
    "action_requests": "Workflow/action store",
    "api_call_logs": "API call log",
    "audit_logs": "Audit log",
    "bills": "Billing workflow",
    "fraud_reports": "Fraud detection / transaction screening",
    "reported_accounts": "Fraud detection / transaction screening",
    "reported_customers": "Fraud detection / transaction screening",
    "fraud_decisions": "Fraud detection / transaction screening",
    "external_bank_accounts": "Master/reference data",
}

TABLE_PURPOSE = {
    "customers": "Luu thong tin khach hang theo CIF de scope du lieu cho cac agent.",
    "accounts": "Luu tai khoan ngan hang cua khach hang, dung cho xem so du va chon tai khoan nguon.",
    "cards": "Luu thong tin the de xu ly khoa/mo khoa/bao mat va xem thong tin the.",
    "beneficiaries": "Luu nguoi nhan da luu cua khach hang de resolve giao dich chuyen tien.",
    "merchants": "Danh muc merchant cho giao dich the va phan tich chi tieu.",
    "billers": "Danh muc nha cung cap hoa don (dien, nuoc, internet, phone).",
    "customer_biller_accounts": "Lien ket khach hang voi ma khach hang tai biller de truy xuat hoa don.",
    "bills": "Luu hoa don theo ky va trang thai thanh toan cho luong bill payment.",
    "interest_rates": "Bang tham chieu lai suat tiet kiem/vay de tu van tai chinh.",
    "transaction_categories": "Danh muc phan loai giao dich cho phan tich va category confirmation.",
    "transactions": "Lich su giao dich/read model cho text2sql, risk va bao cao.",
    "action_requests": "Luu draft va trang thai xu ly cac hanh dong nhay cam cua agent.",
    "api_call_logs": "Luu request/response khi goi external API mock.",
    "audit_logs": "Luu audit trace bat bien cho tung buoc workflow.",
    "fraud_reports": "Luu bao cao lua dao tu nguoi dung.",
    "reported_accounts": "Bang tong hop muc do rui ro theo tai khoan bi bao cao.",
    "reported_customers": "Bang tong hop muc do rui ro theo CIF bi bao cao.",
    "fraud_decisions": "Luu ket qua screening truoc khi chuyen tien.",
    "external_bank_accounts": "Directory tai khoan lien ngan hang de verify nguoi nhan ngoai SHB.",
}

RELATIONSHIPS = {
    "accounts": ["accounts.cif_no -> customers.cif_no"],
    "cards": ["cards.cif_no -> customers.cif_no", "cards.account_no -> accounts.account_no"],
    "beneficiaries": ["beneficiaries.cif_no -> customers.cif_no"],
    "customer_biller_accounts": [
        "customer_biller_accounts.cif_no -> customers.cif_no",
        "customer_biller_accounts.biller_id -> billers.biller_id",
    ],
    "bills": ["bills.biller_code -> billers.biller_code", "bills.customer_bill_code -> customer_biller_accounts.customer_bill_code"],
    "transactions": [
        "transactions.cif_no -> customers.cif_no",
        "transactions.account_no -> accounts.account_no",
        "transactions.card_id -> cards.card_id",
        "transactions.merchant_id -> merchants.merchant_id",
        "transactions.biller_id -> billers.biller_id",
        "transactions.beneficiary_id -> beneficiaries.beneficiary_id",
        "transactions.category_id -> transaction_categories.category_id",
    ],
    "action_requests": ["action_requests.cif_no -> customers.cif_no"],
    "api_call_logs": ["api_call_logs.action_id -> action_requests.action_id"],
    "audit_logs": ["audit_logs.action_id -> action_requests.action_id", "audit_logs.cif_no -> customers.cif_no"],
    "fraud_reports": ["fraud_reports.reporter_cif_no -> customers.cif_no", "fraud_reports.transaction_ref -> transactions.transaction_ref"],
    "reported_customers": ["reported_customers.cif_no -> customers.cif_no"],
    "fraud_decisions": ["fraud_decisions.action_id -> action_requests.action_id"],
}


def read_rows(csv_path: Path):
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        return reader.fieldnames or [], rows


def is_uuid(value: str) -> bool:
    if not value or len(value) != 36:
        return False
    parts = value.split("-")
    if len(parts) != 5:
        return False
    sizes = [8, 4, 4, 4, 12]
    return all(len(part) == size for part, size in zip(parts, sizes))


def is_int(value: str) -> bool:
    try:
        int(value)
        return True
    except ValueError:
        return False


def is_float(value: str) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False


def is_bool(value: str) -> bool:
    return value.lower() in {"true", "false", "0", "1"}


def is_json(value: str) -> bool:
    if not value:
        return False
    if not (value.startswith("{") or value.startswith("[")):
        return False
    try:
        json.loads(value)
        return True
    except json.JSONDecodeError:
        return False


def is_datetime(value: str) -> bool:
    fmts = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]
    for fmt in fmts:
        try:
            datetime.strptime(value, fmt)
            return True
        except ValueError:
            continue
    return False


def infer_type(values):
    non_empty = [v for v in values if v not in ("", None)]
    if not non_empty:
        return "string"

    uniques = sorted(set(non_empty))

    if all(is_uuid(v) for v in non_empty):
        return "UUID string"
    if all(is_bool(v) for v in non_empty):
        return "boolean"
    if all(is_int(v) for v in non_empty):
        return "numeric"
    if all(is_float(v) for v in non_empty):
        return "numeric"
    if all(is_json(v) for v in non_empty):
        return "JSON string"
    if all(is_datetime(v) for v in non_empty):
        if any(len(v) > 10 for v in non_empty):
            return "timestamp string"
        return "date string"
    if len(uniques) <= 12 and all(v.upper() == v for v in uniques if any(ch.isalpha() for ch in v)):
        return "enum string"
    return "string"


def meaning_for_column(col: str) -> str:
    if col.endswith("_id"):
        return "Dinh danh ban ghi"
    if col.endswith("_no"):
        return "Ma/so nghiep vu"
    if col.endswith("_code"):
        return "Ma tham chieu nghiep vu"
    if col.endswith("_at") or col.endswith("_time"):
        return "Moc thoi gian"
    if col in {"status", "risk_level", "risk_tier", "decision"}:
        return "Trang thai/muc do theo workflow"
    if col in {"amount", "balance", "available_balance", "credit_limit", "amount_due", "annual_rate"}:
        return "Gia tri tai chinh"
    if col in {"description", "note", "reason_text", "user_text"}:
        return "Noi dung mo ta"
    return "Truong du lieu nghiep vu"


def key_relationship(table: str, col: str) -> str:
    if col == f"{table[:-1]}_id" or (table.endswith("s") and col == f"{table}_id"):
        return "PK"
    if table == "transactions" and col == "transaction_ref":
        return "Unique"
    if table == "customers" and col == "cif_no":
        return "Unique"
    if table == "accounts" and col == "account_no":
        return "Unique"
    if table == "billers" and col == "biller_code":
        return "Unique"
    rels = RELATIONSHIPS.get(table, [])
    for rel in rels:
        left = rel.split("->")[0].strip()
        if left.endswith(f".{col}"):
            return f"FK -> {rel.split('->')[1].strip()}"
    return "-"


def notes_for_column(col: str) -> str:
    if col in {"api_payload", "resolved_entities", "missing_fields", "request_payload", "response_payload", "event_payload", "reason_codes"}:
        return "JSON payload phuc vu truy vet hoac dieu phoi flow"
    if col == "status":
        return "Gia tri phai khop enum cua workflow hien tai"
    if col in {"is_primary", "is_saved", "requires_confirmation", "requires_otp", "has_evidence"}:
        return "Co/khong theo logic nghiep vu"
    return "-"


def md_table_columns(table: str, fieldnames, rows):
    lines = []
    lines.append("| Column | Type | Meaning | Example Values From Data | Nullable | Key / Relationship | Notes |")
    lines.append("|---|---|---|---|---|---|---|")

    for col in fieldnames:
        values = [r.get(col, "") for r in rows]
        non_empty = [v for v in values if v not in ("", None)]
        inferred = infer_type(values)
        nullable = "Yes" if len(non_empty) != len(values) else "No"
        examples = ", ".join(non_empty[:3]) if non_empty else "-"
        lines.append(
            f"| {col} | {inferred} | {meaning_for_column(col)} | {examples} | {nullable} | {key_relationship(table, col)} | {notes_for_column(col)} |"
        )

    return "\n".join(lines)


def md_enums(fieldnames, rows):
    lines = []
    lines.append("| Column | Value | Meaning | Example Use Case |")
    lines.append("|---|---|---|---|")
    found = False

    for col in fieldnames:
        values = [r.get(col, "") for r in rows]
        uniques = [v for v in sorted(set(values)) if v not in ("", None)]
        if len(uniques) < 2 or len(uniques) > 10:
            continue
        if not any(ch.isalpha() for v in uniques for ch in v):
            continue

        inferred = infer_type(values)
        if inferred != "enum string":
            continue

        found = True
        for val in uniques:
            lines.append(f"| {col} | {val} | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |")

    if not found:
        return "Khong co enum quan trong."
    return "\n".join(lines)


def build_markdown(table: str, fieldnames, rows) -> str:
    group = TABLE_GROUP.get(table, "Operational data")
    purpose = TABLE_PURPOSE.get(table, "Bang du lieu nghiep vu cho banking agent.")
    relationships = RELATIONSHIPS.get(table, [])

    relationship_md = "\n".join(f"- {r}" for r in relationships) if relationships else "- Khong co quan he FK truc tiep."

    md = []
    md.append(f"# {table}")
    md.append("")
    md.append("## 1. Muc dich bang")
    md.append("")
    md.append(purpose)
    md.append("")
    md.append(f"**Nhom:** {group}")
    md.append("")
    md.append("## 2. Ngu canh nghiep vu")
    md.append("")
    md.append("- Bang nay phuc vu luong xu ly cua cac agent trong he thong TrustFlow.")
    md.append("- Du lieu duoc dung de truy van read model, xac thuc thong tin va truy vet audit.")
    md.append("- Day la mock data cho demo, khong phai core ledger van hanh that.")
    md.append("")
    md.append("## 3. Columns")
    md.append("")
    md.append(md_table_columns(table, fieldnames, rows))
    md.append("")
    md.append("## 4. Important Values / Enums")
    md.append("")
    md.append(md_enums(fieldnames, rows))
    md.append("")
    md.append("## 5. Relationships")
    md.append("")
    md.append(relationship_md)
    md.append("")
    md.append("## 6. Simple Usage Examples")
    md.append("")
    md.append("```sql")
    md.append(f"SELECT * FROM {table} LIMIT 5;")
    if "cif_no" in fieldnames:
        md.append(f"SELECT * FROM {table} WHERE cif_no = 'CIF000001' LIMIT 10;")
    md.append("```")
    md.append("")
    return "\n".join(md)


def build_html(table: str, fieldnames, rows) -> str:
    group = TABLE_GROUP.get(table, "Operational data")
    purpose = TABLE_PURPOSE.get(table, "Bang du lieu nghiep vu cho banking agent.")
    relationships = RELATIONSHIPS.get(table, [])

    enum_rows = []
    for col in fieldnames:
        values = [r.get(col, "") for r in rows]
        uniques = [v for v in sorted(set(values)) if v not in ("", None)]
        if infer_type(values) == "enum string" and 2 <= len(uniques) <= 10:
            for val in uniques:
                enum_rows.append((col, val, "Gia tri enum trong du lieu", "Loc/truy van theo trang thai/loai"))

    col_rows = []
    for col in fieldnames:
        values = [r.get(col, "") for r in rows]
        non_empty = [v for v in values if v not in ("", None)]
        inferred = infer_type(values)
        nullable = "Yes" if len(non_empty) != len(values) else "No"
        examples = ", ".join(non_empty[:3]) if non_empty else "-"
        col_rows.append(
            (
                col,
                inferred,
                meaning_for_column(col),
                examples,
                nullable,
                key_relationship(table, col),
                notes_for_column(col),
            )
        )

    relationship_html = "".join(f"<li>{escape(item)}</li>" for item in relationships) or "<li>Khong co quan he FK truc tiep.</li>"

    def render_table(headers, rows_data):
        head = "".join(f"<th>{escape(h)}</th>" for h in headers)
        body = ""
        for row in rows_data:
            body += "<tr>" + "".join(f"<td>{escape(str(cell))}</td>" for cell in row) + "</tr>"
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"

    enum_section = "<p>Khong co enum quan trong.</p>"
    if enum_rows:
        enum_section = render_table(
            ["Column", "Value", "Meaning", "Example Use Case"],
            enum_rows,
        )

    html = f"""<!DOCTYPE html>
<html lang=\"vi\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>{escape(table)}</title>
  <style>
    body {{ font-family: 'Segoe UI', Tahoma, sans-serif; background: #f6f8fb; color: #102027; line-height: 1.6; }}
    .container {{ max-width: 1100px; margin: 24px auto; background: #fff; border-radius: 10px; box-shadow: 0 8px 28px rgba(0,0,0,.08); padding: 28px; }}
    h1 {{ margin-top: 0; color: #0b3c5d; }}
    h2 {{ color: #135d7a; border-bottom: 1px solid #d9e2ec; padding-bottom: 6px; margin-top: 28px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #e9f2f8; }}
    tr:nth-child(even) {{ background: #f8fbfd; }}
    code, pre {{ background: #102a43; color: #f0f4f8; border-radius: 6px; }}
    code {{ padding: 2px 6px; }}
    pre {{ padding: 12px; overflow-x: auto; }}
  </style>
</head>
<body>
<div class=\"container\">
  <h1>{escape(table)}</h1>

  <h2>1. Muc dich bang</h2>
  <p>{escape(purpose)}</p>
  <p><strong>Nhom:</strong> {escape(group)}</p>

  <h2>2. Ngu canh nghiep vu</h2>
  <ul>
    <li>Bang nay phuc vu luong xu ly cua cac agent trong he thong TrustFlow.</li>
    <li>Du lieu duoc dung de truy van read model, xac thuc thong tin va truy vet audit.</li>
    <li>Day la mock data cho demo, khong phai core ledger van hanh that.</li>
  </ul>

  <h2>3. Columns</h2>
  {render_table(["Column", "Type", "Meaning", "Example Values From Data", "Nullable", "Key / Relationship", "Notes"], col_rows)}

  <h2>4. Important Values / Enums</h2>
  {enum_section}

  <h2>5. Relationships</h2>
  <ul>{relationship_html}</ul>

  <h2>6. Simple Usage Examples</h2>
  <pre><code>SELECT * FROM {table} LIMIT 5;{'\nSELECT * FROM ' + table + " WHERE cif_no = 'CIF000001' LIMIT 10;" if 'cif_no' in fieldnames else ''}</code></pre>
</div>
</body>
</html>
"""
    return html


def main():
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    csv_files = sorted(
        p for p in CSV_DIR.glob("*.csv") if p.name.lower() != "readme.csv"
    )

    for csv_file in csv_files:
        table = csv_file.stem
        fieldnames, rows = read_rows(csv_file)
        if not fieldnames:
            continue

        markdown = build_markdown(table, fieldnames, rows)
        html = build_html(table, fieldnames, rows)

        md_path = DOCS_DIR / f"{table}.md"
        html_path = DOCS_DIR / f"{table}.html"

        with open(md_path, "w", encoding="utf-8") as f:
            f.write(markdown)

        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)

        print(f"written: {md_path.name}, {html_path.name}")


if __name__ == "__main__":
    main()
