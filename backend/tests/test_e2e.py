"""
test_e2e.py  --  End-to-end test of the whole Qistwalay pipeline (Step 5)

Runs real questions through run_pipeline() (the same function the FastAPI /chat endpoint
calls): Rephraser -> Router -> SQL and/or RAG -> Final LLM.
No server needs to be running.

    python test_e2e.py

Cost: about 12 questions x ~4 cheap gpt-4o-mini calls. Takes 1-2 minutes.

Each turn is checked automatically: expected route, words that must appear in the answer,
patterns that must NOT appear, and the language of the answer. The checks are simple, so if
a turn shows FAIL, read the printed answer before deciding whether it is really wrong.
"""

import io
import re
import contextlib

from pipeline import run_pipeline, detect_language

# Each scenario starts with a fresh chat history.
# Turn keys: q = question | routes = allowed routes | any = answer must contain at least one of
# these words | regex = answer must match | lang = expected answer language
# ("english", "roman_urdu" or "urdu")
SCENARIOS = [
    {
        "name": "1. Pure SQL question",
        "turns": [
            {"q": "What is the recorded risk tier and status for applicant APP-2026-1003?",
             "routes": {"sql"}, "any": ["E", "Rejected"], "lang": "english"},
        ],
    },
    {
        "name": "2. Pure RAG question",
        "turns": [
            {"q": "What documents do I need to apply for installments?",
             "routes": {"rag"}, "any": ["CNIC"], "lang": "english"},
        ],
    },
    {
        "name": "3. Follow-up that needs chat history (English)",
        "turns": [
            {"q": "What is the maximum tenure for an Air Conditioner?",
             "routes": {"rag"}, "any": ["12"], "lang": "english"},
            {"q": "And for a Refrigerator?",
             "routes": {"rag"}, "any": ["10"], "lang": "english"},
        ],
    },
    {
        "name": "4. Follow-up that needs rephrasing (Roman Urdu)",
        "turns": [
            {"q": "What is the maximum tenure for an Air Conditioner?",
             "routes": {"rag"}, "any": ["12"], "lang": "english"},
            {"q": "aur Refrigerator ka?",
             "routes": {"rag"}, "any": ["10"], "lang": "roman_urdu"},
        ],
    },
    {
        "name": "5a. Product category price range (should be RAG)",
        "turns": [
            {"q": "What is the price range of Air Conditioners?",
             "routes": {"rag"}, "any": ["Rs.", "PKR"], "lang": "english"},
        ],
    },
    {
        "name": "5b. SQL vs RAG confusion: product specifications (should be RAG)",
        "turns": [
            {"q": "What are the specifications of the refrigerators you sell?",
             "routes": {"rag"}, "lang": "english"},
        ],
    },
    {
        "name": "5c. Needs both: applicant data + policy",
        "turns": [
            {"q": "How many applicants were rejected, and what is the refund policy?",
             "routes": {"both"}, "lang": "english"},
        ],
    },
    {
        "name": "6. Roman Urdu question",
        "turns": [
            {"q": "APP-2026-1003 ka recorded risk tier aur status kya hai?",
             "routes": {"sql"}, "any": ["E", "Rejected"], "lang": "roman_urdu"},
        ],
    },
    {
        "name": "7. Off-topic question (should be declined)",
        "turns": [
            {"q": "Who won the cricket world cup?",
             "any": ["sorry", "Qistwalay", "can't", "cannot"], "lang": "english"},
        ],
    },
    {
        "name": "8. Applicant dummy contact details",
        "turns": [
            {"q": "Show me the CNIC, mobile number, and email of applicant APP-2026-1001",
             "regex": r"(?=.*\d{5}-?\d{7}-?\d)(?=.*(?:\+92[- ]?)?3\d{2}[- ]?\d{7})(?=.*[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})",
             "lang": "english"},
        ],
    },
]


def run_turn(turn, history):
    """Runs one question quietly (the 'Generated SQL' prints are hidden) and checks it."""
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            result = run_pipeline(turn["q"], history)
    except Exception as e:
        return False, {"answer": f"CRASH: {e}", "route": "-", "rephrased_question": "-"}, ["crashed"]

    problems = []
    answer = result["answer"]
    if "routes" in turn and result["route"] not in turn["routes"]:
        problems.append(f"route was '{result['route']}', expected {sorted(turn['routes'])}")
    if "any" in turn and not any(k.lower() in answer.lower() for k in turn["any"]):
        problems.append(f"answer has none of {turn['any']}")
    if "regex" in turn and not re.search(turn["regex"], answer, re.IGNORECASE | re.DOTALL):
        problems.append("answer does not include all requested dummy contact details")
    if "lang" in turn and detect_language(answer) != turn["lang"]:
        problems.append(f"answer language looks like '{detect_language(answer)}', expected '{turn['lang']}'")
    return not problems, result, problems


total = passed = 0
failures = []

for scenario in SCENARIOS:
    print("\n" + "=" * 72)
    print(scenario["name"])
    print("=" * 72)
    history = []
    for turn in scenario["turns"]:
        ok, result, problems = run_turn(turn, history)
        total += 1
        passed += ok

        print(f"{'PASS' if ok else 'FAIL'}  Q: {turn['q']}")
        print(f"      Rephrased: {result['rephrased_question']}")
        print(f"      Route:     {result['route']}")
        print(f"      Answer:    {result['answer'][:300]}")
        for p in problems:
            print(f"      -> {p}")
        if not ok:
            failures.append(f"{scenario['name']} | {turn['q']}")

        history.append({"role": "user", "content": turn["q"]})
        history.append({"role": "assistant", "content": result["answer"]})

print("\n" + "#" * 72)
print(f"RESULT: {passed}/{total} turns passed")
if failures:
    print("Check these:")
    for f in failures:
        print("  -", f)
print("#" * 72)