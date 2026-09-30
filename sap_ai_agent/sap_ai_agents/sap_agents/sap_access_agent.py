import os
import json
import re
import requests
import urllib3
import sys

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
session.auth = HTTPBasicAuth(SAP_USER, SAP_PASS)
session.verify = False
session.headers.update({"Accept": "application/json"})

# -------------------------------------------------------
# User Access API
# -------------------------------------------------------

USER_ACCESS_URL = (
    f"{SAP_HOST}"
    "/sap/opu/odata/sap/ZUSER_ACCESS_SRV/UserSet"
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


# -------------------------------------------------------
# Common SAP GET
# -------------------------------------------------------

def sap_get(url, params=None):

    query = {
        "sap-client": SAP_CLIENT,
        "$format": "json",
        "saml2": "disabled"
    }

    if params:
        query.update(params)

    response = session.get(
        url,
        params=query,
        timeout=60
    )

    if response.status_code != 200:
        return {
            "status": "error",
            "response": response.text
        }

    return response.json()


# -------------------------------------------------------
# Get User Details
# -------------------------------------------------------

def get_user_details(username):

    username = clean_value(username).upper()

    url = f"{USER_ACCESS_URL}('{username}')"

    data = sap_get(url)

    if data.get("status") == "error":
        return data

    user = data.get("d", {})

    if not user:
        return {
            "status": "error",
            "message": f"User {username} not found."
        }

    return {
        "status": "success",
        "username": user.get("UserName", ""),
        "fullname": user.get("FullName", ""),
        "locked": user.get("Locked", ""),
        "usertype": user.get("UserType", ""),
        "lastlogon": user.get("LastLogon", ""),
        "roles": user.get("Roles", ""),
        "profiles": user.get("Profiles", ""),
        "roledetails": user.get("RoleDetails", ""),
        "usergroup": user.get("UserGroup", "")
    }


# -------------------------------------------------------
# User Summary
# -------------------------------------------------------

def format_user_summary(user):

    role_list = [
        r for r in user["roles"].split("|")
        if r.strip()
    ]

    profile_list = [
        p for p in user["profiles"].split("|")
        if p.strip()
    ]

    if user["usergroup"].upper() == "OBSOLETE":
        lock_status = "Obsolete"

    elif user["locked"].upper() == "TRUE":
        lock_status = "Locked"

    else:
        lock_status = "Active"

    return f"""
========================================
        SAP ACCESS COPILOT
========================================

User              : {user['username']}

Full Name         : {user['fullname']}

User Type         : {user['usertype']}

Status            : {lock_status}

Roles Assigned    : {len(role_list)}

Profiles Assigned : {len(profile_list)}

----------------------------------------

AI Summary

User account found

{len(role_list)} role(s) assigned

{len(profile_list)} profile(s) assigned

========================================
"""


# -------------------------------------------------------
# List Roles
# -------------------------------------------------------

COMPOSITE_ROLE_PREFIXES = ("ZC", "JE", "J")


def list_roles(user):

    roles = [
        r.strip()
        for r in user["roles"].split("|")
        if r.strip()
    ]

    composite_roles = []
    single_roles = []

    for role in roles:

        role_upper = role.upper()

        if role_upper.startswith(COMPOSITE_ROLE_PREFIXES):
            composite_roles.append(role)
        else:
            single_roles.append(role)

    output = """
========================================
          SAP ACCESS
========================================

COMPOSITE ROLES
----------------------------------------
"""

    if composite_roles:

        for i, role in enumerate(composite_roles, start=1):
            output += f"{i}. {role}\n"

    else:
        output += "No Composite Roles Assigned\n"

    output += f"""

Total Composite Roles : {len(composite_roles)}

========================================

SINGLE ROLES
----------------------------------------
"""

    if single_roles:

        for i, role in enumerate(single_roles, start=1):
            output += f"{i}. {role}\n"

    else:
        output += "No Single Roles Assigned\n"

    output += f"""

Total Single Roles : {len(single_roles)}

========================================
"""

    return output


# -------------------------------------------------------
# Check User Role
# -------------------------------------------------------

def check_user_role(user, role):

    role = role.upper().strip()

    roles = [
        r.upper().strip()
        for r in user["roles"].split("|")
        if r.strip()
    ]

    assigned = role in roles

    return f"""
========================================
        ROLE ASSIGNMENT CHECK
========================================

User : {user['username']}

Role : {role}

Status : {"Assigned" if assigned else "Not Assigned"}

========================================
"""


# -------------------------------------------------------
# List Profiles
# -------------------------------------------------------

def list_profiles(user):

    profiles = [
        p.strip()
        for p in user["profiles"].split("|")
        if p.strip()
    ]

    output = """
========================================
         USER PROFILES
========================================

"""

    for i, profile in enumerate(profiles, start=1):
        output += f"{i}. {profile}\n"

    output += f"\nTotal Profiles : {len(profiles)}"

    return output


# -------------------------------------------------------
# Check Lock Status
# -------------------------------------------------------

def check_locked(user):

    status = (
        "Locked"
        if user["locked"].upper() == "TRUE"
        else "Active"
    )

    return f"""
========================================
          ACCOUNT STATUS
========================================

User Name : {user['username']}

Full Name : {user['fullname']}

Status    : {status}

========================================
"""


# -------------------------------------------------------
# Fallback Router
# -------------------------------------------------------

def fallback_router(user_input):

    text = user_input.upper().strip()

    username = ""

    words = re.findall(r"\b[A-Z0-9_]{3,}\b", text)

    ignore_words = [
        "SHOW", "ACCESS", "LIST", "ROLES", "ROLE", "PROFILE", "PROFILES",
        "USER", "LOCKED", "LOCK", "STATUS", "DOES", "HAVE", "THE", "FOR", "OF", "ME"
    ]

    for word in words:
        if word not in ignore_words:
            username = word
            break

    if "PROFILE" in text:
        return {
            "intent": "LIST_PROFILES",
            "username": username
        }

    if "LOCK" in text:
        return {
            "intent": "CHECK_LOCK",
            "username": username
        }

    if "DOES" in text and "HAVE" in text:
        role = ""

        match = re.search(r"HAVE\s+([A-Z0-9_]+)", text)

        if match:
            role = match.group(1)

        return {
            "intent": "CHECK_ROLE",
            "username": username,
            "role": role
        }

    if "COMPOSITE" in text:
        return {
            "intent": "LIST_COMPOSITE_ROLES",
            "username": username
        }

    if "SINGLE" in text:
        return {
            "intent": "LIST_SINGLE_ROLES",
            "username": username
        }

    if "ROLE" in text:
        return {
            "intent": "LIST_ROLES",
            "username": username
        }

    return {
        "intent": "USER_SUMMARY",
        "username": username
    }


# -------------------------------------------------------
# Composite Roles
# -------------------------------------------------------

def list_composite_roles(user):

    composite_roles = []

    for item in user["roledetails"].split("|"):

        if not item:
            continue

        role_name, role_type = item.split("~")

        if role_type == "C":
            composite_roles.append(role_name)

    output = """
========================================
      COMPOSITE ROLES
========================================

"""

    if composite_roles:

        for i, role in enumerate(composite_roles, 1):
            output += f"{i}. {role}\n"

    else:
        output += "No Composite Roles Assigned\n"

    output += f"\nTotal Composite Roles : {len(composite_roles)}"

    return output


# -------------------------------------------------------
# Single Roles
# -------------------------------------------------------

def list_single_roles(user):

    single_roles = []

    for item in user["roledetails"].split("|"):

        if not item:
            continue

        role_name, role_type = item.split("~")

        if role_type == "S":
            single_roles.append(role_name)

    output = """
========================================
        SINGLE ROLES
========================================

"""

    if single_roles:

        for i, role in enumerate(single_roles, 1):
            output += f"{i}. {role}\n"

    else:
        output += "No Single Roles Assigned\n"

    output += f"\nTotal Single Roles : {len(single_roles)}"

    return output


# -------------------------------------------------------
# GPT Router
# -------------------------------------------------------

def ai_router(user_input):

    prompt = f"""
You are an SAP Access Copilot.

Return ONLY valid JSON.
No markdown.
No explanation.

Supported intents:

- USER_SUMMARY
- LIST_ROLES
- LIST_COMPOSITE_ROLES
- LIST_SINGLE_ROLES
- LIST_PROFILES
- CHECK_ROLE
- CHECK_LOCK

For CHECK_ROLE also extract the role name.

Examples:

User: Show access of VASUM
Output:
{{"intent":"USER_SUMMARY","username":"VASUM"}}

User: show me the access of vasum
Output:
{{"intent":"USER_SUMMARY","username":"VASUM"}}

User: List roles of RNHO
Output:
{{"intent":"LIST_ROLES","username":"RNHO"}}

User: Show profiles for VASUM
Output:
{{"intent":"LIST_PROFILES","username":"VASUM"}}

User: Does VASUM have SAP_ALL?
Output:
{{"intent":"CHECK_ROLE","username":"VASUM","role":"SAP_ALL"}}

User: Is VASUM locked?
Output:
{{"intent":"CHECK_LOCK","username":"VASUM"}}

User: Show composite roles of VASUM
Output:
{{"intent":"LIST_COMPOSITE_ROLES","username":"VASUM"}}

User: Show single roles of VASUM
Output:
{{"intent":"LIST_SINGLE_ROLES","username":"VASUM"}}

User Request:
{user_input}
"""

    try:
        response = azure_client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            temperature=0,
            max_tokens=200,
            messages=[
                {
                    "role": "system",
                    "content": "Return only valid JSON. No markdown. No explanation."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        response_text = response.choices[0].message.content

        if not response_text:
            return fallback_router(user_input)

        response_text = response_text.strip()
        response_text = response_text.replace("```json", "").replace("```", "").strip()

        return json.loads(response_text)

    except Exception:
        return fallback_router(user_input)


# -------------------------------------------------------
# Access Agent
# -------------------------------------------------------

def run_agent(user_input):

    intent_data = ai_router(user_input)

    intent = intent_data.get("intent", "USER_SUMMARY")
    username = clean_value(intent_data.get("username", "")).upper()

    if not username:
        return (
            "========================================\n"
            "        SAP ACCESS COPILOT\n"
            "========================================\n\n"
            "Please provide a valid SAP user ID.\n\n"
            "Example:\n"
            "Show access of VASUM"
        )

    # -------------------------------------------------------
    # Authorization Check - User Access Display
    # -------------------------------------------------------
    auth_result = check_authorization(
        SAP_USER,
        "USER_ACCESS",
        "DISPLAY"
    )

    if not auth_result.get("authorized"):
        return format_authorization_denied(auth_result)

    user = get_user_details(username)

    if user["status"] == "error":
        return user.get("message", "Unable to retrieve user details.")

    if intent == "USER_SUMMARY":
        return format_user_summary(user)

    elif intent == "LIST_ROLES":
        return list_roles(user)

    elif intent == "LIST_PROFILES":
        return list_profiles(user)

    elif intent == "CHECK_LOCK":
        return check_locked(user)

    elif intent == "CHECK_ROLE":
        return check_user_role(
            user,
            intent_data.get("role", "")
        )

    elif intent == "LIST_COMPOSITE_ROLES":
        return list_composite_roles(user)

    elif intent == "LIST_SINGLE_ROLES":
        return list_single_roles(user)

    return "Sorry, I couldn't understand your request."


if __name__ == "__main__":

    while True:

        question = input("\nAsk: ")

        if question.lower() in ["exit", "quit"]:
            break

        print(run_agent(question))