import os
import json
import re
import requests
import urllib3
import sys

from datetime import datetime
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

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

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

# -------------------------------------------------------
# Azure OpenAI
# -------------------------------------------------------

azure_client = AzureOpenAI(
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    api_key=AZURE_OPENAI_API_KEY,
    api_version=AZURE_OPENAI_API_VERSION
)

# -------------------------------------------------------
# SAP Session
# -------------------------------------------------------

session = requests.Session()

session.auth = HTTPBasicAuth(
    SAP_USER,
    SAP_PASS
)

session.verify = False

session.headers.update({
    "Accept": "application/json"
})

# -------------------------------------------------------
# Business Partner URL
# -------------------------------------------------------

BP_URL = (
    f"{SAP_HOST}"
    "/sap/opu/odata/sap/API_BUSINESS_PARTNER/A_BusinessPartner"
)

# -------------------------------------------------------
# Helper
# -------------------------------------------------------

def clean_value(value):

    if value is None:
        return ""

    value = str(value).strip()
    value = re.sub(r"\s+", "", value)

    return value


COUNTRIES = {
    "BE": "Belgium",
    "DE": "Germany",
    "NL": "Netherlands",
    "CN": "China",
    "US": "United States",
    "IN": "India",
    "RO": "Romania",
    "TW": "Taiwan",
    "KR": "South Korea",
    "JP": "Japan"
}


def format_sap_date(value):

    if not value:
        return "-"

    match = re.search(r"/Date\((\d+)", value)

    if not match:
        return value

    timestamp = int(match.group(1)) / 1000

    return datetime.fromtimestamp(timestamp).strftime("%d-%b-%Y")


# -------------------------------------------------------
# Common SAP GET
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
# Get Business Partner
# -------------------------------------------------------

def get_business_partner(bp_number):

    bp_number = clean_value(bp_number)

    if not bp_number:
        return (
            "========================================\n"
            "      BUSINESS PARTNER COPILOT\n"
            "========================================\n\n"
            "Business Partner number is missing.\n\n"
            "Example:\n"
            "Show BP 305"
        )

    data = sap_get(
        BP_URL,
        {
            "$filter": f"BusinessPartner eq '{bp_number}'",
            "$expand": "to_BusinessPartnerAddress,to_Supplier,to_Customer"
        }
    )

    if data.get("status") == "error":

        return (
            "========================================\n"
            "      BUSINESS PARTNER COPILOT\n"
            "========================================\n\n"
            "SAP Error occurred while reading Business Partner.\n\n"
            f"Status Code : {data.get('status_code')}\n"
            f"Response    : {data.get('response') or data.get('message')}"
        )

    results = data.get("d", {}).get("results", [])

    if not results:

        return (
            "========================================\n"
            "      BUSINESS PARTNER COPILOT\n"
            "========================================\n\n"
            f"Business Partner {bp_number} not found."
        )

    bp = results[0]

    supplier = "Yes" if bp.get("Supplier") else "No"
    customer = "Yes" if bp.get("Customer") else "No"
    blocked = "Yes" if bp.get("BusinessPartnerIsBlocked") else "No"

    category = bp.get("BusinessPartnerCategory", "")

    if category == "1":
        category = "Person"

    elif category == "2":
        category = "Organization"

    elif category == "3":
        category = "Group"

    else:
        category = category or "-"

    # ----------------------------
    # Address
    # ----------------------------

    street = "-"
    city = "-"
    postal = "-"
    country = "-"

    addresses = bp.get("to_BusinessPartnerAddress", {}).get("results", [])

    if addresses:

        addr = addresses[0]

        street = addr.get("StreetName", "").rstrip(",") or "-"
        city = addr.get("CityName", "") or "-"
        postal = addr.get("PostalCode", "") or "-"

        country_code = addr.get("Country", "")

        country = (
            f"{COUNTRIES.get(country_code, country_code)} ({country_code})"
            if country_code else "-"
        )

    output = f"""
========================================
      BUSINESS PARTNER COPILOT
========================================

Business Partner
----------------------------------------
Business Partner : {bp.get('BusinessPartner')}

Name             : {bp.get('BusinessPartnerFullName')}

Category         : {category}

Grouping         : {bp.get('BusinessPartnerGrouping')}

--------------- Business Roles ----------------

Supplier         : {supplier}

Customer         : {customer}

Blocked          : {blocked}

--------------- General Information ------------

Search Term      : {bp.get('SearchTerm1')}

Created By       : {bp.get('CreatedByUser')}

Created On       : {format_sap_date(bp.get('CreationDate'))}

--------------- Address ------------------------

Street           : {street}

City             : {city}

Postal Code      : {postal}

Country          : {country}

--------------- AI Summary ---------------------

Active Business Partner

Supplier Role : {supplier}

Customer Role : {customer}

Blocked       : {blocked}

========================================
"""

    return output


# -------------------------------------------------------
# GPT Router
# -------------------------------------------------------

def ai_router(question):

    prompt = """
You are an SAP Business Partner AI Assistant.

Return ONLY valid JSON.
No markdown.
No explanation.

Actions:
- get_business_partner
- unknown

For Business Partner lookup return:

{
    "action": "get_business_partner",
    "business_partner": ""
}

Rules:
- If the user asks about a Business Partner, BP, Supplier, or Customer, return get_business_partner.
- Extract ONLY the Business Partner number.
- Do not guess the Business Partner number.
- Never ask for password, token, cookie, or credentials.

Supported user examples:

User: Show Business Partner 1000001234
Return:
{
    "action":"get_business_partner",
    "business_partner":"1000001234"
}

User: Display BP 20000111
Return:
{
    "action":"get_business_partner",
    "business_partner":"20000111"
}

User: Tell me about BP 305
Return:
{
    "action":"get_business_partner",
    "business_partner":"305"
}

User: Who is Business Partner 305
Return:
{
    "action":"get_business_partner",
    "business_partner":"305"
}

User: Give me details of BP 305
Return:
{
    "action":"get_business_partner",
    "business_partner":"305"
}

User: Show supplier 305
Return:
{
    "action":"get_business_partner",
    "business_partner":"305"
}

User: Show customer 305
Return:
{
    "action":"get_business_partner",
    "business_partner":"305"
}

User: Display BP 305
Return:
{
    "action":"get_business_partner",
    "business_partner":"305"
}

User: Get Business Partner 305
Return:
{
    "action":"get_business_partner",
    "business_partner":"305"
}

User: Show BP 305
Return:
{
    "action":"get_business_partner",
    "business_partner":"305"
}

If no Business Partner number is found return:

{
    "action":"unknown",
    "business_partner":""
}
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
        max_tokens=200
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
            "business_partner": ""
        }


# -------------------------------------------------------
# Run Agent
# -------------------------------------------------------

def run_agent(question):

    route = ai_router(question)

    action = route.get("action", "unknown")

    if action == "get_business_partner":

        # -------------------------------------------------------
        # Authorization Check - Business Partner Display
        # -------------------------------------------------------
        auth_result = check_authorization(
            SAP_USER,
            "BUSINESS_PARTNER",
            "DISPLAY"
        )

        if not auth_result.get("authorized"):
            return format_authorization_denied(auth_result)

        bp_number = route.get("business_partner", "")

        return get_business_partner(bp_number)

    return (
        "========================================\n"
        "      BUSINESS PARTNER COPILOT\n"
        "========================================\n\n"
        "Sorry, I couldn't understand your request.\n\n"
        "You can ask like:\n"
        "Show BP 305\n"
        "Tell me about BP 305\n"
        "Show supplier 305\n"
        "Show customer 305"
    )


# -------------------------------------------------------
# Main
# -------------------------------------------------------

if __name__ == "__main__":

    print("\n====================================")
    print(" SAP Business Partner Agent Started ")
    print("====================================\n")

    while True:

        question = input("You : ").strip()

        if question.lower() in ["exit", "quit", "bye"]:

            print("\nAssistant : Bye\n")
            break

        print("\nAssistant:\n")

        answer = run_agent(question)

        print(answer)

        print()