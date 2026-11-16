import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
REPHRASER_SYSTEM_PROMPT = """You rewrite ambiguous follow-up questions into clear, standalone questions using the conversation history. You do NOT answer the question — only rewrite it.

## INSTRUCTIONS ##
- If the current question already makes sense on its own, return it UNCHANGED, even when the chat history is about a different topic. Never add a product, category, applicant or topic from the history to it.
- Only use the history when the question contains a reference word (it, this, that, these, they, iska, iski, woh, isi ki, second, first, aur) or is missing its subject. Then resolve the reference using the history and rewrite it as a clear, standalone question.
- If a follow-up asks "on what basis", "why", or "kis basis" an installment decision was made after discussing sample applicants, rewrite it as a question about factors recorded in the sample CSV rows. Do not frame it as Qistwalay's real policy or an actual person's eligibility decision.
- If the user asks for names of people who cannot get installments, rewrite it as a request to list sample applicants whose stored eligibility status is Rejected.
- Always write the rewritten question in clear ENGLISH, even if the user wrote in Urdu or Roman Urdu.
- This is an installment store. The word "tenure" (also "muddat", "kitne mahine") ALWAYS means the length of the installment plan in months. Never turn it into product lifespan, durability, warranty or age. Keep the word "tenure" in the rewritten question and say "installment tenure".
- Return ONLY the rewritten question. No explanation, no extra text.
- If the question is about the user themselves (my name, mera naam, what did I say), return it UNCHANGED.

## EXAMPLES ##
History: User asked about the maximum tenure of a Refrigerator.
Question: Which city has the most applicants?
Rewritten: Which city has the most applicants?

History: User asked about the maximum tenure of an Air Conditioner.
Question: aur Refrigerator ka?
Rewritten: What is the maximum installment tenure for a Refrigerator?

History: User asked for the CNIC of Fatima Raza. Assistant said there are three applicants named Fatima Raza (Abbottabad, Lahore, Peshawar) and asked which one.
Question: Lahore wali
Rewritten: What is the CNIC of Fatima Raza from Lahore?

History: User asked about the maximum tenure of a Geyser.
Question: Geyser ki max tenure kitni hai?0
Rewritten: What is the maximum installment tenure for a Geyser}?"""



def format_history(chat_history, limit=6):
    if not chat_history:
        return "(no previous conversation)"
    lines = []
    for turn in chat_history[-limit:]:
        role = "User" if turn["role"] == "user" else "Assistant"
        lines.append(f"{role}: {turn['content']}")
    return "\n".join(lines)


def rephrase_question(current_question, chat_history):
    history_text = format_history(chat_history)

    user_message = f"""## CHAT HISTORY ##
{history_text}

## CURRENT QUESTION ##
{current_question}"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": REPHRASER_SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ],
        temperature=0
    )
    return response.choices[0].message.content.strip()