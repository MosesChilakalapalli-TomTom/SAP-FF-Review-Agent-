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

PO_URL = f"{SAP_HOST}/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrder"

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


def sap_get(url, params=None):
    query = {
        "sap-client": SAP_CLIENT,
        "saml2": "disabled",
        "$format": "json"
    }

    if params:
        query.update(params)

    try:
        response = session.get(url, params=query, timeout=60)

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


def get_purchase_order(po_number):
    po_number = clean_value(po_number)

    if not po_number:
        return "Purchase Order number is missing."

    # -------------------------------------------------------
    # Authorization Check - PO Display
    # -------------------------------------------------------
    auth_result = check_authorization(
                SAP_USER,
                "PURCHASE_ORDER",
                "CREATE"
            )

    if not auth_result.get("authorized"):
        return format_authorization_denied(auth_result)

    data = sap_get(
        PO_URL,
        {
            "$filter": f"PurchaseOrder eq '{po_number}'",
            "$expand": "to_PurchaseOrderItem"
        }
    )

    if data.get("status") == "error":
        return f"SAP Error: {data}"

    results = data.get("d", {}).get("results", [])

    if not results:
        return f"Purchase Order {po_number} not found."

    po = results[0]
    items = po.get("to_PurchaseOrderItem", {}).get("results", [])

    item_text = ""

    for item in items:
        item_text += (
            f"\nItem: {item.get('PurchaseOrderItem')}"
            f"\nMaterial: {item.get('Material')}"
            f"\nPlant: {item.get('Plant')}"
            f"\nQuantity: {item.get('OrderQuantity')} {item.get('PurchaseOrderQuantityUnit')}"
            f"\nNet Price: {item.get('NetPriceAmount')}"
            f"\n"
        )

    return (
        f"Purchase Order Found\n"
        f"PO Number: {po.get('PurchaseOrder')}\n"
        f"Company Code: {po.get('CompanyCode')}\n"
        f"PO Type: {po.get('PurchaseOrderType')}\n"
        f"Supplier: {po.get('Supplier')}\n"
        f"Purchasing Org: {po.get('PurchasingOrganization')}\n"
        f"Purchasing Group: {po.get('PurchasingGroup')}\n"
        f"Currency: {po.get('DocumentCurrency')}\n"
        f"Created By: {po.get('CreatedByUser')}\n"
        f"Created On: {po.get('CreationDate')}\n"
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
            "message": "SAP request timed out after 120 seconds. Check SAP backend or see if PO was created."
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


def ai_router(question):
    prompt = """
You are a secure SAP assistant router.
Return ONLY valid JSON. No markdown. No explanation.

Actions:
- get_purchase_order
- create_purchase_order
- unknown

For GET purchase order, return:
{
  "action": "get_purchase_order",
  "po_number": "",
  "data": {}
}

For CREATE purchase order, return:
{
  "action": "create_purchase_order",
  "po_number": "",
  "data": {
    "company_code": "",
    "po_type": "",
    "supplier": "",
    "supplying_plant": "",
    "purchasing_org": "",
    "purchasing_group": "",
    "currency": "",
    "material": "",
    "plant": "",
    "quantity": "",
    "unit": "",
    "price": ""
  }
}

Rules:
- If user asks to check, show, get, track, or display a purchase order, use get_purchase_order and extract PO number into po_number.
- If user asks to create purchase order or PO, use create_purchase_order.
- Extract only simple values.
- If purchase order type is missing, use NB.
- If currency is missing, use EUR.
- If unit is missing, leave it blank.
- Only NB creation is supported for now.
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
        max_tokens=400
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
            "po_number": "",
            "data": {}
        }


def build_po_payload(data):
    po_type = clean_value(data.get("po_type", "NB")).upper() or "NB"

    if po_type != "NB":
        return None, [
            f"PO type {po_type} is not supported. Only NB is supported for creation."
        ]

    company_code = clean_value(data.get("company_code", "")).upper()
    supplier = clean_value(data.get("supplier", "")).upper()
    purchasing_org = clean_value(data.get("purchasing_org", "")).upper()
    purchasing_group = clean_value(data.get("purchasing_group", "")).upper()
    currency = clean_value(data.get("currency", "EUR")).upper() or "EUR"

    material = clean_value(data.get("material", ""))
    plant = clean_value(data.get("plant", "")).upper()
    quantity = clean_value(data.get("quantity", ""))
    unit = clean_value(data.get("unit", "")).upper()
    price = clean_value(data.get("price", ""))

    missing = []

    required_values = {
        "company_code": company_code,
        "po_type": po_type,
        "supplier": supplier,
        "purchasing_org": purchasing_org,
        "purchasing_group": purchasing_group,
        "currency": currency,
        "material": material,
        "plant": plant,
        "quantity": quantity,
        "unit": unit,
        "price": price
    }

    for field_name, field_value in required_values.items():
        if not field_value:
            missing.append(field_name)

    if missing:
        return None, missing

    payload = {
        "CompanyCode": company_code,
        "PurchaseOrderType": po_type,
        "Supplier": supplier,
        "PurchasingOrganization": purchasing_org,
        "PurchasingGroup": purchasing_group,
        "DocumentCurrency": currency,
        "to_PurchaseOrderItem": {
            "results": [
                {
                    "PurchaseOrderItem": "00010",
                    "Material": material,
                    "Plant": plant,
                    "OrderQuantity": quantity,
                    "PurchaseOrderQuantityUnit": unit,
                    "NetPriceAmount": price
                }
            ]
        }
    }

    return payload, []


def create_purchase_order(payload):
    print("\n========== FINAL PO PAYLOAD ==========")
    print(json.dumps(payload, indent=4))
    print("======================================\n")

    result = sap_post(PO_URL, payload)

    return result


def format_sap_error(response_text):
    try:
        response = json.loads(response_text)

        error = response.get("error", {})
        inner = error.get("innererror", {})

        errors = []
        warnings = []

        error_map = {
            "No master record exists for supplier":
                "Supplier does not exist in SAP.\n"
                "Recommendation: Verify the supplier number or create the supplier first.",

            "Supplier master data":
                "Supplier master data was not found.\n"
                "Recommendation: Use an existing supplier.",

            "Order unit":
                "Invalid Unit of Measure.\n"
                "Recommendation: Use the correct unit for this material, for example PC.",

            "Plant":
                "Invalid Plant.\n"
                "Recommendation: Verify the Plant code.",

            "Material":
                "Material was not found.\n"
                "Recommendation: Verify the Material Number.",

            "No tax code":
                "Tax Code is missing.\n"
                "Recommendation: Provide a valid Tax Code, for example 5F.",

            "PO header data still faulty":
                None,

            "Purchase organization":
                "Purchasing Organization is invalid.\n"
                "Recommendation: Verify the Purchasing Organization.",

            "Purchasing group":
                "Purchasing Group is invalid.\n"
                "Recommendation: Verify the Purchasing Group."
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
            " PURCHASE ORDER CREATION FAILED\n"
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
            " PURCHASE ORDER CREATION FAILED\n"
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
    # YES - Create PO
    # ============================================
    if (
        pending_action
        and pending_action.get("action") == "create_purchase_order"
        and lower_q in ["yes", "y", "approve", "confirm", "ok", "go ahead"]
    ):

        payload = pending_action["payload"]
        pending_action = None

        # -------------------------------------------------------
        # Authorization Check - PO Create
        # -------------------------------------------------------
        auth_result = check_authorization(
            SAP_USER,
            "PURCHASE_ORDER",
            "CREATE"
        )

        if not auth_result.get("authorized"):
            return format_authorization_denied(auth_result)

        result = create_purchase_order(payload)

        if result.get("status") == "success":
            po_number = "Not Available"

            try:
                response_json = json.loads(result.get("response", "{}"))

                if "d" in response_json:
                    po_number = response_json["d"].get("PurchaseOrder", "Not Available")
                else:
                    po_number = response_json.get("PurchaseOrder", "Not Available")

            except Exception as e:
                print("PO Number Extraction Error:", e)

            return (
                "\n"
                "========================================\n"
                "   PURCHASE ORDER CREATED SUCCESSFULLY\n"
                "========================================\n\n"
                "SAP Agent has successfully created the Purchase Order.\n\n"
                f"Purchase Order Number : {po_number}\n"
                f"Supplier              : {payload['Supplier']}\n"
                f"Company Code          : {payload['CompanyCode']}\n"
                f"Purchasing Org        : {payload['PurchasingOrganization']}\n\n"
                "Status                : SUCCESS\n\n"
                "The document has been saved successfully."
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

        payload, missing = build_po_payload(data)

        if missing:
            pending_action = {
                "action": "collect_missing_fields",
                "partial_data": data,
                "missing_fields": missing
            }

            available_fields = []

            for key, value in data.items():
                if value not in ["", None]:
                    if key == "po_type":
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
                "      PROCUREMENT COPILOT\n"
                "========================================\n\n"
                "Information Already Received\n\n"
                f"{available_text}\n\n"
                "----------------------------------------\n\n"
                "Still Required\n\n"
                f"{missing_text}\n\n"
                "----------------------------------------\n\n"
                "Paste the remaining values in this order:\n\n"
                "NL11,ST01,S01,NL11,5,10"
            )

        pending_action = {
            "action": "create_purchase_order",
            "payload": payload
        }

        item = payload["to_PurchaseOrderItem"]["results"][0]

        return (
            "\n"
            "========================================\n"
            "        PURCHASE ORDER PREVIEW\n"
            "========================================\n\n"
            "HEADER INFORMATION\n"
            "----------------------------------------\n"
            f"Company Code         : {payload.get('CompanyCode')}\n"
            f"PO Type              : {payload.get('PurchaseOrderType')}\n"
            f"Supplier             : {payload.get('Supplier')}\n"
            f"Purchasing Org       : {payload.get('PurchasingOrganization')}\n"
            f"Purchasing Group     : {payload.get('PurchasingGroup')}\n"
            f"Currency             : {payload.get('DocumentCurrency')}\n\n"
            "ITEM INFORMATION\n"
            "----------------------------------------\n"
            f"Material             : {item.get('Material')}\n"
            f"Plant                : {item.get('Plant')}\n"
            f"Quantity             : {item.get('OrderQuantity')} {item.get('PurchaseOrderQuantityUnit')}\n"
            f"Net Price            : {item.get('NetPriceAmount')} {payload.get('DocumentCurrency')}\n\n"
            "----------------------------------------\n"
            "Ready to create this Purchase Order.\n\n"
            "Reply YES to continue.\n"
            "Reply NO to cancel."
        )

    # ============================================
    # AI Router
    # ============================================
    route = ai_router(question)

    action = route.get("action", "unknown")

    # ============================================
    # Get PO
    # ============================================
    if action == "get_purchase_order":
        return get_purchase_order(
            route.get("po_number", "")
        )

    # ============================================
    # Create PO
    # ============================================
    if action == "create_purchase_order":

        data = route.get("data", {})

        payload, missing = build_po_payload(data)

        if missing:
            pending_action = {
                "action": "collect_missing_fields",
                "partial_data": data,
                "missing_fields": missing
            }

            available_fields = []

            for key, value in data.items():
                if value not in ["", None]:
                    if key == "po_type":
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
                "      PROCUREMENT COPILOT\n"
                "========================================\n\n"
                "Information Already Received\n\n"
                f"{available_text}\n\n"
                "----------------------------------------\n\n"
                "Still Required\n\n"
                f"{missing_text}\n\n"
                "----------------------------------------\n\n"
                "Paste the remaining values in this order:\n\n"
                "NL11,ST01,S01,NL11,5,10"
            )

        pending_action = {
            "action": "create_purchase_order",
            "payload": payload
        }

        item = payload["to_PurchaseOrderItem"]["results"][0]

        return (
            "\n"
            "========================================\n"
            "        PURCHASE ORDER PREVIEW\n"
            "========================================\n\n"
            "HEADER INFORMATION\n"
            "----------------------------------------\n"
            f"Company Code         : {payload.get('CompanyCode')}\n"
            f"PO Type              : {payload.get('PurchaseOrderType')}\n"
            f"Supplier             : {payload.get('Supplier')}\n"
            f"Purchasing Org       : {payload.get('PurchasingOrganization')}\n"
            f"Purchasing Group     : {payload.get('PurchasingGroup')}\n"
            f"Currency             : {payload.get('DocumentCurrency')}\n\n"
            "ITEM INFORMATION\n"
            "----------------------------------------\n"
            f"Material             : {item.get('Material')}\n"
            f"Plant                : {item.get('Plant')}\n"
            f"Quantity             : {item.get('OrderQuantity')} {item.get('PurchaseOrderQuantityUnit')}\n"
            f"Net Price            : {item.get('NetPriceAmount')} {payload.get('DocumentCurrency')}\n\n"
            "----------------------------------------\n"
            "Ready to create this Purchase Order.\n\n"
            "Reply YES to continue.\n"
            "Reply NO to cancel."
        )

    # ============================================
    # Fallback
    # ============================================
    return (
        "I can help you:\n\n"
        "- Create Purchase Orders\n"
        "- View Purchase Orders\n"
        "- Explain Purchase Orders"
    )


if __name__ == "__main__":
    print("SAP AI Agent started")
    print("Type exit to stop\n")

    while True:
        question = input("You: ").strip()

        if question.lower() in ["exit", "quit", "bye"]:
            print("Assistant: Bye")
            break

        print("\nAssistant:")
        print(run_agent(question))
        print()