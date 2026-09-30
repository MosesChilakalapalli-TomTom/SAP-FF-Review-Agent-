import time
import os
import json
import re
import requests
import urllib3
import sys

from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth
from openai import AzureOpenAI
from datetime import datetime, timedelta

try:
    from .auth_helper import (
        check_authorization,
        format_authorization_denied
    )
except ImportError:
    from auth_helper import (
        check_authorization,
        format_authorization_denied
    )

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()

SAP_HOST = os.getenv("SAP_HOST", "").strip().rstrip("/")
SAP_CLIENT = os.getenv("SAP_CLIENT", "").strip()
SAP_USER = os.getenv("SAP_USER", "").strip()
SAP_PASS = os.getenv("SAP_PASS", "").strip()

AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip().rstrip("/")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "").strip()
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "").strip()

azure_client = AzureOpenAI(
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    api_key=AZURE_OPENAI_API_KEY,
    api_version=AZURE_OPENAI_API_VERSION
)

session = requests.Session()
session.auth = HTTPBasicAuth(SAP_USER, SAP_PASS)
session.verify = False
session.headers.update({"Accept": "application/json"})

IDOC_URL = f"{SAP_HOST}/sap/opu/odata/sap/ZIDOC_MONITOR_SRV/FailedIdocSet"

STATUS_TEXT = {
    "50": "Added",
    "51": "Application document not posted",
    "53": "Application document posted",
    "56": "EDI error",
    "64": "Ready to be transferred",
    "68": "No further processing",
    "69": "Edited",
    "70": "Error during editing",
    "74": "Created"
}


def clean_value(value):
    if value is None:
        return ""

    value = str(value).strip()
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"[^A-Za-z0-9._/-]", "", value)

    return value


def sap_get(url, params=None):
    query = {
        "sap-client": SAP_CLIENT,
        "saml2": "disabled",
        "$format": "json"
    }

    if params:
        query.update(params)

    try:
        start = time.time()

        response = session.get(
            url,
            params=query,
            timeout=60
        )

        print(f"SAP GET Time: {time.time() - start:.2f} sec")

        if response.status_code != 200:
            return {
                "status": "error",
                "status_code": response.status_code,
                "response": response.text
            }

        return response.json()

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


def format_idoc_list(results):
    if not results:
        return "No IDocs found."

    output = []

    output.append("=" * 65)
    output.append(f"Found {len(results)} IDoc(s)")
    output.append("=" * 65)

    for i, row in enumerate(results, 1):
        status = row.get("Status", "")
        meaning = STATUS_TEXT.get(status, "Unknown")

        output.append(f"\n{i}. IDoc : {row.get('Docnum')}")
        output.append(f"   Status : {status} ({meaning})")
        output.append(f"   Type   : {row.get('MessageType')}")
        output.append(f"   Date   : {row.get('CreatedDate')}")

        if row.get("StatusText"):
            output.append(f"   Status : {row.get('StatusText')}")

        if row.get("ErrorText"):
            output.append(f"   Error  : {row.get('ErrorText')}")

        output.append("-" * 65)

    return "\n".join(output)


def get_idoc_by_number(docnum):
    docnum = clean_value(docnum).zfill(16)

    data = sap_get(
        IDOC_URL,
        {
            "$filter": f"Docnum eq '{docnum}'"
        }
    )

    if data.get("status") == "error":
        return f"SAP Error: {data}"

    results = data.get("d", {}).get("results", [])

    return format_idoc_list(results)


def get_idocs_by_status(status):
    status = clean_value(status)

    data = sap_get(
        IDOC_URL,
        {
            "$filter": f"Status eq '{status}'",
            "$top": "20"
        }
    )

    if data.get("status") == "error":
        return f"SAP Error: {data}"

    results = data.get("d", {}).get("results", [])

    return format_idoc_list(results)


def get_idocs_by_message_type(message_type):
    message_type = clean_value(message_type).upper()

    data = sap_get(
        IDOC_URL,
        {
            "$filter": f"MessageType eq '{message_type}'",
            "$top": "20"
        }
    )

    if data.get("status") == "error":
        return f"SAP Error: {data}"

    results = data.get("d", {}).get("results", [])

    return format_idoc_list(results)


def get_failed_idocs():
    data = sap_get(
        IDOC_URL,
        {
            "$top": "20",
            "$orderby": "CreatedDate desc"
        }
    )

    if data.get("status") == "error":
        return f"SAP Error: {data}"

    results = data.get("d", {}).get("results", [])

    return format_idoc_list(results)


def count_idocs_by_status(status):
    status = clean_value(status)

    data = sap_get(
        IDOC_URL,
        {
            "$filter": f"Status eq '{status}'",
            "$inlinecount": "allpages",
            "$top": "1"
        }
    )

    if data.get("status") == "error":
        return f"SAP Error: {data}"

    count = data.get("d", {}).get("__count")

    if count is None:
        count = len(data.get("d", {}).get("results", []))

    return f"Total IDocs in status {status}: {count}"


def get_idocs_by_date(created_date):
    data = sap_get(
        IDOC_URL,
        {
            "$filter": f"CreatedDate eq '{created_date}'",
            "$top": "20"
        }
    )

    if data.get("status") == "error":
        return f"SAP Error: {data}"

    results = data.get("d", {}).get("results", [])

    return format_idoc_list(results)


def get_idocs_by_status_and_date(status, created_date):
    data = sap_get(
        IDOC_URL,
        {
            "$filter": f"Status eq '{status}' and CreatedDate eq '{created_date}'",
            "$top": "20"
        }
    )

    if data.get("status") == "error":
        return f"SAP Error: {data}"

    results = data.get("d", {}).get("results", [])

    return format_idoc_list(results)


def ai_router(question):
    prompt = """
You are a secure SAP IDoc assistant router.
Return ONLY valid JSON. No markdown. No explanation.

Actions:
- get_idoc_by_number
- get_idocs_by_status
- get_idocs_by_message_type
- get_failed_idocs
- count_idocs_by_status
- get_idocs_by_date
- get_idocs_by_status_and_date
- unknown

JSON format:
{
  "action": "",
  "docnum": "",
  "status": "",
  "message_type": "",
  "created_date": ""
}

Rules:
If the user asks:
- today
- yesterday
- a specific date
- from 20260629

If the user says today:
Return "created_date":"TODAY"

If the user says yesterday:
Return "created_date":"YESTERDAY"

Never calculate dates yourself.

Examples:
Show today's IDocs
→ get_idocs_by_date

Show IDocs from 20260629
→ get_idocs_by_date

Show today's status 51 IDocs
→ get_idocs_by_status_and_date

Show ORDERS IDocs from today
→ get_idocs_by_message_type
(created_date also populated)

- If user asks for one specific IDoc number, use get_idoc_by_number and put the number in docnum.
- If user asks for IDocs in status 51, 56, 68, etc., use get_idocs_by_status and put status.
- If user asks how many IDocs are in status 51, 56, 68, etc., use count_idocs_by_status and put status.
- If user asks for ORDERS, DELVRY, INVOIC, etc., use get_idocs_by_message_type and put message_type.
- If user asks failed IDocs without specific status, use get_failed_idocs.
- Never ask for password, token, cookie, or credentials.
"""

    response = azure_client.chat.completions.create(
        model=AZURE_OPENAI_DEPLOYMENT,
        messages=[
            {
                "role": "system",
                "content": prompt
            },
            {
                "role": "user",
                "content": question.strip()
            }
        ],
        temperature=0,
        max_tokens=300
    )

    response_text = response.choices[0].message.content.strip()

    print("\n========== GPT Router ==========")
    print(response_text)
    print("================================\n")

    try:
        return json.loads(response_text)

    except Exception:
        return {
            "action": "unknown",
            "docnum": "",
            "status": "",
            "message_type": "",
            "created_date": ""
        }


def run_agent(question):
    question = question.strip()

    route = ai_router(question)
    action = route.get("action", "unknown")

    today = datetime.now().strftime("%Y%m%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")

    if route.get("created_date") == "TODAY":
        route["created_date"] = today

    elif route.get("created_date") == "YESTERDAY":
        route["created_date"] = yesterday

    valid_display_actions = [
        "get_idoc_by_number",
        "get_idocs_by_status",
        "get_idocs_by_message_type",
        "get_failed_idocs",
        "count_idocs_by_status",
        "get_idocs_by_date",
        "get_idocs_by_status_and_date"
    ]

    # -------------------------------------------------------
    # Authorization Check - IDoc Display
    # -------------------------------------------------------
    if action in valid_display_actions:
        auth_result = check_authorization(
            SAP_USER,
            "IDOC",
            "DISPLAY"
        )

        if not auth_result.get("authorized"):
            return format_authorization_denied(auth_result)

    if action == "get_idoc_by_number":
        return get_idoc_by_number(route.get("docnum", ""))

    if action == "get_idocs_by_status":
        return get_idocs_by_status(route.get("status", ""))

    if action == "count_idocs_by_status":
        return count_idocs_by_status(route.get("status", ""))

    if action == "get_idocs_by_message_type":
        return get_idocs_by_message_type(route.get("message_type", ""))

    if action == "get_failed_idocs":
        return get_failed_idocs()

    if action == "get_idocs_by_date":
        return get_idocs_by_date(route.get("created_date", ""))

    if action == "get_idocs_by_status_and_date":
        return get_idocs_by_status_and_date(
            route.get("status", ""),
            route.get("created_date", "")
        )

    return "I can check IDoc by number, status, message type, or show failed IDocs."


if __name__ == "__main__":
    print("IDoc Agent started")
    print("Type exit to stop\n")

    while True:
        question = input("You: ").strip()

        if question.lower() in ["exit", "quit", "bye"]:
            print("Assistant: Bye")
            break

        print("\nAssistant:")
        print(run_agent(question))
        print()