import os
import time
import requests
import urllib3

from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth
from requests.exceptions import RequestException

urllib3.disable_warnings(
    urllib3.exceptions.InsecureRequestWarning
)

# -------------------------------------------------------
# Load Environment
# -------------------------------------------------------

load_dotenv()

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
    (
        f"{SAP_HOST}/sap/bc/sec/oauth2/token"
        f"?sap-client={SAP_CLIENT}"
    )
).strip()

SAP_OAUTH_SCOPE = os.getenv(
    "SAP_OAUTH_SCOPE",
    ""
).strip()

# Keep false temporarily only if SAP DEV uses an
# internally signed or self-signed certificate.
SAP_VERIFY_SSL = os.getenv(
    "SAP_VERIFY_SSL",
    "false"
).strip().lower() in ("true", "1", "yes")


# -------------------------------------------------------
# Validate Environment
# -------------------------------------------------------

def validate_environment():

    required_variables = {
        "SAP_HOST": SAP_HOST,
        "SAP_CLIENT": SAP_CLIENT,
        "SAP_OAUTH_CLIENT_ID": SAP_OAUTH_CLIENT_ID,
        "SAP_OAUTH_CLIENT_SECRET": SAP_OAUTH_CLIENT_SECRET,
        "SAP_OAUTH_TOKEN_URL": SAP_OAUTH_TOKEN_URL
    }

    missing_variables = [
        name
        for name, value in required_variables.items()
        if not value
    ]

    if missing_variables:
        raise RuntimeError(
            "Missing required environment variables: "
            + ", ".join(missing_variables)
        )


validate_environment()


# -------------------------------------------------------
# OAuth Token Cache
# -------------------------------------------------------

SAP_ACCESS_TOKEN = None
SAP_TOKEN_EXPIRES_AT = 0


def clear_sap_token_cache():

    global SAP_ACCESS_TOKEN
    global SAP_TOKEN_EXPIRES_AT

    SAP_ACCESS_TOKEN = None
    SAP_TOKEN_EXPIRES_AT = 0


def get_sap_access_token(force_refresh=False):

    global SAP_ACCESS_TOKEN
    global SAP_TOKEN_EXPIRES_AT

    current_time = time.time()

    if force_refresh:
        clear_sap_token_cache()

    # Reuse the token when it is still valid.
    if (
        SAP_ACCESS_TOKEN
        and current_time < SAP_TOKEN_EXPIRES_AT - 60
    ):
        return SAP_ACCESS_TOKEN

    response = None

    try:

        token_request_data = {
            "grant_type": "client_credentials"
        }

        # Do not send a blank OAuth scope.
        if SAP_OAUTH_SCOPE:
            token_request_data["scope"] = SAP_OAUTH_SCOPE

        response = requests.post(
            SAP_OAUTH_TOKEN_URL,
            auth=HTTPBasicAuth(
                SAP_OAUTH_CLIENT_ID,
                SAP_OAUTH_CLIENT_SECRET
            ),
            data=token_request_data,
            headers={
                "Accept": "application/json",
                "Content-Type":
                    "application/x-www-form-urlencoded"
            },
            verify=SAP_VERIFY_SSL,
            timeout=60
        )

        response.raise_for_status()

        token_data = response.json()

        access_token = token_data.get("access_token")

        if not access_token:
            raise RuntimeError(
                "OAuth response does not contain access_token."
            )

        expires_in = int(
            token_data.get("expires_in", 3600)
        )

        SAP_ACCESS_TOKEN = access_token
        SAP_TOKEN_EXPIRES_AT = (
            current_time + expires_in
        )

        print(
            "SAP OAuth token obtained successfully."
        )

        return SAP_ACCESS_TOKEN

    except Exception as ex:

        error_response = ""

        if response is not None:
            error_response = response.text[:1000]

        raise RuntimeError(
            "SAP OAuth token request failed: "
            f"{str(ex)} | Response: {error_response}"
        ) from ex


# -------------------------------------------------------
# Authorization API URLs
# -------------------------------------------------------

AUTHORIZATION_SERVICE_ROOT = (
    f"{SAP_HOST}"
    "/sap/opu/odata/sap/"
    "ZAI_AUTHORIZATION_SRV/"
)

AUTHORIZATION_URL = (
    f"{SAP_HOST}"
    "/sap/opu/odata/sap/"
    "ZAI_AUTHORIZATION_SRV/"
    "AuthorizationCheckSet"
)


# -------------------------------------------------------
# Utility Methods
# -------------------------------------------------------

def is_success_status(status_code):

    # Handles all successful HTTP responses:
    # 200 OK, 201 Created, 204 No Content, etc.
    return 200 <= status_code < 300


def get_safe_response_body(response, limit=1000):

    if response is None:
        return ""

    try:
        return response.text[:limit]
    except Exception:
        return ""


def build_http_debug(response):

    if response is None:
        return {}

    return {
        "status_code": response.status_code,
        "url": response.url,
        "content_type": response.headers.get(
            "Content-Type"
        ),
        "body": get_safe_response_body(response)
    }


def normalize_sap_authorized_value(value):

    if value is True:
        return True

    if value is False or value is None:
        return False

    normalized_value = str(value).strip().lower()

    return normalized_value in {
        "x",
        "true",
        "1",
        "yes",
        "y"
    }


# -------------------------------------------------------
# CSRF Token Fetch
# -------------------------------------------------------

def get_csrf_token(session=None):

    active_session = session or requests.Session()
    active_session.verify = SAP_VERIFY_SSL

    try:

        access_token = get_sap_access_token()

        response = active_session.get(
            AUTHORIZATION_SERVICE_ROOT,
            params={
                "sap-client": SAP_CLIENT,
                "saml2": "disabled"
            },
            headers={
                "Authorization":
                    f"Bearer {access_token}",
                "x-csrf-token": "Fetch",
                "Accept": "application/json"
            },
            timeout=30
        )

        token = response.headers.get(
            "x-csrf-token"
        )

        csrf_debug = {
            "status_code": response.status_code,
            "url": response.url,
            "content_type": response.headers.get(
                "Content-Type"
            ),
            "token_present": bool(token),
            "cookies": list(
                active_session.cookies.keys()
            ),
            "body": get_safe_response_body(response)
        }

        if not is_success_status(response.status_code):
            return None, csrf_debug

        if not token:
            return None, csrf_debug

        return token, csrf_debug

    except RequestException as ex:

        return None, {
            "error": str(ex)
        }


# -------------------------------------------------------
# Authorization Check
# -------------------------------------------------------

def check_authorization(
    email,
    business_object,
    action
):

    email = str(email or "").strip().lower()
    business_object = str(
        business_object or ""
    ).strip().upper()
    action = str(action or "").strip().upper()

    if not email:
        return {
            "authorized": False,
            "message": "Email is required."
        }

    if not business_object:
        return {
            "authorized": False,
            "message": "Business object is required."
        }

    if not action:
        return {
            "authorized": False,
            "message": "Action is required."
        }

    session = requests.Session()
    session.verify = SAP_VERIFY_SSL

    try:
        access_token = get_sap_access_token()
    except Exception as ex:
        return {
            "authorized": False,
            "message": "Unable to obtain SAP OAuth token.",
            "error": str(ex)
        }

    common_headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }

    # ===================================================
    # 1. Fetch CSRF Token
    # ===================================================

    try:

        csrf_response = session.get(
            AUTHORIZATION_SERVICE_ROOT,
            params={
                "sap-client": SAP_CLIENT,
                "saml2": "disabled"
            },
            headers={
                **common_headers,
                "x-csrf-token": "Fetch"
            },
            timeout=30
        )

    except RequestException as ex:

        return {
            "authorized": False,
            "message": "Unable to fetch CSRF token.",
            "error": str(ex)
        }

    csrf_token = csrf_response.headers.get(
        "x-csrf-token"
    )

    if (
        not is_success_status(csrf_response.status_code)
        or not csrf_token
    ):

        return {
            "authorized": False,
            "message": "Unable to fetch CSRF token.",
            "csrf_error": {
                "status_code":
                    csrf_response.status_code,
                "url":
                    csrf_response.url,
                "content_type":
                    csrf_response.headers.get(
                        "Content-Type"
                    ),
                "token_present":
                    bool(csrf_token),
                "cookies":
                    list(session.cookies.keys()),
                "body":
                    get_safe_response_body(
                        csrf_response
                    )
            }
        }

    # ===================================================
    # CSRF Debug
    # ===================================================

    print("\n===== CSRF DEBUG =====")
    print(
        "CSRF Token Present:",
        bool(csrf_token)
    )
    print(
        "Session Cookies:",
        list(session.cookies.keys())
    )

    # Never print the complete CSRF token.
    if csrf_token:
        print(
            "CSRF Token:",
            csrf_token[:10] + "...[MASKED]"
        )

    print("======================\n")

    # ===================================================
    # 2. Authorization POST Request
    # ===================================================

    payload = {
        "EMAIL": email,
        "BusinessObject": business_object,
        "Action": action
    }

    try:

        response = session.post(
            AUTHORIZATION_URL,
            params={
                "sap-client": SAP_CLIENT,
                "saml2": "disabled"
            },
            headers={
                **common_headers,
                "x-csrf-token": csrf_token,
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=60
        )

    except RequestException as ex:

        return {
            "authorized": False,
            "message": "Authorization request failed.",
            "error": str(ex)
        }

    # ===================================================
    # 3. Handle HTTP Response
    # ===================================================

    # Important fix:
    # SAP OData POST returns HTTP 201 Created.
    # Any 2xx code is an HTTP success.
    if not is_success_status(response.status_code):

        return {
            "authorized": False,
            "message": (
                "Authorization check API failed. "
                f"HTTP {response.status_code}"
            ),
            "csrf_debug": {
                "status_code":
                    csrf_response.status_code,
                "url":
                    csrf_response.url,
                "content_type":
                    csrf_response.headers.get(
                        "Content-Type"
                    ),
                "token_present":
                    bool(csrf_token),
                "cookies":
                    list(session.cookies.keys()),
                "body":
                    get_safe_response_body(
                        csrf_response
                    )
            },
            "auth_error": {
                "status_code":
                    response.status_code,
                "url":
                    response.url,
                "content_type":
                    response.headers.get(
                        "Content-Type"
                    ),
                "request_cookie_header_present":
                    bool(
                        response.request.headers.get(
                            "Cookie"
                        )
                    ),
                "body":
                    get_safe_response_body(response)
            }
        }

    # ===================================================
    # 4. Parse Successful SAP Response
    # ===================================================

    try:

        data = response.json()

    except ValueError as ex:

        return {
            "authorized": False,
            "message": (
                "Authorization service returned "
                "an invalid JSON response."
            ),
            "error": str(ex),
            "status_code": response.status_code,
            "body": get_safe_response_body(response)
        }

    # OData V2 normally wraps the entity under "d".
    entity = data.get("d", data)

    if not isinstance(entity, dict):

        return {
            "authorized": False,
            "message": (
                "Authorization service returned "
                "an unexpected response structure."
            ),
            "status_code": response.status_code,
            "body": get_safe_response_body(response)
        }

    authorized_value = entity.get("Authorized")

    authorized = normalize_sap_authorized_value(
        authorized_value
    )

    sap_message = entity.get(
        "Message",
        "Authorization check completed."
    )

    return {
        "authorized": authorized,
        "message": sap_message,
        "status_code": response.status_code,
        "raw": entity
    }


# -------------------------------------------------------
# Authorization Denied Formatter
# -------------------------------------------------------

def format_authorization_denied(auth_result):

    output = (
        "========================================\n"
        "        AUTHORIZATION CHECK FAILED\n"
        "========================================\n\n"
        "You are not authorized to perform "
        "this action.\n\n"
        f"Reason: {auth_result.get('message')}\n\n"
    )

    # Temporary debugging only.
    # Remove detailed API output before QA/PROD.

    if auth_result.get("csrf_error"):

        output += (
            "CSRF Debug Details\n"
            "----------------------------------------\n"
            f"{auth_result.get('csrf_error')}\n\n"
        )

    if auth_result.get("auth_error"):

        output += (
            "Authorization API Debug Details\n"
            "----------------------------------------\n"
            f"{auth_result.get('auth_error')}\n\n"
        )

    if auth_result.get("error"):

        output += (
            "Technical Error\n"
            "----------------------------------------\n"
            f"{auth_result.get('error')}\n\n"
        )

    output += (
        "No SAP data was changed or displayed."
    )

    return output


# -------------------------------------------------------
# Optional Test
# -------------------------------------------------------

if __name__ == "__main__":

    test_result = check_authorization(
        email="moses.chilakalapalli@tomtom.com",
        business_object="FIREFIGHTER",
        action="DISPLAY"
    )

    print("\n===== AUTHORIZATION RESULT =====")
    print(test_result)
    print("================================\n")

    if test_result.get("authorized"):
        print(
            "Authorization successful. "
            "The firefighter review can continue."
        )
    else:
        print(
            format_authorization_denied(
                test_result
            )
        )