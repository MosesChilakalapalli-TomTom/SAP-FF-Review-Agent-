import os
import json
import re
import requests
import urllib3
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth
from openai import AzureOpenAI
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

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# -------------------------------------------------------
# Load Environment
# -------------------------------------------------------

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


# -------------------------------------------------------
# SAP Session
# -------------------------------------------------------

session = requests.Session()
session.auth = HTTPBasicAuth(SAP_USER, SAP_PASS)
session.verify = False
session.headers.update({"Accept": "application/json"})

# -------------------------------------------------------
# URLs
# -------------------------------------------------------

SEGMENT_URL = (
    f"{SAP_HOST}"
    "/sap/opu/odata/sap/ZIDOC_SEGMENT_SRV_SRV/IdocSegmentSet"
)

COSTCENTER_URL = (
    f"{SAP_HOST}"
    "/sap/opu/odata/sap/API_COSTCENTER_SRV/A_CostCenterText"
)

OBCC_URL = (
    f"{SAP_HOST}"
    "/sap/opu/odata/sap/ZFI_EDI_ASSIGNMENT_SRV_SRV/Assignment001Set"
)

pending_action = None

# -------------------------------------------------------
# Defaults
# -------------------------------------------------------

DEFAULT_PARTNER_TYPE = "LS"
DEFAULT_PARTNER_NO = "RYDOO"
DEFAULT_CO_AREA = "TT01"


# -------------------------------------------------------
# Helpers
# -------------------------------------------------------

def clean_value(value):
    if value is None:
        return ""

    value = str(value).strip()
    value = re.sub(r"\s+", "", value)

    return value


# -------------------------------------------------------
# Generic GET
# -------------------------------------------------------

def sap_get(url, params=None):
    query = {
        "sap-client": SAP_CLIENT,
        "saml2": "disabled",
        "$format": "json"
    }

    if params:
        query.update(params)

    try:
        response = session.get(
            url,
            params=query,
            timeout=60
        )

        if response.status_code != 200:
            return {
                "status": "error",
                "status_code": response.status_code,
                "response": response.text
            }

        return response.json()

    except Exception as ex:
        return {
            "status": "error",
            "message": str(ex)
        }


# -------------------------------------------------------
# Read IDoc Segments
# -------------------------------------------------------

def read_idoc_segments(idoc_number):
    data = sap_get(
        SEGMENT_URL,
        {
            "$filter": f"Docnum eq '{idoc_number}'"
        }
    )

    if data.get("status") == "error":
        return data

    results = data.get("d", {}).get("results", [])

    if not results:
        return {
            "status": "error",
            "message": "No segments found for this IDoc."
        }

    return {
        "status": "success",
        "segments": results
    }


# -------------------------------------------------------
# Extract Company Code & Cost Center
# -------------------------------------------------------

def extract_idoc_information(segment_result):
    company_code = ""
    cost_center = ""

    segments = segment_result.get("segments", [])

    for seg in segments:
        segname = seg.get("Segnam", "").strip()
        sdata = seg.get("Sdata", "").strip()

        # -------------------------------
        # Company Code
        # -------------------------------
        if segname == "E1EDK14":
            qualf = sdata[:3]

            if qualf == "003" and not company_code:
                company_code = sdata[3:].strip()

        # -------------------------------
        # Cost Center
        # -------------------------------
        elif segname == "E1EDP02":
            qualf = sdata[:3]

            if qualf == "021" and not cost_center:
                value = sdata[3:].strip()
                cost_center = value.split()[0]

    if not company_code:
        return {
            "status": "error",
            "message": "Company Code not found in the IDoc."
        }

    if not cost_center:
        return {
            "status": "error",
            "message": "Cost Center not found in the IDoc."
        }

    return {
        "status": "success",
        "company_code": company_code,
        "cost_center": cost_center
    }


# -------------------------------------------------------
# Check Cost Center
# -------------------------------------------------------

def check_cost_center(company_code, cost_center):
    sap_cost_center = f"{company_code}{cost_center}"

    data = sap_get(
        COSTCENTER_URL,
        {
            "$filter": f"CostCenter eq '{sap_cost_center}' and ControllingArea eq 'TT01'"
        }
    )

    if data.get("status") == "error":
        return data

    results = data.get("d", {}).get("results", [])

    if not results:
        return {
            "status": "error",
            "message": f"Cost Center {sap_cost_center} not found in SAP."
        }

    return {
        "status": "success",
        "company_code": company_code,
        "cost_center": sap_cost_center
    }


# -------------------------------------------------------
# Fetch CSRF Token
# -------------------------------------------------------

def get_csrf_token(url):
    response = session.get(
        url,
        params={
            "sap-client": SAP_CLIENT,
            "saml2": "disabled"
        },
        headers={
            "x-csrf-token": "Fetch",
            "Accept": "application/json"
        },
        timeout=30
    )

    token = response.headers.get("x-csrf-token")

    if not token:
        return None

    return token


# -------------------------------------------------------
# Generic POST
# -------------------------------------------------------

def sap_post(url, payload):
    token = get_csrf_token(url)

    if not token:
        return {
            "status": "error",
            "message": "Unable to fetch CSRF Token.",
            "response": ""
        }

    try:
        response = session.post(
            url,
            params={
                "sap-client": SAP_CLIENT,
                "saml2": "disabled"
            },
            headers={
                "x-csrf-token": token,
                "Content-Type": "application/json",
                "Accept": "application/json"
            },
            json=payload,
            timeout=120
        )

        if response.status_code not in [200, 201, 204]:
            return {
                "status": "error",
                "status_code": response.status_code,
                "response": response.text
            }

        return {
            "status": "success",
            "status_code": response.status_code,
            "response": response.text
        }

    except requests.exceptions.ReadTimeout:
        return {
            "status": "error",
            "message": "SAP request timed out after 120 seconds.",
            "response": ""
        }

    except Exception as ex:
        return {
            "status": "error",
            "message": str(ex),
            "response": ""
        }


# -------------------------------------------------------
# Build OBCC Payload
# -------------------------------------------------------

def build_obcc_payload(company_code, cost_center):
    sap_cost_center = f"{company_code}{cost_center}"

    payload = {
        "Partnertype": DEFAULT_PARTNER_TYPE,
        "Partnerno": DEFAULT_PARTNER_NO,
        "Companycode": company_code,
        "Assignmentid": cost_center,
        "Description": sap_cost_center,
        "Costcenter": sap_cost_center,
        "Coarea": DEFAULT_CO_AREA,
        "Validfrom": "2026-07-01T00:00:00",
        "Validto": "9999-12-31T00:00:00"
    }

    return payload


# -------------------------------------------------------
# Create OBCC Assignment
# -------------------------------------------------------

def create_obcc_assignment(company_code, cost_center):
    payload = build_obcc_payload(
        company_code,
        cost_center
    )

    return sap_post(
        OBCC_URL,
        payload
    )


# -------------------------------------------------------
# Friendly SAP Error Parser
# -------------------------------------------------------

def format_sap_error(response_text):
    try:
        response = json.loads(response_text)

        error = response.get("error", {})
        inner = error.get("innererror", {})

        errors = []
        warnings = []

        error_map = {
            "already exists":
                "OBCC Assignment already exists.\n"
                "Recommendation: Check the existing OBCC entry before creating again.",

            "duplicate":
                "Duplicate OBCC Assignment detected.\n"
                "Recommendation: Verify the Assignment ID and Partner details.",

            "Costcenter":
                "Invalid Cost Center.\n"
                "Recommendation: Verify the Cost Center value in SAP.",

            "Cost Center":
                "Invalid Cost Center.\n"
                "Recommendation: Verify the Cost Center value in SAP.",

            "Companycode":
                "Invalid Company Code.\n"
                "Recommendation: Verify the Company Code.",

            "Company Code":
                "Invalid Company Code.\n"
                "Recommendation: Verify the Company Code.",

            "Coarea":
                "Invalid Controlling Area.\n"
                "Recommendation: Verify the Controlling Area.",

            "Partnerno":
                "Invalid Partner Number.\n"
                "Recommendation: Verify the Partner Number.",

            "Partnertype":
                "Invalid Partner Type.\n"
                "Recommendation: Verify the Partner Type.",

            "Validfrom":
                "Invalid Valid From date.\n"
                "Recommendation: Check the date format.",

            "Validto":
                "Invalid Valid To date.\n"
                "Recommendation: Check the date format."
        }

        main_message = error.get("message", {}).get("value", "")

        if main_message:
            translated = None

            for key, value in error_map.items():
                if key.lower() in main_message.lower():
                    translated = value
                    break

            if translated is None:
                translated = main_message

            if translated:
                errors.append(translated)

        details = inner.get("errordetails", [])

        for item in details:
            message = item.get("message", "").strip()
            severity = item.get("severity", "").lower()

            translated = None

            for key, value in error_map.items():
                if key.lower() in message.lower():
                    translated = value
                    break

            if translated is None:
                translated = message

            if not translated:
                continue

            if severity == "error":
                errors.append(translated)

            elif severity == "warning":
                warnings.append(translated)

        errors = list(dict.fromkeys(errors))
        warnings = list(dict.fromkeys(warnings))

        output = (
            "========================================\n"
            "        ISSUE RESOLUTION FAILED\n"
            "========================================\n\n"
        )

        if errors:
            output += "❌ Errors\n"
            output += "----------------------------------------\n"

            for i, msg in enumerate(errors, 1):
                output += f"{i}. {msg}\n\n"

        if warnings:
            output += "⚠ Warnings\n"
            output += "----------------------------------------\n"

            for i, msg in enumerate(warnings, 1):
                output += f"{i}. {msg}\n\n"

        if not errors and not warnings:
            output += "Unknown SAP error occurred."

        return output

    except Exception as ex:
        return (
            "========================================\n"
            "        ISSUE RESOLUTION FAILED\n"
            "========================================\n\n"
            "Unable to interpret SAP response.\n\n"
            f"Parser Error: {str(ex)}\n\n"
            "Raw Response:\n"
            f"{response_text}"
        )


# -------------------------------------------------------
# GPT Router
# -------------------------------------------------------

def ai_router(question):
    prompt = """
You are an SAP Rydoo IDoc Self-Healing Agent router.

Return ONLY valid JSON.
No markdown.
No explanation.

Supported action:
- fix_idoc
- unknown

For fixing, analyzing, resolving, repairing, or healing a Rydoo/Expense IDoc, return:

{
  "action": "fix_idoc",
  "idoc_number": ""
}

If user is not asking to fix/analyze/resolve/repair/heal an IDoc, return:

{
  "action": "unknown",
  "idoc_number": ""
}

Examples:

User: Fix Rydoo IDoc 158694
Return:
{
  "action": "fix_idoc",
  "idoc_number": "158694"
}

User: Analyze Rydoo IDoc 158694
Return:
{
  "action": "fix_idoc",
  "idoc_number": "158694"
}

User: Resolve Rydoo IDoc 158694
Return:
{
  "action": "fix_idoc",
  "idoc_number": "158694"
}

User: Fix Expense IDoc 158694
Return:
{
  "action": "fix_idoc",
  "idoc_number": "158694"
}

User: Repair IDoc 158694
Return:
{
  "action": "fix_idoc",
  "idoc_number": "158694"
}

User: Heal IDoc 158694
Return:
{
  "action": "fix_idoc",
  "idoc_number": "158694"
}

Rules:
- Extract only the IDoc number.
- Do not ask for password, token, cookie, or credentials.
- Do not guess missing IDoc number.
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
                "content": question
            }
        ],
        temperature=0,
        max_tokens=300
    )

    text = response.choices[0].message.content.strip()

    try:
        return json.loads(text)

    except Exception:
        return {
            "action": "unknown",
            "idoc_number": ""
        }


# -------------------------------------------------------
# Run Agent
# -------------------------------------------------------

def run_agent(question):
    global pending_action

    original_question = question.strip()
    lower_question = original_question.lower()

        # ==========================================
    # YES - Create OBCC
    # ==========================================
    if (
        pending_action
        and pending_action.get("action") == "create_obcc"
        and lower_question in ["yes", "y", "confirm", "approve", "ok", "go ahead"]
    ):
        action = pending_action
        pending_action = None

        auth_result = check_authorization(
            SAP_USER,
            "RYDOO_OBCC",
            "CREATE"
        )

        if not auth_result.get("authorized"):
            return format_authorization_denied(auth_result)

        result = create_obcc_assignment(
            action["company_code"],
            action["cost_center"]
        )

        if result.get("status") == "success":
            return (
                "========================================\n"
                "        ISSUE RESOLVED\n"
                "========================================\n\n"
                f"IDoc Number      : {action['idoc']}\n"
                f"Company Code     : {action['company_code']}\n"
                f"Cost Center      : {action['cost_center']}\n"
                f"Status           : SUCCESS\n\n"
                "OBCC Assignment created successfully.\n\n"
                "Please reprocess the IDoc in BD87."
            )

        return format_sap_error(
            result.get("response", "")
        )

    
    

    # ==========================================
    # NO - Cancel
    # ==========================================
    if (
        pending_action
        and lower_question in ["no", "n", "cancel", "stop", "reject"]
    ):
        pending_action = None

        return "Cancelled. No changes were made in SAP."

    # ==========================================
    # AI Router
    # ==========================================
    route = ai_router(original_question)

    if route.get("action") != "fix_idoc":
        return (
            "========================================\n"
            "        RYDOO COPILOT\n"
            "========================================\n\n"
            "Please provide a valid Rydoo IDoc number.\n\n"
            "Example:\n"
            "Fix Rydoo IDoc 158694"
        )

    idoc = clean_value(route.get("idoc_number", ""))

    if not idoc:
        return (
            "========================================\n"
            "        RYDOO COPILOT\n"
            "========================================\n\n"
            "IDoc number is missing.\n\n"
            "Example:\n"
            "Fix Rydoo IDoc 158694"
        )

    # ==========================================
    # Read IDoc
    # ==========================================
    segments = read_idoc_segments(idoc)

    if segments.get("status") == "error":
        return (
            "========================================\n"
            "        RYDOO COPILOT\n"
            "========================================\n\n"
            "❌ Unable to read IDoc segments.\n\n"
            f"Reason: {segments.get('message') or segments.get('response')}"
        )

    # ==========================================
    # Extract IDoc Information
    # ==========================================
    info = extract_idoc_information(segments)

    if info.get("status") == "error":
        return (
            "========================================\n"
            "        RYDOO COPILOT\n"
            "========================================\n\n"
            "❌ Unable to extract required IDoc information.\n\n"
            f"Reason: {info.get('message')}"
        )

    # ==========================================
    # Check Cost Center
    # ==========================================
    cc = check_cost_center(
        info["company_code"],
        info["cost_center"]
    )

    if cc.get("status") == "error":
        return (
            "========================================\n"
            "        RYDOO COPILOT\n"
            "========================================\n\n"
            "❌ Cost Center validation failed.\n\n"
            f"Reason: {cc.get('message') or cc.get('response')}"
        )

    # ==========================================
    # Preview Before Creating OBCC
    # ==========================================
    pending_action = {
        "action": "create_obcc",
        "company_code": info["company_code"],
        "cost_center": info["cost_center"],
        "idoc": idoc
    }

    sap_cost_center = f"{info['company_code']}{info['cost_center']}"

    return (
        "========================================\n"
        "        RYDOO COPILOT\n"
        "========================================\n\n"
        "✅ Analysis Completed\n\n"
        f"IDoc Number      : {idoc}\n"
        f"Company Code     : {info['company_code']}\n"
        f"Cost Center      : {info['cost_center']}\n"
        f"SAP Cost Center  : {sap_cost_center}\n\n"
        "----------------------------------------\n\n"
        "Root Cause\n\n"
        "No OBCC Assignment exists.\n\n"
        "----------------------------------------\n\n"
        "Action\n\n"
        "✓ Create OBCC Assignment\n\n"
        "Reply YES to continue.\n"
        "Reply NO to cancel."
    )


# -------------------------------------------------------
# MAIN
# -------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("SAP RYDOO IDOC SELF HEALING AGENT")
    print("=" * 60)

    while True:
        question = input("\nYou : ").strip()

        if question.lower() in ["exit", "quit", "bye"]:
            print("Assistant: Bye")
            break

        print("\nAssistant:\n")
        print(run_agent(question))