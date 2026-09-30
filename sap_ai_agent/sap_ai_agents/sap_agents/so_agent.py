import os
import json
import re
import requests
import urllib3
import sys

from datetime import datetime, timezone
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

SO_URL = f"{SAP_HOST}/sap/opu/odata/sap/API_SALES_ORDER_SRV/A_SalesOrder"

pending_action = None


def has_pending_action():
    global pending_action
    return pending_action is not None


def clean_value(value):
    if value is None:
        return ""

    value = str(value).strip()
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"[^A-Za-z0-9._/-]", "", value)

    return value


def convert_to_sap_date(date_value):
    if not date_value:
        return ""

    date_value = str(date_value).strip()

    if date_value.startswith("/Date("):
        return date_value

    formats = [
        "%Y-%m-%d",
        "%d.%m.%Y",
        "%d/%m/%Y",
        "%d-%m-%Y"
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(date_value, fmt)
            dt = dt.replace(tzinfo=timezone.utc)
            milliseconds = int(dt.timestamp() * 1000)
            return f"/Date({milliseconds})/"
        except ValueError:
            continue

    return ""


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
                "response": response.text[:2000],
                "url": response.url
            }

        return response.json()

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


def get_sales_order(so_number):
    so_number = clean_value(so_number)

    if not so_number:
        return "Sales Order number is missing."

    # -------------------------------------------------------
    # Authorization Check - Sales Order Display
    # -------------------------------------------------------
    auth_result = check_authorization(
        SAP_USER,
        "SALES_ORDER",
        "DISPLAY"
    )

    if not auth_result.get("authorized"):
        return format_authorization_denied(auth_result)

    data = sap_get(
        SO_URL,
        {
            "$filter": f"SalesOrder eq '{so_number}'",
            "$expand": "to_Item"
        }
    )

    if data.get("status") == "error":
        return f"SAP Error: {data}"

    results = data.get("d", {}).get("results", [])

    if not results:
        return f"Sales Order {so_number} not found."

    so = results[0]
    items = so.get("to_Item", {}).get("results", [])

    item_text = ""

    for item in items:
        item_text += (
            f"\nItem: {item.get('SalesOrderItem')}"
            f"\nMaterial: {item.get('Material')}"
            f"\nQuantity: {item.get('RequestedQuantity')} {item.get('RequestedQuantityUnit')}"
            f"\nNet Amount: {item.get('NetAmount')}"
            f"\n"
        )

    return (
        f"Sales Order Found\n"
        f"Sales Order: {so.get('SalesOrder')}\n"
        f"Sales Order Type: {so.get('SalesOrderType')}\n"
        f"Sales Org: {so.get('SalesOrganization')}\n"
        f"Distribution Channel: {so.get('DistributionChannel')}\n"
        f"Division: {so.get('OrganizationDivision')}\n"
        f"Sold-To Party: {so.get('SoldToParty')}\n"
        f"Customer PO: {so.get('PurchaseOrderByCustomer')}\n"
        f"Requested Delivery Date: {so.get('RequestedDeliveryDate')}\n"
        f"Total Net Amount: {so.get('TotalNetAmount')} {so.get('TransactionCurrency')}\n"
        f"Created On: {so.get('CreationDate')}\n"
        f"\nItems:\n{item_text}"
    )


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
        return None, response.text[:1000]

    return token, None


def sap_post(url, payload):
    token, error = get_csrf_token(url)

    if not token:
        return {
            "status": "error",
            "message": "CSRF token not received",
            "response": error
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
            "message": "SAP request timed out after 120 seconds. Check SAP backend or see if Sales Order was created."
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


def ai_router(question):
    prompt = """
You are a secure SAP Sales Order assistant router.
Return ONLY valid JSON. No markdown. No explanation.

Actions:
- get_sales_order
- create_sales_order
- unknown

For GET sales order, return:
{
  "action": "get_sales_order",
  "sales_order": "",
  "data": {}
}

For CREATE sales order, return:
{
  "action": "create_sales_order",
  "sales_order": "",
  "data": {
    "sales_order_type": "",
    "sales_org": "",
    "distribution_channel": "",
    "division": "",
    "sold_to_party": "",
    "customer_po": "",
    "currency": "",
    "material": "",
    "quantity": "",
    "unit": "",
    "requested_delivery_date": ""
  }
}

Rules:
- If user asks to check, show, get, track, or display a sales order, use get_sales_order and extract the sales order number.
- If user asks to create sales order or SO, use create_sales_order.
- Extract only simple values.
- If sales order type is missing, use OR.
- If currency is missing, use EUR.
- If unit is missing, use PC.
- Extract requested delivery date if user provides it.
- Requested delivery date can be in formats like 2026-07-10, 10.07.2026, 10/07/2026, or 10-07-2026.
- If requested delivery date is missing, leave it blank.
- Do not build SAP payload.
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
        max_tokens=500
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
            "sales_order": "",
            "data": {}
        }


def build_so_payload(data):
    sales_order_type = clean_value(data.get("sales_order_type", "OR")).upper() or "OR"
    sales_org = clean_value(data.get("sales_org", "")).upper()
    distribution_channel = clean_value(data.get("distribution_channel", ""))
    division = clean_value(data.get("division", ""))
    sold_to_party = clean_value(data.get("sold_to_party", ""))
    customer_po = str(data.get("customer_po", "")).strip()
    currency = clean_value(data.get("currency", "EUR")).upper() or "EUR"

    material = clean_value(data.get("material", ""))
    quantity = clean_value(data.get("quantity", ""))
    unit = clean_value(data.get("unit", "PC")).upper() or "PC"

    requested_delivery_date_raw = str(data.get("requested_delivery_date", "")).strip()
    requested_delivery_date = convert_to_sap_date(requested_delivery_date_raw)

    if len(distribution_channel) == 1:
        distribution_channel = distribution_channel.zfill(2)

    if len(division) == 1:
        division = division.zfill(2)

    missing = []

    required_values = {
        "sales_order_type": sales_order_type,
        "sales_org": sales_org,
        "distribution_channel": distribution_channel,
        "division": division,
        "sold_to_party": sold_to_party,
        "material": material,
        "quantity": quantity,
        "unit": unit,
        "requested_delivery_date": requested_delivery_date
    }

    for field_name, field_value in required_values.items():
        if not field_value:
            missing.append(field_name)

    if missing:
        return None, missing

    payload = {
        "SalesOrderType": sales_order_type,
        "SalesOrganization": sales_org,
        "DistributionChannel": distribution_channel,
        "OrganizationDivision": division,
        "SoldToParty": sold_to_party,
        "PurchaseOrderByCustomer": customer_po,
        "TransactionCurrency": currency,
        "RequestedDeliveryDate": requested_delivery_date,
        "to_Item": {
            "results": [
                {
                    "SalesOrderItem": "000010",
                    "Material": material,
                    "RequestedQuantity": quantity,
                    "RequestedQuantityUnit": unit
                }
            ]
        }
    }

    return payload, []


def create_sales_order(payload):
    return sap_post(SO_URL, payload)


def format_sap_error(response_text):
    try:
        response = json.loads(response_text)

        error = response.get("error", {})
        inner = error.get("innererror", {})

        errors = []
        warnings = []

        error_map = {
            "No master record exists for customer":
                "Customer does not exist in SAP.\n"
                "Recommendation: Verify the Sold-To Party or create the customer first.",

            "Customer":
                "Customer master data was not found.\n"
                "Recommendation: Use an existing customer number.",

            "Sales area":
                "Invalid Sales Area combination.\n"
                "Recommendation: Verify Sales Org, Distribution Channel and Division.",

            "Sales organization":
                "Invalid Sales Organization.\n"
                "Recommendation: Verify the Sales Organization code.",

            "Distribution channel":
                "Invalid Distribution Channel.\n"
                "Recommendation: Verify the Distribution Channel.",

            "Division":
                "Invalid Division.\n"
                "Recommendation: Verify the Division code.",

            "Material":
                "Material was not found or not extended to the sales area.\n"
                "Recommendation: Verify the Material Number and its sales view.",

            "Order unit":
                "Invalid Unit of Measure.\n"
                "Recommendation: Use the correct unit for this material, for example PC.",

            "Requested delivery date":
                "Requested Delivery Date is invalid.\n"
                "Recommendation: Provide a valid future delivery date.",

            "No tax code":
                "Tax Code is missing.\n"
                "Recommendation: Provide a valid Tax Code.",

            "Currency":
                "Invalid Currency.\n"
                "Recommendation: Provide a valid Currency, for example EUR.",

            "SD document":
                None
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

            if translated is None:
                continue

            if severity == "error":
                errors.append(translated)

            elif severity == "warning":
                warnings.append(translated)

        errors = list(dict.fromkeys(errors))
        warnings = list(dict.fromkeys(warnings))

        output = (
            "========================================\n"
            "   SALES ORDER CREATION FAILED\n"
            "========================================\n\n"
        )

        if errors:
            output += "Errors\n"
            output += "----------------------------------------\n"

            for i, msg in enumerate(errors, 1):
                output += f"{i}. {msg}\n\n"

        if warnings:
            output += "Warnings\n"
            output += "----------------------------------------\n"

            for i, msg in enumerate(warnings, 1):
                output += f"{i}. {msg}\n\n"

        if not errors and not warnings:
            output += "Unknown SAP error occurred."

        return output

    except Exception as e:
        return (
            "========================================\n"
            "   SALES ORDER CREATION FAILED\n"
            "========================================\n\n"
            "Unable to interpret SAP response.\n\n"
            f"Parser Error: {str(e)}\n\n"
            "Raw Response:\n"
            f"{response_text}"
        )


def run_agent(question):
    global pending_action

    question = question.strip()
    lower_q = question.lower()

    # ============================================
    # YES - Create Sales Order
    # ============================================
    if (
        pending_action
        and pending_action.get("action") == "create_sales_order"
        and lower_q in ["yes", "y", "approve", "confirm", "ok", "go ahead"]
    ):
        payload = pending_action["payload"]
        pending_action = None

        # -------------------------------------------------------
        # Authorization Check - Sales Order Create
        # -------------------------------------------------------
        auth_result = check_authorization(
            SAP_USER,
            "SALES_ORDER",
            "CREATE"
        )

        if not auth_result.get("authorized"):
            return format_authorization_denied(auth_result)

        result = create_sales_order(payload)

        if result.get("status") == "success":
            so_number = "Not Available"

            try:
                response_json = json.loads(result.get("response", "{}"))

                if "d" in response_json:
                    so_number = response_json["d"].get("SalesOrder", "Not Available")
                else:
                    so_number = response_json.get("SalesOrder", "Not Available")

            except Exception:
                pass

            return (
                "\n"
                "========================================\n"
                "     SALES ORDER CREATED SUCCESSFULLY\n"
                "========================================\n\n"
                "SAP Agent has successfully created the Sales Order.\n\n"
                f"Sales Order Number   : {so_number}\n"
                f"Sold-To Party        : {payload['SoldToParty']}\n"
                f"Sales Organization   : {payload['SalesOrganization']}\n"
                f"Distribution Channel : {payload['DistributionChannel']}\n"
                f"Division             : {payload['OrganizationDivision']}\n\n"
                "Status               : SUCCESS\n\n"
                "The Sales Order has been created successfully."
            )

        return format_sap_error(result.get("response", ""))

    # ============================================
    # NO - Cancel
    # ============================================
    if (
        pending_action
        and lower_q in ["no", "n", "cancel", "stop", "reject"]
    ):
        pending_action = None
        return "Cancelled. No changes were made in SAP."

    # ============================================
    # Missing field collection
    # ============================================
    if (
        pending_action
        and pending_action.get("action") == "collect_missing_fields"
    ):
        if "," in question:
            values = [v.strip() for v in question.split(",") if v.strip()]

        elif ";" in question:
            values = [v.strip() for v in question.split(";") if v.strip()]

        else:
            values = [
                v.strip()
                for v in re.split(r"\r?\n", question)
                if v.strip()
            ]

        missing_fields = pending_action["missing_fields"]

        if len(values) != len(missing_fields):
            return (
                f"I am expecting {len(missing_fields)} value(s).\n"
                f"You entered {len(values)}.\n"
                "Please provide exactly one value per field."
            )

        data = pending_action["partial_data"]

        for field, value in zip(missing_fields, values):
            data[field] = value

        pending_action = None

        payload, missing = build_so_payload(data)

        if missing:
            pending_action = {
                "action": "collect_missing_fields",
                "partial_data": data,
                "missing_fields": missing
            }

            available_fields = []

            for key, value in data.items():
                if value not in ["", None]:
                    if key == "sales_order_type":
                        continue

                    available_fields.append(
                        f"{key.replace('_', ' ').title():25} : {value}"
                    )

            available_text = "\n".join(available_fields)

            missing_text = "\n".join(
                f"{i + 1}. {field.replace('_', ' ').title()}"
                for i, field in enumerate(missing)
            )

            return (
                "========================================\n"
                "        SALES COPILOT\n"
                "========================================\n\n"
                "Information Already Received\n\n"
                f"{available_text}\n\n"
                "----------------------------------------\n\n"
                "Still Required\n\n"
                f"{missing_text}\n\n"
                "----------------------------------------\n\n"
                "Paste the remaining values in this order:\n\n"
                "TT01,10,10,5,PC,2026-07-20"
            )

        pending_action = {
            "action": "create_sales_order",
            "payload": payload
        }

        item = payload["to_Item"]["results"][0]

        return (
            "\n"
            "========================================\n"
            "        SALES ORDER PREVIEW\n"
            "========================================\n\n"
            "HEADER INFORMATION\n"
            "----------------------------------------\n"
            f"Sales Order Type       : {payload.get('SalesOrderType')}\n"
            f"Sales Organization     : {payload.get('SalesOrganization')}\n"
            f"Distribution Channel   : {payload.get('DistributionChannel')}\n"
            f"Division               : {payload.get('OrganizationDivision')}\n"
            f"Sold-To Party          : {payload.get('SoldToParty')}\n"
            f"Customer PO            : {payload.get('PurchaseOrderByCustomer') or '-'}\n"
            f"Currency               : {payload.get('TransactionCurrency')}\n"
            f"Requested Delivery Date: {payload.get('RequestedDeliveryDate')}\n\n"
            "ITEM INFORMATION\n"
            "----------------------------------------\n"
            f"Material               : {item.get('Material')}\n"
            f"Quantity               : {item.get('RequestedQuantity')} {item.get('RequestedQuantityUnit')}\n\n"
            "----------------------------------------\n"
            "Ready to create this Sales Order.\n\n"
            "Reply YES to continue.\n"
            "Reply NO to cancel."
        )

    # ============================================
    # AI Router
    # ============================================
    route = ai_router(question)
    action = route.get("action", "unknown")

    # ============================================
    # Get Sales Order
    # ============================================
    if action == "get_sales_order":
        return get_sales_order(
            route.get("sales_order", "")
        )

    # ============================================
    # Create Sales Order
    # ============================================
    if action == "create_sales_order":
        data = route.get("data", {})
        payload, missing = build_so_payload(data)

        if missing:
            pending_action = {
                "action": "collect_missing_fields",
                "partial_data": data,
                "missing_fields": missing
            }

            available_fields = []

            for key, value in data.items():
                if value not in ["", None]:
                    if key == "sales_order_type":
                        continue

                    available_fields.append(
                        f"{key.replace('_', ' ').title():25} : {value}"
                    )

            available_text = "\n".join(available_fields)

            missing_text = "\n".join(
                f"{i + 1}. {field.replace('_', ' ').title()}"
                for i, field in enumerate(missing)
            )

            return (
                "========================================\n"
                "        SALES COPILOT\n"
                "========================================\n\n"
                "Information Already Received\n\n"
                f"{available_text}\n\n"
                "----------------------------------------\n\n"
                "Still Required\n\n"
                f"{missing_text}\n\n"
                "----------------------------------------\n\n"
                "Paste the remaining values in this order:\n\n"
                "TT01,10,10,5,PC,2026-07-20"
            )

        pending_action = {
            "action": "create_sales_order",
            "payload": payload
        }

        item = payload["to_Item"]["results"][0]

        return (
            "\n"
            "========================================\n"
            "        SALES ORDER PREVIEW\n"
            "========================================\n\n"
            "HEADER INFORMATION\n"
            "----------------------------------------\n"
            f"Sales Order Type       : {payload.get('SalesOrderType')}\n"
            f"Sales Organization     : {payload.get('SalesOrganization')}\n"
            f"Distribution Channel   : {payload.get('DistributionChannel')}\n"
            f"Division               : {payload.get('OrganizationDivision')}\n"
            f"Sold-To Party          : {payload.get('SoldToParty')}\n"
            f"Customer PO            : {payload.get('PurchaseOrderByCustomer') or '-'}\n"
            f"Currency               : {payload.get('TransactionCurrency')}\n"
            f"Requested Delivery Date: {payload.get('RequestedDeliveryDate')}\n\n"
            "ITEM INFORMATION\n"
            "----------------------------------------\n"
            f"Material               : {item.get('Material')}\n"
            f"Quantity               : {item.get('RequestedQuantity')} {item.get('RequestedQuantityUnit')}\n\n"
            "----------------------------------------\n"
            "Ready to create this Sales Order.\n\n"
            "Reply YES to continue.\n"
            "Reply NO to cancel."
        )

    # ============================================
    # Fallback
    # ============================================
    return (
        "I can help you:\n\n"
        "- Create Sales Orders\n"
        "- View Sales Orders\n"
        "- Explain Sales Orders"
    )


if __name__ == "__main__":
    print("SAP Sales Order Agent started")
    print("Type exit to stop\n")

    while True:
        question = input("You: ").strip()

        if question.lower() in ["exit", "quit", "bye"]:
            print("Assistant: Bye")
            break

        print("\nAssistant:")
        print(run_agent(question))
        print()