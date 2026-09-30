"""
=========================================================
SAP Enterprise AI Assistant
Firefighter Review Agent
Version : 3.0

Controller identity is resolved ONLY from the
authenticated Microsoft Entra identity.

TEST_CONTROLLER has been removed.
=========================================================
"""

import os
import json
import logging
import re
import requests
import urllib3

from urllib.parse import quote
from dotenv import load_dotenv
from openai import AzureOpenAI
from requests.auth import HTTPBasicAuth
from datetime import datetime

try:
    from .auth_helper import check_authorization
except ImportError:
    from auth_helper import check_authorization


urllib3.disable_warnings()

print("Current Working Directory:", os.getcwd())


# -------------------------------------------------------
# Load Environment Variables
# -------------------------------------------------------

load_dotenv()

AZURE_OPENAI_ENDPOINT = os.getenv(
    "AZURE_OPENAI_ENDPOINT",
    ""
).strip().rstrip("/")

AZURE_OPENAI_API_KEY = os.getenv(
    "AZURE_OPENAI_API_KEY",
    ""
).strip()

AZURE_OPENAI_DEPLOYMENT = os.getenv(
    "AZURE_OPENAI_DEPLOYMENT",
    ""
).strip()

AZURE_OPENAI_API_VERSION = os.getenv(
    "AZURE_OPENAI_API_VERSION",
    ""
).strip()

SAP_HOST = os.getenv(
    "SAP_HOST",
    ""
).strip().rstrip("/")

SAP_CLIENT = os.getenv(
    "SAP_CLIENT",
    ""
).strip()

SAP_OAUTH_CLIENT_ID = os.getenv(
    "SAP_OAUTH_CLIENT_ID",
    ""
).strip()

SAP_OAUTH_CLIENT_SECRET = os.getenv(
    "SAP_OAUTH_CLIENT_SECRET",
    ""
).strip()

SAP_OAUTH_TOKEN_URL = os.getenv(
    "SAP_OAUTH_TOKEN_URL",
    f"{SAP_HOST}/sap/bc/sec/oauth2/token"
    f"?sap-client={SAP_CLIENT}"
).strip()

SAP_OAUTH_SCOPE = os.getenv(
    "SAP_OAUTH_SCOPE",
    "ZFF_REVIEW_SRV_0001 ZFF_ACTIVITY_SRV_0001"
).strip()

ENTRA_CONTROLLER_MAP = os.getenv(
    "ENTRA_CONTROLLER_MAP",
    ""
).strip()

FIREFIGHTER_REVIEW_BATCH_SIZE = 4


class SapControllerResolutionError(Exception):
    def __init__(self, public_message, status_code=502):
        super().__init__(public_message)
        self.public_message = public_message
        self.status_code = status_code


# -------------------------------------------------------
# Resolve Authenticated SAP Controller
# -------------------------------------------------------

def get_authenticated_controller(authenticated_identity):
    """
    Resolve the SAP Firefighter Controller from the
    authenticated Microsoft Entra identity.

    The request body is never trusted.
    """

    if not authenticated_identity:
        raise Exception(
            "Authenticated Entra identity is missing."
        )

    if not authenticated_identity.get(
        "authenticated",
        False
    ):
        raise Exception(
            "Authenticated Entra identity is invalid."
        )

    controller = (
        authenticated_identity.get(
            "sap_controller"
        )
        or ""
    ).strip().upper()

    if not controller:
        raise Exception(
            "Authenticated Entra user is not mapped "
            "to a SAP Firefighter Controller."
        )

    return controller


def resolve_sap_controller(authenticated_identity):
    """Resolve the Firefighter controller from trusted Entra identity mapping."""
    if not isinstance(authenticated_identity, dict):
        raise SapControllerResolutionError(
            "Authenticated identity is invalid.",
            401
        )

    if not authenticated_identity.get("authenticated"):
        raise SapControllerResolutionError(
            "Authentication is required.",
            401
        )

    email = str(
        authenticated_identity.get("preferred_username")
        or ""
    ).strip().lower()
    if not email:
        raise SapControllerResolutionError(
            "Authenticated identity does not contain a corporate email.",
            401
        )

    if not ENTRA_CONTROLLER_MAP:
        raise SapControllerResolutionError(
            "Entra controller mapping is not configured.",
            502
        )

    try:
        mapping = json.loads(ENTRA_CONTROLLER_MAP)
    except json.JSONDecodeError:
        raise SapControllerResolutionError(
            "Entra controller mapping is invalid.",
            502
        )

    if not isinstance(mapping, dict):
        raise SapControllerResolutionError(
            "Entra controller mapping is invalid.",
            502
        )

    normalized_mapping = {}

    for mapped_email, controller in mapping.items():

        if (
            not isinstance(mapped_email, str)
            or not isinstance(controller, str)
            or not mapped_email.strip()
            or not controller.strip()
        ):
            raise SapControllerResolutionError(
                "Entra controller mapping is invalid.",
                502
            )

        normalized_mapping[
            mapped_email.strip().lower()
        ] = controller.strip().upper()

    controller = normalized_mapping.get(email)

    if not controller:
        raise SapControllerResolutionError(
            "Authenticated user is not registered as a SAP Controller.",
            403
        )

    logging.info(
        "SAP controller resolved for authenticated identity %s: %s",
        f"{email[:2]}***{email[-2:]}",
        controller
    )
    return controller


# -------------------------------------------------------
# SAP Firefighter URLs
# -------------------------------------------------------

FF_REVIEW_URL = (
    f"{SAP_HOST}/sap/opu/odata/sap/ZFF_REVIEW_SRV/"
    f"PendingReviewSet?$format=json&$top=1000"
    f"&saml2=disabled&sap-client={SAP_CLIENT}"
)

FF_ACTIVITY_URL = (
    f"{SAP_HOST}/sap/opu/odata/sap/ZFF_ACTIVITY_SRV/"
    f"FFActS?$format=json&$top=1000"
    f"&saml2=disabled&sap-client={SAP_CLIENT}"
)

CONTROLLER_ASSIGNMENT_URL = (
    f"{SAP_HOST}/sap/opu/odata/sap/ZFF_REVIEW_SRV/"
    f"ControllerAssignmentSet?$format=json&$top=1000"
    f"&saml2=disabled&sap-client={SAP_CLIENT}"
)


# -------------------------------------------------------
# Azure OpenAI Client
# -------------------------------------------------------

azure_client = AzureOpenAI(
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    api_key=AZURE_OPENAI_API_KEY,
    api_version=AZURE_OPENAI_API_VERSION
)


# -------------------------------------------------------
# URL Filter Helper
# -------------------------------------------------------

def add_odata_filter(url, filter_expression):

    if not filter_expression:
        return url

    encoded_filter = quote(
        filter_expression,
        safe=""
    )

    return f"{url}&$filter={encoded_filter}"


# -------------------------------------------------------
# SAP OAuth 2.0 Token Cache
# -------------------------------------------------------

SAP_ACCESS_TOKEN = None
SAP_TOKEN_EXPIRES_AT = 0


def get_sap_access_token():

    global SAP_ACCESS_TOKEN
    global SAP_TOKEN_EXPIRES_AT

    current_time = datetime.now().timestamp()

    # Reuse the cached token when it is still valid.
    if (
        SAP_ACCESS_TOKEN
        and current_time < SAP_TOKEN_EXPIRES_AT - 60
    ):
        return SAP_ACCESS_TOKEN

    response = None

    try:

        response = requests.post(
            SAP_OAUTH_TOKEN_URL,

            auth=HTTPBasicAuth(
                SAP_OAUTH_CLIENT_ID,
                SAP_OAUTH_CLIENT_SECRET
            ),

            data={
                "grant_type": "client_credentials",
                "scope": SAP_OAUTH_SCOPE
            },

            headers={
                "Accept": "application/json",
                "Content-Type":
                    "application/x-www-form-urlencoded"
            },

            verify=False,
            timeout=60
        )

        response.raise_for_status()

        token_data = response.json()

        SAP_ACCESS_TOKEN = token_data["access_token"]

        expires_in = int(
            token_data.get("expires_in", 3600)
        )

        SAP_TOKEN_EXPIRES_AT = (
            current_time + expires_in
        )

        print(
            "SAP OAuth token obtained successfully."
        )

        return SAP_ACCESS_TOKEN

    except Exception as ex:

        error_response = (
            response.text
            if response is not None
            else ""
        )

        raise Exception(
            f"SAP OAuth token request failed: "
            f"{str(ex)} | {error_response}"
        )


# -------------------------------------------------------
# Generic SAP GET using OAuth 2.0
# -------------------------------------------------------

def sap_get(url):

    response = None

    try:

        access_token = get_sap_access_token()

        response = requests.get(
            url,

            headers={
                "Authorization":
                    f"Bearer {access_token}",
                "Accept": "application/json"
            },

            verify=False,
            timeout=60
        )

        response.raise_for_status()

        return {
            "status": "success",
            "data": response.json()
        }

    except requests.exceptions.HTTPError as ex:

        return {
            "status": "error",
            "message": f"SAP HTTP Error: {str(ex)}",
            "response": (
                response.text
                if response is not None
                else ""
            )
        }

    except requests.exceptions.ConnectionError:

        return {
            "status": "error",
            "message": (
                "Unable to connect to SAP host. "
                "Please check VPN, DNS, SAP_HOST, "
                "and network connectivity."
            )
        }

    except requests.exceptions.Timeout:

        return {
            "status": "error",
            "message": "SAP request timed out."
        }

    except Exception as ex:

        return {
            "status": "error",
            "message": f"Unexpected SAP error: {str(ex)}"
        }


# -------------------------------------------------------
# Get Firefighter Sessions
# -------------------------------------------------------

def get_firefighter_sessions(user=None, connector=None):

    url = FF_REVIEW_URL

    filters = []

    if user:
        filters.append(
            f"FirefighterUser eq '{user}'"
        )

    if connector:
        filters.append(
            f"Connector eq '{connector}'"
        )

    if filters:
        filter_expression = " and ".join(filters)
        url = add_odata_filter(
            url,
            filter_expression
        )

    result = sap_get(url)

    if result.get("status") == "error":
        raise Exception(result.get("message"))

    data = result.get("data", {})

    return data.get("d", {}).get("results", [])


# -------------------------------------------------------
# Get Firefighter Activities
# -------------------------------------------------------

def get_firefighter_activities(
    user=None,
    connector=None,
    transaction=None
):

    url = FF_ACTIVITY_URL

    filters = []

    if user:
        filters.append(f"FFUser eq '{user}'")

    if connector:
        filters.append(f"Connector eq '{connector}'")

    if transaction:
        filters.append(f"Action eq '{transaction}'")

    if filters:
        filter_expression = " and ".join(filters)
        url = add_odata_filter(
            url,
            filter_expression
        )

    result = sap_get(url)

    if result.get("status") == "error":
        raise Exception(result.get("message"))

    data = result.get("data", {})

    return data.get("d", {}).get("results", [])


# -------------------------------------------------------
# Get Controller Assignments
# -------------------------------------------------------

def get_controller_assignments(
    user_role=None,
    connector=None
):

    url = CONTROLLER_ASSIGNMENT_URL

    filters = []

    if user_role:
        filters.append(f"UserRole eq '{user_role}'")

    if connector:
        filters.append(f"Connector eq '{connector}'")

    if filters:
        filter_expression = " and ".join(filters)
        url = add_odata_filter(
            url,
            filter_expression
        )

    result = sap_get(url)

    if result.get("status") == "error":
        raise Exception(result.get("message"))

    data = result.get("data", {})

    return data.get("d", {}).get("results", [])


# -------------------------------------------------------
# Get Firefighter Scope for Controller
# -------------------------------------------------------

def get_controller_firefighter_scope(controller):

    if not controller:
        raise Exception(
            "Authenticated Controller identity is missing."
        )

    controller = controller.strip().upper()

    assignments = get_controller_assignments()

    if not assignments:
        return []

    scope = []

    for assignment in assignments:

        assignment_controller = (
            assignment.get("Controller") or ""
        ).strip().upper()

        if assignment_controller != controller:
            continue

        firefighter_id = (
            assignment.get("UserRole") or ""
        ).strip().upper()

        connector = (
            assignment.get("Connector") or ""
        ).strip().upper()

        if not firefighter_id or not connector:
            continue

        scope.append({
            "FirefighterId": firefighter_id,
            "Connector": connector
        })

    return scope


# -------------------------------------------------------
# Filter Sessions by Controller Scope
# -------------------------------------------------------

def filter_sessions_by_scope(sessions, scope):

    if not sessions:
        return []

    if not scope:
        return []

    allowed = {
        (
            item["FirefighterId"],
            item["Connector"]
        )
        for item in scope
    }

    filtered_sessions = []

    for session in sessions:

        firefighter_id = (
            session.get("FirefighterId") or ""
        ).strip().upper()

        connector = (
            session.get("Connector") or ""
        ).strip().upper()

        key = (
            firefighter_id,
            connector
        )

        if key in allowed:
            filtered_sessions.append(session)

    return filtered_sessions


# -------------------------------------------------------
# Filter Activities Using Authorized Sessions
# -------------------------------------------------------

def filter_activities_by_authorized_sessions(
    activities,
    authorized_sessions
):

    if not activities:
        return []

    if not authorized_sessions:
        return []

    allowed_users = set()

    for session in authorized_sessions:

        firefighter_user = (
            session.get("FirefighterUser") or ""
        ).strip().upper()

        connector = (
            session.get("Connector") or ""
        ).strip().upper()

        if firefighter_user and connector:
            allowed_users.add(
                (
                    firefighter_user,
                    connector
                )
            )

    filtered_activities = []

    for activity in activities:

        activity_user = (
            activity.get("FFUser") or ""
        ).strip().upper()

        connector = (
            activity.get("Connector") or ""
        ).strip().upper()

        key = (
            activity_user,
            connector
        )

        if key in allowed_users:
            filtered_activities.append(activity)

    return filtered_activities


# -------------------------------------------------------
# Attach Controller to Firefighter Sessions
# -------------------------------------------------------

def attach_authenticated_controller(
    sessions,
    controller
):

    controller = (
        controller or ""
    ).strip().upper()

    for session in sessions:
        session["AuthenticatedController"] = controller

    return sessions


# -------------------------------------------------------
# Sanitized Authorization Denied Message
# -------------------------------------------------------

def _safe_authorization_denied_message(auth_result):
    """
    Return a safe, generic authorization-denied message for the
    frontend.

    format_authorization_denied() (auth_helper.py) includes SAP
    URLs, raw response bodies, CSRF token details, and other
    OData internals meant for local debugging. Those details are
    logged server-side only here and are never returned to the
    caller.
    """

    logging.warning(
        "Firefighter authorization denied. Details: %s",
        {
            "message": auth_result.get("message"),
            "status_code": auth_result.get("status_code"),
            "csrf_error": auth_result.get("csrf_error"),
            "auth_error": auth_result.get("auth_error"),
            "error": auth_result.get("error")
        }
    )

    return (
        "========================================\n"
        "        AUTHORIZATION CHECK FAILED\n"
        "========================================\n\n"
        "Authorization denied for this request.\n\n"
        "No SAP data was changed or displayed."
    )


# -------------------------------------------------------
# Get Controller-Authorized Firefighter Data
# -------------------------------------------------------

def get_authorized_controller_data(
    controller,
    authenticated_email
):
    """
    Single security gate for every Firefighter action.

    Performs:
    1. SAP Firefighter authorization check
    2. Controller scope resolution
    3. Session filtering
    4. Activity filtering through authorized sessions
    """

    controller = (
        controller or ""
    ).strip().upper()

    if not controller:
        raise Exception(
            "Authenticated Controller identity is missing."
        )

    # ---------------------------------------------------
    # SAP Firefighter authorization
    # ---------------------------------------------------

    auth_result = check_authorization(
        authenticated_email,
        "FIREFIGHTER",
        "DISPLAY"
    )

    if not auth_result.get(
        "authorized",
        False
    ):
        raise Exception(
            _safe_authorization_denied_message(
                auth_result
            )
        )

    # ---------------------------------------------------
    # Controller-specific Firefighter scope
    # ---------------------------------------------------

    scope = get_controller_firefighter_scope(
        controller
    )

    if not scope:
        raise Exception(
            f"No Firefighter assignments found "
            f"for Controller {controller}."
        )

    # ---------------------------------------------------
    # Get SAP data
    # ---------------------------------------------------

    sessions = get_firefighter_sessions()

    activities = get_firefighter_activities()

    # ---------------------------------------------------
    # Filter sessions
    # ---------------------------------------------------

    authorized_sessions = filter_sessions_by_scope(
        sessions,
        scope
    )

    # ---------------------------------------------------
    # Filter activities through authorized sessions
    # ---------------------------------------------------

    authorized_activities = (
        filter_activities_by_authorized_sessions(
            activities,
            authorized_sessions
        )
    )

    logging.info(
        "Controller %s authorization scope=%s sessions=%s activities=%s",
        controller,
        len(scope),
        len(authorized_sessions),
        len(authorized_activities)
    )

    # ---------------------------------------------------
    # Attach authenticated controller for context only
    # ---------------------------------------------------

    authorized_sessions = (
        attach_authenticated_controller(
            authorized_sessions,
            controller
        )
    )

    return (
        authorized_sessions,
        authorized_activities,
        scope
    )


# -------------------------------------------------------
# Safe JSON Parser
# -------------------------------------------------------

def safe_json_loads(text):

    if not text:
        return {"action": "unknown"}

    text = text.strip()

    text = (
        text
        .replace("```json", "")
        .replace("```", "")
        .strip()
    )

    try:
        return json.loads(text)

    except Exception:
        return {"action": "unknown"}


# -------------------------------------------------------
# AI Router
# -------------------------------------------------------

def ai_router(question):

    prompt = """
You are the SAP Enterprise Firefighter AI Router.

Your job is to identify the user's intent and extract entities.

Return ONLY valid JSON.

Supported actions:

1. review_all
2. review_user
3. pending_reviews
4. review_transaction
5. review_connector
6. summarize
7. risk_analysis
8. approval
9. unknown

Extract entities whenever possible.

Examples

User:
Review firefighter user GUPTARO

Response
{
    "action":"review_user",
    "user":"GUPTARO"
}

User:
Show pending firefighter reviews

Response
{
    "action":"pending_reviews"
}

User:
Show FB01 activities

Response
{
    "action":"review_transaction",
    "transaction":"FB01"
}

User:
Show connector T4PCLNT100

Response
{
    "action":"review_connector",
    "connector":"T4PCLNT100"
}

User:
Analyze all firefighter sessions

Response
{
    "action":"review_all"
}

User:
Can I approve this session?

Response
{
    "action":"approval"
}

User:
Summarize firefighter sessions

Response
{
    "action":"summarize"
}

User:
Analyze firefighter risk

Response
{
    "action":"risk_analysis"
}

Everything else

{
    "action":"unknown"
}

Return ONLY JSON.
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
            max_tokens=150
        )

        text = (
            response.choices[0]
            .message.content.strip()
        )

        return safe_json_loads(text)

    except Exception:
        return {"action": "unknown"}


# -------------------------------------------------------
# Attach Activities to Sessions
# -------------------------------------------------------

def attach_activities_to_sessions(
    sessions,
    activities
):

    for session in sessions:

        session["Activities"] = []

        session_user = (
            session.get("FirefighterUser") or ""
        ).strip().upper()

        session_connector = (
            session.get("Connector") or ""
        ).strip().upper()

        login = (
            session.get("LoginTime") or ""
        ).strip()

        logout = (
            session.get("LogoutTime") or ""
        ).strip()

        # -----------------------------------------
        # Validate session timestamps
        # -----------------------------------------

        try:
            login_dt = datetime.strptime(
                login,
                "%Y%m%d%H%M%S"
            )

            logout_dt = datetime.strptime(
                logout,
                "%Y%m%d%H%M%S"
            )

        except Exception:
            print(
                f"Unable to parse session time for "
                f"{session_user}"
            )
            continue

        # -----------------------------------------
        # Match activities
        # -----------------------------------------

        for activity in activities:

            activity_user = (
                activity.get("FFUser") or ""
            ).strip().upper()

            activity_connector = (
                activity.get("Connector") or ""
            ).strip().upper()

            # User must match
            if activity_user != session_user:
                continue

            # Connector must match
            if activity_connector != session_connector:
                continue

            exec_date = (
                activity.get("ExecDate") or ""
            ).strip()

            # -----------------------------------------
            # Parse activity execution time
            # -----------------------------------------

            try:
                exec_dt = datetime.strptime(
                    exec_date,
                    "%Y%m%d%H%M%S"
                )

            except Exception:
                print(
                    f"Unable to parse activity time: "
                    f"{exec_date}"
                )
                continue

            # -----------------------------------------
            # Activity must occur inside FF session
            # -----------------------------------------

            if login_dt <= exec_dt <= logout_dt:

                session["Activities"].append({
                    "Action": (
                        activity.get("Action") or ""
                    ).strip(),

                    "Program": (
                        activity.get("Program") or ""
                    ).strip(),

                    "ExecDate": exec_date,

                    "Connector":
                        activity.get("Connector"),

                    "FFUser":
                        activity.get("FFUser")
                })

    return sessions


# -------------------------------------------------------
# Analyze Firefighter Data
# -------------------------------------------------------

def _get_session_ids(sessions):

    session_ids = [
        str(session.get("SessionId") or "").strip()
        for session in sessions
    ]

    missing_count = sum(
        1 for session_id in session_ids
        if not session_id
    )

    duplicate_ids = sorted({
        session_id
        for session_id in session_ids
        if session_id
        and session_ids.count(session_id) > 1
    })

    if missing_count or duplicate_ids:
        details = []

        if missing_count:
            details.append(
                f"{missing_count} session(s) have no Session ID"
            )

        if duplicate_ids:
            details.append(
                "duplicate Session ID(s): "
                + ", ".join(duplicate_ids)
            )

        raise ValueError(
            "Firefighter review cannot be completed because "
            + "; ".join(details)
            + "."
        )

    return session_ids


def _reviewed_session_id_matches(review_text):

    return list(re.finditer(
        r"(?im)^\s*-\s*(?:\*\*)?Session ID(?:\*\*)?"
        r"\s*:\s*(?:\*\*)?([^\s*]+)",
        review_text or ""
    ))


def _format_authoritative_activities(session):

    activities = session.get("Activities", [])

    if not activities:
        return "**No recorded activities.**"

    formatted_activities = []

    for activity in activities:
        formatted_activities.append(
            "- **Transaction Code**: "
            f"{str(activity.get('Action') or '').strip()}\n"
            "- **Program**: "
            f"{str(activity.get('Program') or '').strip()}\n"
            "- **Execution Time**: "
            f"{str(activity.get('ExecDate') or '').strip()}"
        )

    return "\n\n".join(formatted_activities)


def _render_authoritative_activities(
    review_text,
    sessions
):

    matches = _reviewed_session_id_matches(
        review_text
    )
    expected_ids = _get_session_ids(sessions)
    reviewed_ids = [
        match.group(1).strip()
        for match in matches
    ]

    if reviewed_ids != expected_ids:
        return review_text

    output_parts = []
    cursor = 0

    for index, match in enumerate(matches):
        segment_end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(review_text)
        )
        output_parts.append(
            review_text[cursor:match.end()]
        )

        session_review = review_text[
            match.end():segment_end
        ]
        authoritative_section = (
            "### 📝 Activities\n\n"
            + _format_authoritative_activities(
                sessions[index]
            )
            + "\n\n"
        )
        activities_pattern = re.compile(
            r"(?is)###\s*(?:📝\s*)?Activities\b"
            r".*?"
            r"(?=###\s*(?:🔍\s*)?Analysis\b)"
        )

        if activities_pattern.search(session_review):
            session_review = activities_pattern.sub(
                authoritative_section,
                session_review,
                count=1
            )
        else:
            analysis_match = re.search(
                r"(?is)###\s*(?:🔍\s*)?Analysis\b",
                session_review
            )

            if analysis_match:
                analysis_start = analysis_match.start()
                session_review = (
                    session_review[:analysis_start]
                    + authoritative_section
                    + session_review[analysis_start:]
                )

        output_parts.append(session_review)
        cursor = segment_end

    output_parts.append(review_text[cursor:])

    return "".join(output_parts)


def _validate_completed_review(
    review_text,
    sessions,
    finish_reason=None
):

    expected_ids = _get_session_ids(sessions)

    matches = _reviewed_session_id_matches(
        review_text
    )
    reviewed_ids = [
        match.group(1).strip()
        for match in matches
    ]

    if finish_reason and finish_reason != "stop":
        raise RuntimeError(
            "Firefighter review could not be completed for all "
            f"sessions: EXPECTED_COUNT={len(expected_ids)}, "
            f"REVIEWED_COUNT={len(set(reviewed_ids))}. Model "
            f"generation ended with finish reason "
            f"'{finish_reason}'."
        )

    if reviewed_ids != expected_ids:
        missing_ids = [
            session_id
            for session_id in expected_ids
            if session_id not in reviewed_ids
        ]
        unexpected_ids = [
            session_id
            for session_id in reviewed_ids
            if session_id not in expected_ids
        ]
        duplicate_ids = sorted({
            session_id
            for session_id in reviewed_ids
            if reviewed_ids.count(session_id) > 1
        })

        raise RuntimeError(
            "Firefighter review completeness validation failed: "
            f"EXPECTED_COUNT={len(expected_ids)}, "
            f"REVIEWED_COUNT={len(set(reviewed_ids))}, "
            f"missing={missing_ids}, "
            f"unexpected={unexpected_ids}, "
            f"duplicates={duplicate_ids}."
        )

    for index, session in enumerate(sessions):
        segment_start = matches[index].end()
        segment_end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(review_text)
        )
        session_review = review_text[
            segment_start:segment_end
        ]
        activities_match = re.search(
            r"(?is)###\s*(?:📝\s*)?Activities\b"
            r"(.*?)"
            r"(?=###\s*(?:🔍\s*)?Analysis\b)",
            session_review
        )

        if not activities_match:
            raise RuntimeError(
                "Firefighter review activity validation failed "
                f"for Session ID {expected_ids[index]}: "
                "Activities section is missing."
            )

        activities_review = activities_match.group(1)
        session_activities = session.get(
            "Activities",
            []
        )

        if not session_activities:
            if activities_review.count(
                "No recorded activities."
            ) != 1:
                raise RuntimeError(
                    "Firefighter review completeness validation "
                    f"failed for Session ID "
                    f"{expected_ids[index]}: the required "
                    "'No recorded activities.' statement is "
                    "missing or duplicated."
                )
            continue

        if "No recorded activities." in activities_review:
            raise RuntimeError(
                "Firefighter review activity validation failed "
                f"for Session ID {expected_ids[index]}."
            )

        for activity in session_activities:
            for field in (
                "Action",
                "Program",
                "ExecDate"
            ):
                value = str(
                    activity.get(field) or ""
                ).strip()

                if value and value not in activities_review:
                    raise RuntimeError(
                        "Firefighter review activity validation "
                        f"failed for Session ID "
                        f"{expected_ids[index]}: missing "
                        f"{field} value '{value}'."
                    )


def _format_review_summary(sessions):

    sessions_with_activities = sum(
        1 for session in sessions
        if session.get("Activities")
    )
    sessions_without_activities = (
        len(sessions) - sessions_with_activities
    )

    return (
        "### 📊 Executive Summary\n\n"
        f"- Sessions Reviewed: {len(sessions)}\n"
        "- Sessions with Activities: "
        f"{sessions_with_activities}\n"
        "- Sessions without Activities: "
        f"{sessions_without_activities}\n"
        "- Coverage: Complete - every authorized SAP "
        "session is included exactly once.\n"
    )


def _format_review_for_chat(review_text):

    formatted_lines = []
    previous_blank = False
    heading_replacements = {
        "📊 Executive Summary": (
            "🔥 FIREFIGHTER REVIEW\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "📊 OVERVIEW"
        ),
        "📝 Activities": "🧾 ACTIVITIES",
        "🔍 Analysis": "🔍 ASSESSMENT",
        "1. Business Reason Validation": "🧭 Business reason",
        "2. Transaction Validation": "🔎 Activity assessment",
        "3. Special Rules": "📌 Special rules",
        "4. Conclusion": "📝 Conclusion",
        "💡 Recommendation": "💡 RECOMMENDATION",
        "Recommendation": "💡 RECOMMENDATION",
        "🛡️ Decision": "🛡️ DECISION",
        "Decision": "🛡️ DECISION",
        "Analysis": "🔍 ASSESSMENT",
        "Activities": "🧾 ACTIVITIES"
    }
    activity_label_replacements = {
        "- Transaction Code:": "🔷 T-Code:",
        "- Program:": "🟣 Program:",
        "- Execution Time:": "🕒 Executed:"
    }
    decision_replacements = {
        "APPROVE": "🟢 APPROVE",
        "REQUEST JUSTIFICATION": "🟠 REQUEST JUSTIFICATION",
        "ESCALATE": "🔴 ESCALATE"
    }

    for line in (review_text or "").splitlines():
        stripped_line = line.strip()

        if stripped_line == "---":
            line = ""
        else:
            line = re.sub(
                r"^\s*#{1,6}\s*",
                "",
                line
            )
            line = line.replace("**", "")
            stripped_line = line.strip()

            if (
                stripped_line.startswith("🔹 Session ")
                or stripped_line.startswith("Session ")
            ):
                session_label = stripped_line.replace(
                    "🔹 ",
                    "",
                    1
                ).upper()
                line = (
                    "━━━━━━━━━━━━━━━━━━\n"
                    f"🔹 {session_label}"
                )
            elif stripped_line in heading_replacements:
                line = heading_replacements[stripped_line]
            elif stripped_line in decision_replacements:
                line = decision_replacements[stripped_line]
            else:
                for source_label, display_label in (
                    activity_label_replacements.items()
                ):
                    if stripped_line.startswith(source_label):
                        value = stripped_line[
                            len(source_label):
                        ].strip()
                        line = f"{display_label} {value}"
                        break

        is_blank = not line.strip()

        if is_blank and previous_blank:
            continue

        formatted_lines.append(line.rstrip())
        previous_blank = is_blank

    return "\n".join(formatted_lines).strip()


def analyze_firefighter_data(
    sessions,
    activities,
    mode="review_all",
    filter_value="",
    _review_index_offset=None
):

    sessions = attach_activities_to_sessions(
        sessions,
        activities
    )

    _get_session_ids(sessions)

    if _review_index_offset is None:
        review_parts = []

        for batch_start in range(
            0,
            len(sessions),
            FIREFIGHTER_REVIEW_BATCH_SIZE
        ):
            batch = sessions[
                batch_start:
                batch_start + FIREFIGHTER_REVIEW_BATCH_SIZE
            ]
            review_parts.append(
                analyze_firefighter_data(
                    batch,
                    activities,
                    mode,
                    filter_value,
                    _review_index_offset=batch_start
                )
            )

        completed_review = (
            _format_review_summary(sessions)
            + "\n---\n\n"
            + "\n\n---\n\n".join(review_parts)
        )

        _validate_completed_review(
            completed_review,
            sessions
        )

        return _format_review_for_chat(
            completed_review
        )

    BASE_DIR = os.path.dirname(
        os.path.abspath(__file__)
    )

    knowledge_file = os.path.join(
        BASE_DIR,
        "knowledge_base",
        "firefighter_roles.md"
    )

    with open(
        knowledge_file,
        "r",
        encoding="utf-8"
    ) as f:
        firefighter_knowledge_base = f.read()

    prompt = f"""
You are an SAP GRC Firefighter Review Expert.

Review EVERY Firefighter Session individually using ONLY:

1. Firefighter Session details.
2. Activities attached to that specific session by Python.
3. Firefighter Knowledge Base.

The Firefighter Knowledge Base is the source of truth for:
- Firefighter role purpose
- Expected transactions
- Restricted activities
- Special Rules
- Automatic/background processing rules

======================================================
STRICT DATA ACCURACY RULES
======================================================

Never fabricate or assume:

- Firefighter User
- Firefighter ID
- Session ID
- Business Reason
- Owner
- Controller
- Connector
- Login Time
- Logout Time
- Transaction Code
- Program
- Execution Time
- Activities
- Recommendations
- Decisions

Base every conclusion ONLY on:

- Supplied session data
- Activities attached to that session
- Firefighter Knowledge Base

The Authenticated Controller is the controller identity
provided by the authorization layer.

Do NOT use the SAP session Controller field to determine
whether the session is authorized.

Authorization has already been enforced by Python before
the data reaches the AI.

Never infer authorization from the SAP session Controller
field.

The Python activity-matching result is authoritative.

If a session's Activities list contains activities,
you MUST display those activities.

If the Activities list is empty, write exactly:

No recorded activities.

Do NOT use activities from another session.

Do NOT move activities from one session to another.

Do NOT invent activities based on the Firefighter role.

Do NOT infer a transaction that is not present in the
attached Activities list.

Do NOT invent a Program when the Program is missing.

======================================================
AUTOMATIC BACKGROUND PROCESSING
======================================================

Do not automatically treat background/system processing
as a manual security violation.

Apply automatic processing rules ONLY when the supplied
session context, activity data, and Knowledge Base support
the conclusion.

1. FF_FIAP / Concur IDoc Processing

If FB01 is recorded during Concur-related IDoc processing
under FF_FIAP, do not automatically classify FB01 as a
manual financial posting.

The system may automatically trigger FB01 as part of
standard IDoc invoice posting.

Treat it as automatic background processing only when the
available context supports this.

2. O2C Web Order IDoc Processing

If VA01 is recorded during Web Order IDoc processing under
the appropriate O2C/Web Firefighter ID, do not automatically
classify VA01 as an unauthorized manual sales-order creation.

VA01 may be automatically triggered by Web Order IDoc
processing.

Treat it as automatic background processing only when the
available context supports this.

Never claim an activity was automatic solely because the
transaction appears in these rules.

======================================================
OUTPUT FORMAT
======================================================

Do NOT output an Executive Summary. Python generates the
authoritative summary after every batch has been validated.

======================================================

### 🔹 Session {_review_index_offset + 1}

- **Firefighter User**:
- **Firefighter ID**:
- **Session ID**:
- **Business Reason**:
- **Owner**:
- **Controller**:
- **Connector**:
- **Login Time**:
- **Logout Time**:

### 📝 Activities

Display ONLY activities actually attached to this session.

For every recorded activity display ONLY:

- **Transaction Code**:
- **Program**:
- **Execution Time**:

Do NOT display:
- Connector
- FFUser
- Raw JSON
- OData metadata

If no activities are attached to the session, write exactly:

**No recorded activities.**

======================================================

### 🔍 Analysis

For EVERY session provide ONLY these four points.

#### 1. Business Reason Validation

Explain whether the Business Reason matches the purpose
of the Firefighter ID according to the Firefighter Knowledge Base.

Do not invent a role purpose if the Knowledge Base does not
provide sufficient information.

Use no more than two concise sentences.

#### 2. Transaction Validation

For EVERY activity actually recorded for this session:

- State the exact Transaction Code.
- State the exact Program.
- Determine whether the transaction is:
  - Expected
  - Unexpected
  - Automatic Background Processing
  - High Risk

Explain WHY based ONLY on the Firefighter Knowledge Base
and supplied session/activity context.

Keep each activity assessment to one concise sentence.
When the same transaction occurs more than once, assess it
once and state the number of occurrences.

Do not introduce transactions that are not present.

Do not list expected transactions that were NOT executed
as if they were executed.

If an activity is identified as automatic background
processing, clearly explain why.

If no activities are recorded, write exactly:

**No activities were recorded for validation.**

#### 3. Special Rules

Apply ALL Special Rules relevant to this specific
Firefighter ID and its recorded activities.

Do not list unrelated Special Rules.

If no applicable Special Rules exist, write:

**No applicable special rules identified.**

Do not add an explanation when no special rule applies.

#### 4. Conclusion

State whether the session aligns with:

- Firefighter role
- Business reason
- Recorded activities
- Applicable Special Rules

Base the conclusion only on available evidence.

Use one concise sentence.

======================================================

### 🛡️ Decision

For EACH session provide exactly ONE decision:

**APPROVE**

**REQUEST JUSTIFICATION**

**ESCALATE**

Do NOT provide one global decision for all sessions.

Do NOT create a separate Recommendation section.

Do not automatically approve a session merely because there
are no activities.

Do not automatically escalate a session merely because a
transaction is sensitive.

Base the decision on the available evidence.

======================================================
IMPORTANT OUTPUT RULES
======================================================

1. Review EVERY session individually.

2. Do NOT create a "Remaining Sessions" section.

3. Do NOT create a "Final Recommendation" section.

4. Do NOT create a "Masked Activity Sample" section.

5. Do NOT output raw JSON.

6. Do NOT reproduce the complete OData payload.

7. Do NOT invent activities.

8. Do NOT omit activities that exist in the session's
   Activities list.

9. Keep Transaction Code, Program, and Execution Time
   exactly as supplied.

10. Keep the analysis concise and suitable for an
    SAP GRC audit/review process. Avoid repeating session
    facts in the assessment.

11. This batch contains {len(sessions)} sessions. Output
    exactly {len(sessions)} detailed session reviews, in
    the supplied order, starting with review number
    {_review_index_offset + 1}.

12. Include every supplied Session ID exactly once in its
    "- **Session ID**:" field.

======================================================

🔥 FIREFIGHTER SESSIONS
======================================================

{json.dumps(sessions, indent=2)}

======================================================

📚 FIREFIGHTER KNOWLEDGE BASE
======================================================

{firefighter_knowledge_base}

======================================================

Request Type:
{mode}

Filter:
{filter_value}

======================================================
END OF INPUT
======================================================
"""

    response = azure_client.chat.completions.create(
        model=AZURE_OPENAI_DEPLOYMENT,
        messages=[
            {
                "role": "system",
                "content":
                    "You are an SAP GRC Security Expert."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0,
        max_tokens=4000
    )

    choice = response.choices[0]
    review_text = choice.message.content or ""

    review_text = _render_authoritative_activities(
        review_text,
        sessions
    )

    _validate_completed_review(
        review_text,
        sessions,
        getattr(choice, "finish_reason", None)
    )

    return review_text


# -------------------------------------------------------
# Pending Review Summary
# -------------------------------------------------------

def format_pending_reviews(sessions):

    if not sessions:
        return (
            "========================================\n"
            "        FIREFIGHTER REVIEW AGENT\n"
            "========================================\n\n"
            "No pending Firefighter reviews found.\n"
        )

    output = """
========================================
        PENDING FIREFIGHTER REVIEWS
========================================

"""

    for index, session in enumerate(
        sessions,
        start=1
    ):

        output += (
            f"{index}. Firefighter User : "
            f"{session.get('FirefighterUser', '-')}\n"

            f"   Firefighter ID   : "
            f"{session.get('FirefighterId', '-')}\n"

            f"   Session ID       : "
            f"{session.get('SessionId', '-')}\n"

            f"   Owner            : "
            f"{session.get('Owner', '-')}\n"

            f"   Controller       : "
            f"{session.get('Controller', '-') or 'Not Assigned'}\n"

            f"   Reason           : "
            f"{session.get('Reason', '-')}\n"

            f"   Connector        : "
            f"{session.get('Connector', '-')}\n"

            f"   Login Time       : "
            f"{session.get('LoginTime', '-')}\n"

            f"   Logout Time      : "
            f"{session.get('LogoutTime', '-')}\n\n"
        )

    output += (
        "----------------------------------------\n"
        f"Total Pending Reviews : {len(sessions)}\n"
        "========================================\n"
    )

    return output


# -------------------------------------------------------
# Run Agent
# -------------------------------------------------------

def run_agent(question, authenticated_identity=None):

    route = ai_router(question)

    try:

        # ---------------------------------------------
        # Controller comes ONLY from the authenticated
        # Microsoft Entra identity.
        # ---------------------------------------------

        controller = resolve_sap_controller(
            authenticated_identity
        )
        firefighter_identity = dict(authenticated_identity or {})
        firefighter_identity["sap_controller"] = controller

        controller = get_authenticated_controller(
            firefighter_identity
        )
        authenticated_email = str(
            firefighter_identity.get(
                "preferred_username"
            )
            or ""
        ).strip().lower()

    except Exception as identity_error:

        return (
            "========================================\n"
            "        AUTHORIZATION CHECK FAILED\n"
            "========================================\n\n"
            f"{str(identity_error)}\n\n"
            "No SAP data was changed or displayed."
        )

    print("\n===== Router Output =====")
    print(route)
    print("=========================\n")

    print(
        "Authenticated SAP Controller:",
        controller
    )

    action = route.get("action")

    try:

        # -----------------------------
        # Review All Sessions
        # -----------------------------
        if action == "review_all":

            print(
                "\n===== FIREFIGHTER "
                "AUTHORIZATION CHECK ====="
            )

            print(
                "Authenticated SAP Controller:",
                controller
            )

            sessions, activities, scope = (
                get_authorized_controller_data(
                    controller,
                    authenticated_email
                )
            )

            print("\nAuthorized Firefighter Scope:")

            for item in scope:
                print(
                    f"FF ID: {item['FirefighterId']} | "
                    f"Connector: {item['Connector']}"
                )

            print(
                "\nAuthorized Sessions:",
                len(sessions)
            )

            print(
                "Authorized Activities:",
                len(activities)
            )

            print("\nAuthorized Session Details:")

            for session in sessions:
                print(
                    f"FF ID: "
                    f"{session.get('FirefighterId')} | "
                    f"FF User: "
                    f"{session.get('FirefighterUser')} | "
                    f"Session: "
                    f"{session.get('SessionId')} | "
                    f"Connector: "
                    f"{session.get('Connector')} | "
                    f"Authenticated Controller: "
                    f"{session.get('AuthenticatedController')}"
                )

            print(
                "\n==========================================\n"
            )

            return analyze_firefighter_data(
                sessions,
                activities,
                "review_all",
                controller
            )

        # -----------------------------
        # Review Specific User
        # -----------------------------
        elif action == "review_user":

            user = (
                route.get("user", "")
                .upper()
                .strip()
            )

            if not user:
                return "Firefighter user is missing."

            authorized_sessions, authorized_activities, scope = (
                get_authorized_controller_data(
                    controller,
                    authenticated_email
                )
            )

            # Only keep sessions for the requested user
            sessions = [
                session
                for session in authorized_sessions
                if (
                    session.get("FirefighterUser") or ""
                ).strip().upper() == user
            ]

            activities = (
                filter_activities_by_authorized_sessions(
                    authorized_activities,
                    sessions
                )
            )

            if not sessions:
                return (
                    f"Access denied or no authorized "
                    f"Firefighter sessions found "
                    f"for user {user}."
                )

            return analyze_firefighter_data(
                sessions,
                activities,
                "review_user",
                user
            )

        # -----------------------------
        # Pending Reviews
        # -----------------------------
        elif action == "pending_reviews":

            sessions, activities, scope = (
                get_authorized_controller_data(
                    controller,
                    authenticated_email
                )
            )

            return format_pending_reviews(sessions)

        # -----------------------------
        # Transaction Review
        # -----------------------------
        elif action == "review_transaction":

            transaction = (
                route.get("transaction", "")
                .upper()
                .strip()
            )

            if not transaction:
                return "Transaction code is missing."

            authorized_sessions, authorized_activities, scope = (
                get_authorized_controller_data(
                    controller,
                    authenticated_email
                )
            )

            transaction_activities = [
                activity
                for activity in authorized_activities
                if (
                    activity.get("Action") or ""
                ).strip().upper() == transaction
            ]

            if not transaction_activities:
                return (
                    "========================================\n"
                    "        FIREFIGHTER REVIEW AGENT\n"
                    "========================================\n\n"
                    f"No authorized Firefighter activities "
                    f"found for transaction {transaction}.\n"
                )

            return analyze_firefighter_data(
                authorized_sessions,
                transaction_activities,
                "review_transaction",
                transaction
            )

        # -----------------------------
        # Connector Review
        # -----------------------------
        elif action == "review_connector":

            connector = (
                route.get("connector", "")
                .upper()
                .strip()
            )

            if not connector:
                return "Connector is missing."

            authorized_sessions, authorized_activities, scope = (
                get_authorized_controller_data(
                    controller,
                    authenticated_email
                )
            )

            sessions = [
                session
                for session in authorized_sessions
                if (
                    session.get("Connector") or ""
                ).strip().upper() == connector
            ]

            activities = (
                filter_activities_by_authorized_sessions(
                    authorized_activities,
                    sessions
                )
            )

            if not sessions:
                return (
                    f"Access denied or no authorized "
                    f"Firefighter data found "
                    f"for connector {connector}."
                )

            return analyze_firefighter_data(
                sessions,
                activities,
                "review_connector",
                connector
            )

        # -----------------------------
        # Summarize
        # -----------------------------
        elif action == "summarize":

            sessions, activities, scope = (
                get_authorized_controller_data(
                    controller,
                    authenticated_email
                )
            )

            return analyze_firefighter_data(
                sessions,
                activities,
                "summarize",
                controller
            )

        # -----------------------------
        # Risk Analysis
        # -----------------------------
        elif action == "risk_analysis":

            sessions, activities, scope = (
                get_authorized_controller_data(
                    controller,
                    authenticated_email
                )
            )

            return analyze_firefighter_data(
                sessions,
                activities,
                "risk_analysis",
                controller
            )

        # -----------------------------
        # Approval
        # -----------------------------
        elif action == "approval":

            sessions, activities, scope = (
                get_authorized_controller_data(
                    controller,
                    authenticated_email
                )
            )

            return analyze_firefighter_data(
                sessions,
                activities,
                "approval",
                controller
            )

        else:

            return (
                "========================================\n"
                "        FIREFIGHTER REVIEW AGENT\n"
                "========================================\n\n"
                "Unknown request.\n\n"
                "Try asking:\n"
                "- Analyze all firefighter sessions\n"
                "- Review firefighter user GUPTARO\n"
                "- Show pending firefighter reviews\n"
                "- Show FB01 activities\n"
                "- Show connector T4PCLNT100\n"
                "- Can I approve this session?\n"
            )

    except Exception as ex:

        return (
            "========================================\n"
            "        FIREFIGHTER REVIEW AGENT\n"
            "========================================\n\n"
            "Unable to process Firefighter review.\n\n"
            f"Error: {str(ex)}"
        )


# -------------------------------------------------------
# Main
# -------------------------------------------------------

if __name__ == "__main__":

    print("\n======================================")
    print(" Firefighter Review Agent ")
    print("======================================\n")

    print(
        "This agent requires an authenticated "
        "Microsoft Entra identity."
    )

    print(
        "Local console mode uses a locally supplied "
        "identity for development only."
    )

    local_controller = os.getenv(
        "LOCAL_DEV_CONTROLLER",
        ""
    ).strip().upper()

    local_identity = None

    if local_controller:

        local_identity = {
            "authenticated": True,
            "sap_controller": local_controller,
            "preferred_username": os.getenv(
                "LOCAL_DEV_USER",
                ""
            ).strip()
        }

        print(
            "Local development controller:",
            local_controller
        )

    else:

        print(
            "LOCAL_DEV_CONTROLLER is not set. "
            "Requests will be rejected."
        )

    print("\n===== Controller Assignments =====")

    try:

        assignments = get_controller_assignments()

        for assignment in assignments:
            print(assignment)

    except Exception as ex:

        print(
            "Unable to retrieve Controller assignments:"
        )
        print(ex)

    print("==================================\n")

    while True:

        question = input("You : ").strip()

        if question.lower() in [
            "exit",
            "quit",
            "bye"
        ]:
            print("Assistant: Bye")
            break

        print()

        print(
            run_agent(
                question,
                local_identity
            )
        )

        print()
