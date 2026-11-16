"""
text2sql_module.py

Turns a natural-language question into ONE read-only SQLite SELECT query, runs it safely
and returns (columns, rows). run_query() is the only function the rest of the project uses.
"""
import logging
import os
import re
import sqlite3
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
log = logging.getLogger("text2sql")

MODEL = os.getenv("SQL_MODEL", "gpt-4o-mini")
DB_PATH = Path(__file__).resolve().parent / "qistwalay_eligibility.db"
QUERY_TIMEOUT_SECONDS = 5
MAX_ROWS = 500

def is_rejected_sample_list_question(question):
    """Match natural English and Roman Urdu requests to list rejected sample applicants."""
    return bool(
        _REJECTION_TERMS.search(question)
        and _INSTALLMENT_TERMS.search(question)
        and (
            _REJECTED_LIST_TERMS.search(question)
            or _REJECTED_SAMPLE_LIST_LIMIT.search(question)
        )
    )

def is_sample_rejection_basis_question(question):
    """Match questions asking what recorded factors appear in rejected sample records."""
    return bool(
        _SAMPLE_BASIS_TERMS.search(question)
        and (
            _INSTALLMENT_TERMS.search(question)
            or _REJECTION_TERMS.search(question)
        )
    )

def is_applicant_rejection_basis_question(question):
    """Match rejection-basis questions tied to one applicant ID."""
    return bool(
        _APPLICANT_ID.search(question)
        and is_sample_rejection_basis_question(question)
    )

def is_bankruptcy_eligibility_question(question):
    return bool(_BANKRUPTCY_TERMS.search(question))

# --- NAYA FIX: Paradoxical / Sab kuch hone ke baad bhi reject ---
def is_paradoxical_rejected_question(question):
    """Match 'sab kuch hone ke baad bhi reject' type questions."""
    q = question or ""
    return bool(
        re.search(r"\b(?:sab\s+kuch|everything|phir\s+bhi|fir\s+bhi|hone\s+ke\s+baad|baad\s+bhi)\b", q, re.IGNORECASE)
        and re.search(r"\b(?:reject\w*|cannot|can\s+not|can't|nahi|nahin|nhi|na|not\s+eligible)\b", q, re.IGNORECASE)
    )

def get_paradoxical_rejected_records():
    """Only Rejected rows that look fine on surface: income >= 50000, late=0, bounced=0, not blacklisted, no bankruptcy.
    Returns their hidden factors + filtered recorded reasons, so pipeline can explain why they were rejected."""
    query = (
        "SELECT applicant_id, full_name, monthly_net_income_pkr, "
        "avg_monthly_balance_pkr, active_loans_count, late_payments_12m, "
        "bounced_cheques_12m, bureau_status, bankruptcy_flag, eligibility_status, "
        "income_verified, months_in_current_job, debt_to_income_ratio, "
        "monthly_debt_obligation_pkr, affordability_headroom_pkr, "
        "previous_installment_defaults, decision_reason "
        "FROM applicants WHERE eligibility_status = 'Rejected' "
        "AND monthly_net_income_pkr >= 50000 "
        "AND late_payments_12m = 0 AND bounced_cheques_12m = 0 "
        "AND LOWER(bureau_status) != 'blacklisted' "
        "AND LOWER(bankruptcy_flag) = 'no' "
        "ORDER BY monthly_net_income_pkr DESC LIMIT 5"
    )
    columns, rows = _execute(query)
    records = []
    for row in rows:
        record = dict(zip(columns, row))
        record["recorded_reasons"] = _safe_decision_reasons(record.pop("decision_reason"))
        records.append(record)
    return records

_TOP_SAMPLE_ELIGIBILITY = re.compile(
    r"\btop\s+(?P<limit>\d+)\s+(?:(?:eligib\w*|qualif\w*)\s+)?(?:(?:applicant|customer)\s+)?"
    r"(?:names|people|persons?|applicants|customers|naam)\b"
    r".{0,120}\b(?:eligib\w*|qualif\w*|installments?|instalments?|financ\w*|naam)\b",
    re.IGNORECASE,
)
_REJECTED_SAMPLE_LIST_LIMIT = re.compile(
    r"\b(?P<limit>\d+)\s+(?:sample\s+)?(?:applicants?|people|persons?)\b",
    re.IGNORECASE,
)
_REJECTION_TERMS = re.compile(
    r"\b(?:cannot|can\s+not|can't|cant|unable|nahi|nahin|nhi|ni|na|reject\w*|"
    r"denied|declin\w*|refus\w*|"
    r"not\s+eligible)\b",
    re.IGNORECASE,
)
_INSTALLMENT_TERMS = re.compile(
    r"\b(?:installments?|instalments?|qist\w*|kist\w*)\b",
    re.IGNORECASE,
)
_REJECTED_LIST_TERMS = re.compile(
    r"\b(?:names?|who|which|kon|kaun|koun|list|show|give|tell|find|batao|btao|bta|"
    r"unka|unke|onka|onke)\b",
    re.IGNORECASE,
)
_SAMPLE_BASIS_TERMS = re.compile(
    r"\b(?:basis|bunyaad|bunyad|wajah|reason|why|kyun|decide\w*|decision|criteria)\b",
    re.IGNORECASE,
)
_APPLICANT_ID = re.compile(r"\bAPP-\d{4}-\d{4}\b", re.IGNORECASE)
_BANKRUPTCY_TERMS = re.compile(
    r"\b(?:bankrupt\w*|bankkrupt\w*|bankruptcy|bankrupcy|bankrupty)\b",
    re.IGNORECASE,
)
_SAMPLE_FACTOR_ELIGIBILITY = re.compile(
    r"\b(?:blacklist(?:ed)?|no\s+(?:income|source\s+of\s+income)|without\s+(?:any\s+)?income|"
    r"(?:does\s+not|doesn't|do\s+not|don't|has\s+no)\s+(?:have\s+)?(?:any\s+)?income(?:\s+source)?|"
    r"unemployed|never\s+(?:paid|had|taken)\s+(?:any\s+)?installments?|"
    r"no\s+(?:previous|prior|past)\s+installment\s+plans?|"
    r"(?:never|no)\s+(?:made|had|paid)\s+(?:any\s+)?(?:previous\s+|prior\s+)?installment\s+payments?)\b",
    re.IGNORECASE,
)

SCHEMA = """
Table: applicants (100 rows, one row per application; all people are made up)
Columns:
applicant_id, full_name, gender, date_of_birth, age, cnic, marital_status, dependents,
education_level, city, province, residence_type, years_at_current_address, mobile_number,
email, employment_type, employer_name, job_title, industry, months_in_current_job,
total_work_experience_years, monthly_gross_income_pkr, monthly_net_income_pkr,
other_monthly_income_pkr, income_verified, bank_name, bank_account_age_months,
avg_monthly_balance_pkr, salary_credited_to_bank, active_loans_count, total_outstanding_debt_pkr,
monthly_debt_obligation_pkr, debt_to_income_ratio, credit_cards_count,
late_payments_12m, max_dpd_24m,
defaults_lifetime, bounced_cheques_12m, utility_bill_payment_behavior,
bureau_status, bankruptcy_flag, previous_installment_plans,
previous_installment_defaults, existing_customer, guarantor_available,
requested_appliance_category, requested_appliance_model,
appliance_price_pkr, requested_tenure_months, requested_downpayment_pct,
application_date, affordability_headroom_pkr, max_financing_limit_pkr, risk_tier,
eligibility_status, approved_downpayment_pct, approved_tenure_months,
annual_markup_pct, monthly_installment_pkr, total_payable_pkr

Table: appliance_categories
Columns: category (TEXT, PRIMARY KEY), price_min, price_max, max_tenure_months

Relation: applicants.requested_appliance_category = appliance_categories.category

Stored values (use them exactly):
- gender: Female, Male
- marital_status: Divorced, Married, Single, Widowed
- education_level: Bachelors, Diploma, Intermediate, MPhil/PhD, Masters, Matric
- province: Balochistan, Islamabad Capital Territory, Khyber Pakhtunkhwa, Punjab, Sindh
- city: Abbottabad, Bahawalpur, Faisalabad, Gujranwala, Hyderabad, Islamabad, Karachi, Lahore, Multan, Peshawar, Quetta, Rawalpindi, Sargodha, Sialkot
- residence_type: Family-Owned, Owned, Rented
- employment_type: Business Owner, Contract, Freelancer, Government Employee, Retired, Salaried, Self-Employed, Student, Unemployed
- income_verified: No, Partial, Yes
- salary_credited_to_bank, bankruptcy_flag, existing_customer, guarantor_available: Yes, No
- bureau_status: Clear, Under Observation, Blacklisted
- utility_bill_payment_behavior: On-time, Occasionally Late, Frequently Late
- risk_tier: A, B, C, D, E
- eligibility_status: Approved, Approved with Conditions, Referred for Manual Review, Rejected
- requested_appliance_category (applicants): Refrigerator, Air Conditioner, Washing Machine, LED / Smart TV, Microwave Oven, Water Dispenser, Deep Freezer
- appliance_categories.category has 15 values: Refrigerator, Air Conditioner, Washing Machine, LED / Smart TV, Microwave Oven, Water Dispenser, Deep Freezer, Kitchen Appliances, Geyser, Fans, Air Cooler, Air Purifier, Room Heaters, Mobile Phones, Motorcycle. Only the first 7 have applicants.

Units and meaning:
- Columns ending in _pkr are rupees. Columns ending in _pct are percent numbers (10 means 10 percent).
- debt_to_income_ratio is a fraction (0.206 means 20.6 percent).
- date_of_birth and application_date are text in YYYY-MM-DD format. Applications are from May to September 2026.
- For Rejected applicants approved_downpayment_pct, approved_tenure_months, annual_markup_pct, monthly_installment_pkr and total_payable_pkr are empty (NULL), and max_financing_limit_pkr is 0.
- max_tenure_months in appliance_categories can be NULL: never guess a value.
"""

RULES = """
Rules:
- Return ONLY one SQLite SELECT query: no explanation, no markdown fences, no semicolon.
- Read-only: never write DROP, DELETE, UPDATE, INSERT or anything except SELECT.
- Only the two tables above exist. If the question cannot be answered from them (product specifications or the price of one product, policies, documents, delivery, deals, the website, or the general eligibility criteria and rules of Qistwalay), return exactly: SELECT 'NOT_IN_DATABASE' AS note
- The applicant rows are sample CSV records, not Qistwalay policy. For a named applicant or applicant ID, report only that row's stored facts and recorded decision/reason; do not make a new approval decision. For hypothetical factor questions, only summarize matching sample records and their recorded outcomes; never infer or promise a real person's eligibility.
- For eligibility explanations, use only the stored risk_tier and eligibility_status plus the available income/bank, DTI/loans, and payment-history fields. Never derive or override the stored tier/status. If they appear inconsistent, report both stored values as-is.
- The configured bankruptcy rule is an explicit exception: bankruptcy_flag = 'Yes' means Rejected regardless of income and must never appear in an eligible-applicant list. If the stored eligibility_status conflicts, report the stored status separately and explain that the configured bankruptcy rule still rejects the application.
- For a request to list people who cannot get installments and their factors, select only rows with stored eligibility_status = 'Rejected'. Return full_name, monthly_net_income_pkr, avg_monthly_balance_pkr, active_loans_count, late_payments_12m, bounced_cheques_12m, bureau_status, bankruptcy_flag, and eligibility_status. Do not return city or risk_tier.
- Do not use excluded fields or raw decision-reason text. If a request cannot be answered from the available columns, return exactly: SELECT 'NOT_IN_DATABASE' AS note. For a mixed request, answer only its supported parts.
- Never use applicants' requested product fields or appliance_categories for Qistwalay product/catalog facts. Product categories, prices, plans, availability, and specifications must come from RAG or return NOT_IN_DATABASE.
- For a request for the top N sample applicants described as eligible or able to get installments, include only stored eligibility_status values 'Approved' or 'Approved with Conditions'; exclude Rejected, bankruptcy_flag = 'Yes', and bureau_status = 'Blacklisted'. Return only full_name, monthly_net_income_pkr, avg_monthly_balance_pkr, active_loans_count, late_payments_12m, bounced_cheques_12m, bureau_status, bankruptcy_flag, and eligibility_status; sort by monthly_net_income_pkr DESC and use LIMIT N. Do not infer a salary threshold or imply approval for any product.
- For a hypothetical installment question comparing sample cases by a factor, return only aggregate counts by recorded eligibility_status for matching rows, without applicant names or any product columns. Match blacklisted using bureau_status = 'Blacklisted'; no income using monthly gross and net income both zero and employment_type = 'Unemployed'; no previous installment plan history using previous_installment_plans = 0. Clearly, the latter field records prior plan count, not a payment ledger.
- Never use SELECT *. Use the exact column names above.
- Compare text case-insensitively: LOWER(column) = LOWER('value') or LIKE. Map everyday words to stored values: govt or government -> 'Government Employee'; business or businessman -> 'Business Owner'; self employed -> 'Self-Employed'; job or employee -> 'Salaried'; KPK -> 'Khyber Pakhtunkhwa'; on time -> 'On-time'; mphil or phd -> 'MPhil/PhD'; blacklisted -> bureau_status 'Blacklisted'; AC -> 'Air Conditioner'; fridge -> 'Refrigerator'; TV or LED -> 'LED / Smart TV'; freezer -> 'Deep Freezer'; dispenser -> 'Water Dispenser'; microwave -> 'Microwave Oven'.
- PERSON LOOKUP: split the name into words and require every word, in any order: LOWER(full_name) LIKE '%yasir%' AND LOWER(full_name) LIKE '%chaudhry%'. With only a first name, return everyone with that name. If a city is named add AND LOWER(city) = 'lahore'. An applicant ID may be written as APP-2026-1016, 1016 or 'applicant 1016': use applicant_id = 'APP-2026-1016'.
- In a person lookup ALWAYS select applicant_id, full_name, city, age, employment_type and requested_appliance_category, plus what the question needs:
    - decision, status, why, reason: eligibility_status, risk_tier, max_financing_limit_pkr, monthly_gross_income_pkr, monthly_net_income_pkr, income_verified, months_in_current_job, salary_credited_to_bank, avg_monthly_balance_pkr, debt_to_income_ratio, active_loans_count, late_payments_12m, bounced_cheques_12m, bureau_status, bankruptcy_flag
    - approved plan, installment, down payment, tenure, markup, total: approved_downpayment_pct, approved_tenure_months, annual_markup_pct, monthly_installment_pkr, total_payable_pkr
    - what the person asked for: requested_appliance_model, appliance_price_pkr, requested_tenure_months, requested_downpayment_pct
    - income, job, bank: employer_name, job_title, industry, monthly_gross_income_pkr, monthly_net_income_pkr, other_monthly_income_pkr, income_verified, bank_name
    - income and bank status: monthly_gross_income_pkr, monthly_net_income_pkr, income_verified, months_in_current_job, salary_credited_to_bank, avg_monthly_balance_pkr
    - debt: debt_to_income_ratio, active_loans_count
    - payment history: late_payments_12m, bounced_cheques_12m, bureau_status, bankruptcy_flag
    - who is, tell me about: gender, province, marital_status, job_title, risk_tier, eligibility_status
- Stored eligibility_status must be reported exactly. For requests using "eligible" or "can take installments", include both 'Approved' and 'Approved with Conditions'; never include Rejected rows.
- Percentages: SQLite divides whole numbers without decimals, so use 100.0 * and ROUND to 1 decimal. The denominator is the group the question names: for 'Karachi mein approved ka percentage' use 100.0 * SUM(CASE WHEN eligibility_status = 'Approved' THEN 1 ELSE 0 END) / COUNT(*) WHERE LOWER(city) = 'karachi'. Use all applicants as the denominator only when no group is named. Also select the count and the group size, so the answer can say '3 of 13'.
- Months: strftime('%Y-%m', application_date).
- For a why/reason question, explain only from the allowed income/bank, debt/DTI, and payment-history fields above. Do not use or quote a free-text reason field. Do not label income as stable or a balance as good/low unless the stored data explicitly supports that description.
- For highest, lowest, youngest or top questions use ORDER BY with LIMIT.
- For list questions (list, show, which applicants, kaun kaun) do NOT add LIMIT: the program limits the output itself and tells the user the total. Add LIMIT only when the user asks for a number, such as top 5.
- Product/category counts, catalog facts, prices and maximum tenures must come from RAG, never appliance_categories or applicant product fields. Sample applicant counts remain SQL.
"""

SYSTEM_PROMPT = (
    "You convert natural language questions into SQLite queries for an appliance "
    "installment eligibility database.\n\nSchema:\n" + SCHEMA + RULES
)

IDENTITY_COLUMNS = ["applicant_id", "full_name", "city", "age",
                    "employment_type", "requested_appliance_category"]

FORBIDDEN = re.compile(
    r"\b(drop|delete|update|insert|alter|attach|detach|pragma|create|vacuum|reindex|load_extension)\b|sqlite_",
    re.I,
)
RESTRICTED_COLUMNS = re.compile(
    r"\b(?:credit_score|credit_score_band|guarantor_credit_score|mobile_wallet_score|decision_reason)\b",
    re.I,
)
SELECT_ALL_COLUMNS = re.compile(
    r"\bselect\s+(?:distinct\s+)?(?:[\w]+\s*\.\s*)?\*",
    re.I,
)

def is_top_sample_eligibility_question(question):
    return bool(_TOP_SAMPLE_ELIGIBILITY.search(question))

def get_rejected_sample_list_limit(question):
    if not is_rejected_sample_list_question(question):
        return None
    match = _REJECTED_SAMPLE_LIST_LIMIT.search(question)
    if not match:
        return None
    return min(max(int(match.group("limit")), 1), MAX_ROWS)

_ALLOWED_REASON_FACTORS = re.compile(
    r"\b(?:income|salary|employment|job|bank|business|practice|debt|dti|loan|"
    r"installment|affordability|exposure|late|past\s+due|cheque|blacklist|"
    r"bankruptcy|default|bureau|payment\s+history)\b",
    re.IGNORECASE,
)

def _safe_decision_reasons(raw_reason):
    reasons = []
    for reason in (raw_reason or "").split(";"):
        reason = reason.strip()
        if (
            reason
            and not re.search(r"\bscore\b", reason, re.IGNORECASE)
            and _ALLOWED_REASON_FACTORS.search(reason)
        ):
            reasons.append(reason)
    return reasons

def get_sanitized_sample_records(status, limit=None, rank_by_income=False):
    """Return sample rows with only allowed, filtered CSV reason clauses."""
    status_clauses = {
        "Approved": "eligibility_status = 'Approved'",
        "Rejected": "eligibility_status = 'Rejected'",
    }
    if status not in status_clauses:
        raise ValueError("Unsupported sample eligibility status.")
    if rank_by_income and (status != "Approved" or limit is None):
        raise ValueError("Income ranking is only supported for a limited approved list.")

    fields = (
        "applicant_id, full_name, city, risk_tier, eligibility_status, "
        "monthly_net_income_pkr, monthly_gross_income_pkr, income_verified, "
        "months_in_current_job, salary_credited_to_bank, avg_monthly_balance_pkr, "
        "debt_to_income_ratio, active_loans_count, total_outstanding_debt_pkr, "
        "monthly_debt_obligation_pkr, late_payments_12m, bounced_cheques_12m, "
        "bureau_status, bankruptcy_flag, decision_reason"
    )
    query = f"SELECT {fields} FROM applicants WHERE {status_clauses[status]}"
    if rank_by_income:
        query += (
            " AND LOWER(bureau_status) != 'blacklisted' "
            "ORDER BY monthly_net_income_pkr DESC"
        )
    else:
        query += " ORDER BY full_name, city"
    if limit is not None:
        query += f" LIMIT {min(max(int(limit), 1), MAX_ROWS)}"

    columns, rows = _execute(query)
    records = []
    for row in rows:
        record = dict(zip(columns, row))
        record["recorded_reasons"] = _safe_decision_reasons(
            record.pop("decision_reason")
        )
        records.append(record)
    return records

def get_top_eligible_sample_records(question):
    match = _TOP_SAMPLE_ELIGIBILITY.search(question)
    if not match:
        raise ValueError("A top-N eligible sample-applicant question is required.")

    limit = min(max(int(match.group("limit")), 1), MAX_ROWS)
    query = (
        "SELECT full_name, monthly_net_income_pkr, avg_monthly_balance_pkr, "
        "active_loans_count, late_payments_12m, bounced_cheques_12m, "
        "bureau_status, bankruptcy_flag, eligibility_status "
        "FROM applicants "
        "WHERE eligibility_status IN ('Approved', 'Approved with Conditions') "
        "AND LOWER(TRIM(bankruptcy_flag)) = 'no' "
        "AND LOWER(TRIM(bureau_status)) != 'blacklisted' "
        "ORDER BY monthly_net_income_pkr DESC, applicant_id ASC "
        f"LIMIT {limit}"
    )
    columns, rows = _execute(query)
    return [dict(zip(columns, row)) for row in rows]

def get_bankruptcy_eligibility_counts():
    query = (
        "SELECT eligibility_status, COUNT(*) AS sample_records "
        "FROM applicants WHERE LOWER(TRIM(bankruptcy_flag)) = 'yes' "
        "GROUP BY eligibility_status ORDER BY eligibility_status"
    )
    columns, rows = _execute(query)
    return {row[0]: row[1] for row in rows}

def text_to_sql(question, failed_sql=None, error=None):
    top_eligibility_match = _TOP_SAMPLE_ELIGIBILITY.search(question)
    if top_eligibility_match:
        limit = min(max(int(top_eligibility_match.group("limit")), 1), MAX_ROWS)
        return (
            "SELECT full_name, monthly_net_income_pkr, avg_monthly_balance_pkr, "
            "active_loans_count, late_payments_12m, bounced_cheques_12m, "
            "bureau_status, bankruptcy_flag, eligibility_status FROM applicants "
            "WHERE eligibility_status IN ('Approved', 'Approved with Conditions') "
            "AND LOWER(TRIM(bankruptcy_flag)) = 'no' "
            "AND LOWER(TRIM(bureau_status)) != 'blacklisted' "
            "ORDER BY monthly_net_income_pkr DESC, applicant_id ASC "
            f"LIMIT {limit}"
        )

    if is_rejected_sample_list_question(question):
        query = (
            "SELECT full_name, monthly_net_income_pkr, avg_monthly_balance_pkr, "
            "active_loans_count, late_payments_12m, bounced_cheques_12m, "
            "bureau_status, bankruptcy_flag, eligibility_status "
            "FROM applicants WHERE eligibility_status = 'Rejected' "
            "ORDER BY full_name"
        )
        limit = get_rejected_sample_list_limit(question)
        if limit is not None:
            query += f" LIMIT {limit}"
        return query

    if is_applicant_rejection_basis_question(question):
        applicant_id = _APPLICANT_ID.search(question).group(0).upper()
        return (
            "SELECT applicant_id, monthly_gross_income_pkr, monthly_net_income_pkr, "
            "avg_monthly_balance_pkr, active_loans_count, total_outstanding_debt_pkr, "
            "monthly_debt_obligation_pkr, late_payments_12m, bounced_cheques_12m, "
            "bureau_status, bankruptcy_flag, eligibility_status "
            "FROM applicants "
            f"WHERE applicant_id = '{applicant_id}'"
        )

    if is_sample_rejection_basis_question(question):
        return (
            "SELECT eligibility_status, COUNT(*) AS sample_records, "
            "ROUND(AVG(monthly_gross_income_pkr), 0) AS avg_monthly_gross_income_pkr, "
            "ROUND(AVG(monthly_net_income_pkr), 0) AS avg_monthly_net_income_pkr, "
            "ROUND(AVG(avg_monthly_balance_pkr), 0) AS avg_monthly_balance_pkr, "
            "ROUND(AVG(active_loans_count), 1) AS avg_active_loans, "
            "ROUND(AVG(total_outstanding_debt_pkr), 0) AS avg_outstanding_debt_pkr, "
            "ROUND(AVG(late_payments_12m), 1) AS avg_late_payments_12m, "
            "ROUND(AVG(bounced_cheques_12m), 1) AS avg_bounced_cheques_12m, "
            "SUM(CASE WHEN bureau_status = 'Blacklisted' THEN 1 ELSE 0 END) "
            "AS blacklisted_records, "
            "SUM(CASE WHEN bankruptcy_flag = 'Yes' THEN 1 ELSE 0 END) "
            "AS bankruptcy_records "
            "FROM applicants WHERE eligibility_status = 'Rejected' "
            "GROUP BY eligibility_status ORDER BY eligibility_status"
        )

    if _SAMPLE_FACTOR_ELIGIBILITY.search(question) and re.search(
        r"\b(?:installments?|instalments?|financ\w*|on\s+credit)\b",
        question,
        re.IGNORECASE,
    ):
        question_lower = question.lower()
        if re.search(r"\bblacklist(?:ed)?\b", question_lower):
            condition = "LOWER(bureau_status) = 'blacklisted'"
        elif re.search(
            r"\b(?:no\s+(?:income|source\s+of\s+income)|without\s+(?:any\s+)?income|"
            r"(?:does\s+not|doesn't|do\s+not|don't|has\s+no)\s+(?:have\s+)?(?:any\s+)?"
            r"income(?:\s+source)?|unemployed)\b",
            question_lower,
        ):
            condition = (
                "COALESCE(monthly_gross_income_pkr, 0) <= 0 "
                "AND COALESCE(monthly_net_income_pkr, 0) <= 0 "
                "AND COALESCE(other_monthly_income_pkr, 0) <= 0 "
                "AND LOWER(employment_type) = 'unemployed'"
            )
        else:
            condition = "COALESCE(previous_installment_plans, 0) = 0"

        return (
            "SELECT COUNT(*) AS sample_records, "
            "SUM(CASE WHEN eligibility_status = 'Approved' THEN 1 ELSE 0 END) AS approved, "
            "SUM(CASE WHEN eligibility_status = 'Approved with Conditions' THEN 1 ELSE 0 END) "
            "AS approved_with_conditions, "
            "SUM(CASE WHEN eligibility_status = 'Referred for Manual Review' THEN 1 ELSE 0 END) "
            "AS manual_review, "
            "SUM(CASE WHEN eligibility_status = 'Rejected' THEN 1 ELSE 0 END) AS rejected "
            f"FROM applicants WHERE {condition}"
        )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    if failed_sql:
        messages += [
            {"role": "assistant", "content": failed_sql},
            {"role": "user", "content": f"That query failed with: {error}. Return one corrected SELECT query only."},
        ]
    response = client.chat.completions.create(model=MODEL, messages=messages, temperature=0)
    sql = response.choices[0].message.content.strip()
    sql = re.sub(r"```(?:sql)?", "", sql, flags=re.I).strip()
    return sql.rstrip(";").strip()

def ensure_identity_columns(sql):
    """A lookup of one person must show who each row is, so people with the same name can be told apart."""
    m = re.match(r"\s*select\s+(.*?)\s+from\s+applicants\b(.*)$", sql, re.I | re.S)
    if not m:
        return sql
    cols, rest = m.group(1).strip(), m.group(2)
    low = rest.lower()
    if cols == "*" or cols.lower().startswith("distinct"):
        return sql
    if "full_name" not in low and "applicant_id" not in low:
        return sql
    if re.search(r"\b(count|avg|sum|min|max)\s*\(|group\s+by", sql, re.I):
        return sql
    have = {c.strip().lower() for c in cols.split(",")}
    extra = [c for c in IDENTITY_COLUMNS if c not in have]
    if not extra:
        return sql
    return f"SELECT {', '.join(extra)}, {cols} FROM applicants{rest}"

def is_safe_query(sql):
    s = sql.strip().lower()
    if not (s.startswith("select") or s.startswith("with")):
        return False
    if ";" in s:
        return False
    return (
        not FORBIDDEN.search(s)
        and not RESTRICTED_COLUMNS.search(s)
        and not SELECT_ALL_COLUMNS.search(s)
    )

def _execute(sql):
    # read-only connection (a fresh one per call, safe for FastAPI threads) and a time limit
    conn = sqlite3.connect(DB_PATH.as_uri() + "?mode=ro", uri=True)
    deadline = time.monotonic() + QUERY_TIMEOUT_SECONDS
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 100000)
    try:
        cursor = conn.execute(sql)
        rows = cursor.fetchmany(MAX_ROWS)
        columns = [d[0] for d in cursor.description]
        return columns, rows
    finally:
        conn.close()

def get_applicant_factors_by_question(question):
    match = _APPLICANT_ID.search(question)
    if not match:
        raise ValueError("An applicant ID is required for a specific factor lookup.")

    applicant_id = match.group(0).upper()
    sql = (
        "SELECT applicant_id, full_name, monthly_gross_income_pkr, monthly_net_income_pkr, "
        "avg_monthly_balance_pkr, active_loans_count, total_outstanding_debt_pkr, "
        "monthly_debt_obligation_pkr, late_payments_12m, bounced_cheques_12m, "
        "previous_installment_defaults, affordability_headroom_pkr, "
        "bureau_status, bankruptcy_flag, eligibility_status "
        "FROM applicants "
        f"WHERE applicant_id = '{applicant_id}'"
    )
    if not is_safe_query(sql):
        raise RuntimeError("The fixed applicant-factor query failed its safety check.")
    columns, rows = _execute(sql)
    if not rows:
        return None
    record = dict(zip(columns, rows[0]))
    reason_sql = (
        "SELECT decision_reason FROM applicants "
        f"WHERE applicant_id = '{applicant_id}'"
    )
    _, reason_rows = _execute(reason_sql)
    record["recorded_reasons"] = _safe_decision_reasons(reason_rows[0][0])
    return record

def get_applicant_rejection_basis_record(question):
    if not is_applicant_rejection_basis_question(question):
        raise ValueError("A rejection-basis question with an applicant ID is required.")
    return get_applicant_factors_by_question(question)

def run_query(question):
    """Returns (columns, rows) on success or (None, 'error text') on failure."""
    sql = text_to_sql(question)
    if not is_top_sample_eligibility_question(question):
        sql = ensure_identity_columns(sql)
    for attempt in (1, 2):
        log.info("SQL (attempt %s): %s", attempt, sql)
        if RESTRICTED_COLUMNS.search(sql) or SELECT_ALL_COLUMNS.search(sql):
            return ["note"], []
        if not is_safe_query(sql):
            return None, "Blocked: query failed safety check"
        try:
            columns, rows = _execute(sql)
        except Exception as e:
            if attempt == 2:
                return None, f"Error: {e}"
            sql = text_to_sql(question, failed_sql=sql, error=str(e))
            if not is_top_sample_eligibility_question(question):
                sql = ensure_identity_columns(sql)
            continue
        if rows == [("NOT_IN_DATABASE",)]:
            return columns, []
        return columns, rows

if __name__ == "__main__":
    print(run_query("Show applicants in risk tier A with their monthly installment amount"))