import json
import os

from openai import AzureOpenAI
from dotenv import load_dotenv

from . import firefighter_review_agent


# ============================================================
# LOAD ENVIRONMENT
# ============================================================

load_dotenv()

AZURE_OPENAI_ENDPOINT = (
    os.getenv("AZURE_OPENAI_ENDPOINT", "")
    .strip()
    .rstrip("/")
)

AZURE_OPENAI_API_KEY = (
    os.getenv("AZURE_OPENAI_API_KEY", "")
    .strip()
)

AZURE_OPENAI_DEPLOYMENT = (
    os.getenv("AZURE_OPENAI_DEPLOYMENT", "")
    .strip()
)

AZURE_OPENAI_API_VERSION = (
    os.getenv("AZURE_OPENAI_API_VERSION", "")
    .strip()
)


# ============================================================
# VALIDATE ENVIRONMENT
# ============================================================

if not AZURE_OPENAI_ENDPOINT:
    print("WARNING: AZURE_OPENAI_ENDPOINT is not configured.")

if not AZURE_OPENAI_API_KEY:
    print("WARNING: AZURE_OPENAI_API_KEY is not configured.")

if not AZURE_OPENAI_DEPLOYMENT:
    print("WARNING: AZURE_OPENAI_DEPLOYMENT is not configured.")

if not AZURE_OPENAI_API_VERSION:
    print("WARNING: AZURE_OPENAI_API_VERSION is not configured.")


# ============================================================
# AZURE OPENAI CLIENT
# ============================================================

azure_client = AzureOpenAI(
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    api_key=AZURE_OPENAI_API_KEY,
    api_version=AZURE_OPENAI_API_VERSION
)


# ============================================================
# AI ROUTER
# ============================================================

def ai_router(question):

    prompt = """
You are the SAP Enterprise AI Router.

Your job is ONLY to determine whether the user request
should go to the Firefighter Review Agent or the RAG
Assistant.

Return ONLY valid JSON.

Available agents:

1. firefighterreview
2. rag


============================================================
FIREFIGHTER REVIEW AGENT
============================================================

Route to "firefighterreview" when the user asks about:

- Firefighter
- Firefighter sessions
- Firefighter logs
- FF sessions
- FF logs
- Firefighter activity
- Firefighter activities
- Firefighter review
- Review Firefighter
- Analyze Firefighter
- Analyze Firefighter sessions
- Analyze all Firefighter sessions
- Pending Firefighter reviews
- Pending FF reviews
- Firefighter transactions
- Firefighter usage
- Emergency Access Management
- EAM
- Firefighter ID
- Firefighter user
- FF user
- Controller Firefighter assignments
- Firefighter risk
- Firefighter justification
- Firefighter approval
- Firefighter audit
- Firefighter controller
- Controller review of Firefighter logs

Examples:

User:
"Analyze all firefighter sessions"

Return:
{
    "agent": "firefighterreview"
}

User:
"Show Firefighter logs"

Return:
{
    "agent": "firefighterreview"
}

User:
"Review FF activity"

Return:
{
    "agent": "firefighterreview"
}


============================================================
RAG ASSISTANT
============================================================

For all other questions, return:

{
    "agent": "rag"
}


============================================================
IMPORTANT RULES
============================================================

- Return ONLY JSON.
- Do not return explanations.
- Do not return markdown.
- Do not invent an agent.
- Use exactly one of:
  "firefighterreview"
  "rag"
"""


    try:

        response = azure_client.chat.completions.create(

            model=AZURE_OPENAI_DEPLOYMENT,

            messages=[
                {
                    "role": "system",
                    "content": prompt
                },
                {
                    "role": "user",
                    "content": question
                }
            ],

            temperature=0,

            max_tokens=100
        )

        text = (
            response
            .choices[0]
            .message
            .content
            .strip()
        )

        print(
            "\n========== Router Raw Output =========="
        )

        print(text)

        print(
            "=======================================\n"
        )

        # ----------------------------------------------------
        # Parse JSON
        # ----------------------------------------------------

        route = json.loads(text)

        # ----------------------------------------------------
        # Validate agent
        # ----------------------------------------------------

        agent = route.get("agent")

        if agent not in [
            "firefighterreview",
            "rag"
        ]:

            print(
                "Invalid router agent. "
                "Falling back to RAG."
            )

            return {
                "agent": "rag"
            }

        return {
            "agent": agent
        }

    except Exception as e:

        print(
            f"Router error: {str(e)}"
        )

        # ----------------------------------------------------
        # Safe fallback
        # ----------------------------------------------------

        return {
            "agent": "rag"
        }


# ============================================================
# DISPATCH
# ============================================================

def dispatch(question, authenticated_identity=None):

    print(
        "\n======================================"
    )

    print(
        "       SAP ENTERPRISE ROUTER"
    )

    print(
        "======================================"
    )

    print(
        "Question:",
        question
    )

    # --------------------------------------------------------
    # Get route
    # --------------------------------------------------------

    route = ai_router(question)

    print(
        "Router output:",
        route
    )

    agent = route.get(
        "agent",
        "rag"
    )

    print(
        "Selected agent:",
        agent
    )

    # --------------------------------------------------------
    # Firefighter Review Agent
    # --------------------------------------------------------

    if agent == "firefighterreview":

        print(
            "Calling Firefighter Review Agent..."
        )

        return firefighter_review_agent.run_agent(
            question,
            authenticated_identity=authenticated_identity
        )

    # --------------------------------------------------------
    # RAG
    # --------------------------------------------------------

    if agent == "rag":

        print(
            "Calling RAG fallback..."
        )

        return (
            "RAG Assistant will answer this question.\n"
            "Integration will be added later."
        )

    # --------------------------------------------------------
    # Safety fallback
    # --------------------------------------------------------

    return (
        "Unable to determine which agent "
        "should answer."
    )


# ============================================================
# OPTIONAL LOCAL TEST
# ============================================================

if __name__ == "__main__":

    print(
        "======================================"
    )

    print(
        " SAP Enterprise AI Assistant "
    )

    print(
        "======================================\n"
    )

    print(
        "Available agents:"
    )

    print(
        " - Firefighter Review"
    )

    print(
        " - RAG"
    )

    print()

    while True:

        question = input(
            "You : "
        ).strip()

        if question.lower() in [
            "exit",
            "quit",
            "bye"
        ]:

            print(
                "\nAssistant : Bye\n"
            )

            break

        if not question:
            continue

        print(
            "\nAssistant:\n"
        )

        answer = dispatch(
            question
        )

        print(
            answer
        )

        print()