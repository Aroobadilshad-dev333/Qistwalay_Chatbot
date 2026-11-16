import os
import re
from dotenv import load_dotenv
from openai import OpenAI
from text2sql_module import (
    is_rejected_sample_list_question,
    is_sample_rejection_basis_question,
    is_top_sample_eligibility_question,
)

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

ROUTER_SYSTEM_PROMPT = """You are a routing classifier for a Qistwalay customer support system. You must NOT answer the question — only classify it.

## DATA SOURCES ##
SQL database (SQLite) — SAMPLE applicant data from the supplied CSV, not live customer records. It contains applicant identity/contact details, income, employment, banking, debt, payment history, bankruptcy flags, risk tiers, recorded decisions, requested products, and approved plans. It also contains category-level price ranges and maximum tenures.

RAG — product, policy, FAQ, and installment-process information collected from Qistwalay's website.

## INSTRUCTIONS ##
Classify into exactly ONE label: sql, rag, or both.
- sql: questions asking for facts recorded in a particular/sample applicant's row (including name, CNIC, email, income, bank details, debt, payment history, bankruptcy flag, risk tier, recorded eligibility status, or approved plan), sample-applicant counts/lists, or sample-data comparisons about eligibility factors. For hypothetical factor questions, SQL may summarize matching sample records only; it cannot establish a real policy or decide a real person's application.
- rag: all Qistwalay product/catalog information (including categories, prices, plans, availability and specifications), FAQs, policies, required documents, or general eligibility rules published by Qistwalay. Never use CSV/SQLite product columns or category data as website product facts.
- both: a question explicitly asks for a particular sample applicant's recorded financial/eligibility facts AND asks for Qistwalay website policy/product information or how that policy applies. A specific applicant's recorded decision is historical sample data, not a new approval.
- Questions with an applicant ID such as APP-2026-1010 refer to that sample record. A name or short follow-up referring to an applicant record should use SQL; if the same question also asks about website policy/product facts, use both.
- If a question asks how sample applicants with a stated factor (such as blacklisted status, no recorded income, or no previous installment plans) fared, use SQL to summarize matching sample outcomes. Clearly distinguish this historical sample evidence from actual Qistwalay policy. Product catalog/details are still RAG only.
- A general eligibility question without a sample-data factor comparison is rag. Never use the sample CSV to decide a real or hypothetical person's eligibility.

Return ONLY the single word: sql, rag, or both. Nothing else."""


_APPLICANT_ID = re.compile(r"\bAPP[-\s]?\d{4}[-\s]?\d{3,}\b", re.IGNORECASE)
_NAMED_PERSON_QUESTION = re.compile(
    r"(?i:\b(?:can|could|would|is|was|does|did)\s+(?:applicant\s+)?)"
    r"(?!(?i:i|we|you|he|she|they|it|this|that|there|a|an|the|person|people|"
    r"customer|applicant|user|borrower|someone|anyone|bankrupt(?:cy)?|eligible|"
    r"eligibility|qualify|qualified|allowed|approved|rejected)\b)"
    r"[A-Z][a-z]+(?:[-'][A-Za-z]+)?(?:\s+[A-Z][a-z]+(?:[-'][A-Za-z]+)?)?"
)
_GENERAL_ELIGIBILITY = re.compile(
    r"\b(bankrupt(?:cy)?|eligib\w*|qualif\w*|minimum\s+(?:income|age))\b",
    re.IGNORECASE,
)
_RESTRICTED_FIELD_QUESTION = re.compile(
    r"\b(?:credit[\s_-]*score(?:[\s_-]*band)?|guarantor[\s_-]*credit[\s_-]*score|"
    r"mobile[\s_-]*wallet[\s_-]*score)\b",
    re.IGNORECASE,
)
_INSTALLMENT_DECISION = re.compile(
    r"\b(?:can|could|may|would|allowed|eligible|qualif\w*|take|get|receive)\b"
    r".{0,100}\b(?:installments?|instalments?|financ\w*|on\s+credit)\b",
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
_SAMPLE_LOOKUP = re.compile(
    r"\b(?:applicants?|sample\s+data|sample\s+record)\b"
    r".{0,80}\b(?:show|list|which|who|how\s+many|count|income|"
    r"risk|tier|status|decision|approved|rejected|bank|email|cnic|city)\b"
    r"|\b(?:show|list|which|who|how\s+many|count)\b.{0,80}"
    r"\b(?:applicants?|sample\s+data|sample\s+records?)\b"
    r"|\b(?:how\s+many|list|show|count|which)\b.{0,80}"
    r"\bapplicants?\b.{0,80}\b(?:bankrupt|bankruptcy)\b",
    re.IGNORECASE,
)
_ABOUT_QISTWALAY = re.compile(
    r"\b(?:tell\s+me\s+about|what\s+(?:is|does)|who\s+is|describe)\s+qistwalay\b"
    r"|\bqistwalay\b.{0,80}\b(?:about|bare|bary|baray|baare|kya|kia|jant\w*|"
    r"business|company|shop|store)\b",
    re.IGNORECASE,
)


def _quick_route(question: str) -> str | None:
    """Keep general policy questions out of the synthetic applicant database."""
    if (
        is_rejected_sample_list_question(question)
        or is_sample_rejection_basis_question(question)
    ):
        return "sql"

    if _RESTRICTED_FIELD_QUESTION.search(question):
        return "sql"

    if _SAMPLE_FACTOR_ELIGIBILITY.search(question) and re.search(
        r"\b(?:installments?|instalments?|financ\w*|on\s+credit)\b",
        question,
        re.IGNORECASE,
    ):
        return "sql"

    if is_top_sample_eligibility_question(question):
        return "sql"

    if re.search(r"\b(?:price(?:\s+range)?|cost|tenure|max(?:imum)?\s+tenure)\b", question, re.IGNORECASE) and re.search(
        r"\b(?:air\s*conditioners?|refrigerators?|washing\s*machines?|televisions?|tvs?|microwave\s*ovens?|water\s*dispensers?|deep\s*freezers?|mobile\s*phones?|air\s*coolers?|fans?|geysers?|motorcycles?|room\s*heaters?|air\s*purifiers?)\b",
        question,
        re.IGNORECASE,
    ):
        return "sql"

    if (
        re.search(r"\b(?:how\s+many|count|list|show|which|who)\b", question, re.IGNORECASE)
        and re.search(r"\b(?:applicants?|people|sample)\b", question, re.IGNORECASE)
        and re.search(r"\b(?:refund|policy|warranty|document|requirement|faq|terms)\b", question, re.IGNORECASE)
    ):
        return "both"

    has_applicant_id = bool(_APPLICANT_ID.search(question))
    has_named_person = bool(_NAMED_PERSON_QUESTION.search(question))
    asks_about_installment_eligibility = bool(
        _GENERAL_ELIGIBILITY.search(question) or _INSTALLMENT_DECISION.search(question)
    )

    if has_applicant_id or has_named_person:
        asks_about_policy = bool(
            _GENERAL_ELIGIBILITY.search(question)
            and re.search(r"\b(?:website|policy|rule|criteria|requirement)\w*\b", question, re.I)
        )
        return "both" if _INSTALLMENT_DECISION.search(question) or asks_about_policy else "sql"
    if _ABOUT_QISTWALAY.search(question):
        return "rag"
    if asks_about_installment_eligibility and not _SAMPLE_LOOKUP.search(question):
        return "rag"
    return None


def classify_question(question: str) -> str:
    quick_route = _quick_route(question)
    if quick_route:
        return quick_route

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
            {"role": "user",   "content": f"## CURRENT QUESTION ##\n{question}"}
        ],
        temperature=0
    )
    label = response.choices[0].message.content.strip().lower()
    if label not in {"sql", "rag", "both"}:
        print(f"WARNING: unexpected label '{label}' — defaulting to 'both'")
        label = "both"
    return label
