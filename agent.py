import requests
from requests.auth import HTTPBasicAuth
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SAP_HOST = "https://s4-dev.sap.tomtomgroup.com"
SAP_CLIENT = "300"
SAP_USER = "vasum"
SAP_PASS = "Sap@123456"

# ✅ ✅ CORRECT ODATA URLS (use SAP_HOST everywhere)
COST_CENTER_ODATA_URL = f"https://s4-dev.sap.tomtomgroup.com/sap/opu/odata/sap/API_COSTCENTER_SRV/A_CostCenterText?saml2=disabled&sap-client=300"

SO_ODATA_URL = f"https://s4-dev.sap.tomtomgroup.com/sap/opu/odata/sap/API_SALES_ORDER_SRV/A_SalesOrder?saml2=disabled&sap-client=300"

PO_ODATA_URL = f"https://s4-dev.sap.tomtomgroup.com/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrder?saml2=disabled&sap-client=300"

BP_ODATA_URL = f"https://s4-dev.sap.tomtomgroup.com/sap/opu/odata/sap/API_BUSINESS_PARTNER/A_BusinessPartner?saml2=disabled&sap-client=300"


# ✅ COMMON SAP CALL
def call_sap(url, params):
    try:
        response = requests.get(
            url,
            params=params,
            auth=HTTPBasicAuth(SAP_USER, SAP_PASS),
            headers={"Accept": "application/json"},
            verify=False,
            timeout=30
        )

        if response.status_code != 200:
            return {
                "status": "error",
                "message": f"SAP returned {response.status_code}",
                "response": response.text[:300],
                "url": response.url
            }

        return response.json()

    except Exception as e:
        return {"status": "error", "message": str(e)}


# ✅ COST CENTER
def check_cost_center(cost_center: str, controlling_area: str = "TT01"):

    cost_center = cost_center.strip().upper()

    params = {
        "$format": "json",
        "$filter": f"CostCenter eq '{cost_center}' and ControllingArea eq '{controlling_area}'"
    }

    data = call_sap(COST_CENTER_ODATA_URL, params)

    if data.get("status") == "error":
        return f"❌ {data['message']}"

    results = data.get("d", {}).get("results", [])

    if not results:
        return f"❌ Cost center {cost_center} not found."

    cc = results[0]

    return f"✅ Cost Center Found\nCost Center: {cc.get('CostCenter')}\nName: {cc.get('CostCenterName')}\nEnd date : {cc.get('ValidityEndDate')}"


# ✅ SALES ORDER
def check_sales_order(so_number: str):

    so_number = so_number.strip()

    params = {
        "$format": "json",
        "$filter": f"SalesOrder eq '{so_number}'",
        "$select": (
            "SalesOrder,"
            "SoldToParty,"
            "TotalNetAmount,"
            "TransactionCurrency,"
            "PurchaseOrderByCustomer,"
            "CustomerPurchaseOrderDate,"
            "CreationDate"
        )
    }

    data = call_sap(SO_ODATA_URL, params)

    if data.get("status") == "error":
        return f"❌ {data['message']}\n{data.get('response','')}"

    results = data.get("d", {}).get("results", [])

    if not results:
        return f"❌ Sales Order {so_number} not found."

    so = results[0]

    return (
        f"✅ Sales Order Found\n"
        f"Sales Order: {so.get('SalesOrder')}\n"
        f"Sold-To Party: {so.get('SoldToParty')}\n"
        f"Net Value: {so.get('TotalNetAmount')} {so.get('TransactionCurrency')}\n"
        f"Customer Reference: {so.get('PurchaseOrderByCustomer')}\n"
        f"Customer Ref Date: {so.get('CustomerPurchaseOrderDate')}\n"
        f"Created On: {so.get('CreationDate')}"
    )


# ✅ PURCHASE ORDER
def check_purchase_order(po_number: str):

    po_number = po_number.strip()

    params = {
        "$format": "json",
        "$filter": f"PurchaseOrder eq '{po_number}'"
    }

    data = call_sap(PO_ODATA_URL, params)

    if data.get("status") == "error":
        return f"❌ {data['message']}\n{data.get('response','')}"

    results = data.get("d", {}).get("results", [])

    if not results:
        return f"❌ Purchase Order {po_number} not found."

    po = results[0]

    return (
        f"✅ Purchase Order Found\n"
        f"PO Number: {po.get('PurchaseOrder')}\n"
        f"Company Code: {po.get('CompanyCode')}\n"
        f"PO Type: {po.get('PurchaseOrderType')}\n"
        f"Supplier: {po.get('Supplier')}\n"
        f"Supplying Plant: {po.get('SupplyingPlant')}\n"
        f"Purchasing Org: {po.get('PurchasingOrganization')}\n"
        f"Purchasing Group: {po.get('PurchasingGroup')}\n"
        f"Currency: {po.get('DocumentCurrency')}\n"
        f"PO Date: {po.get('PurchaseOrderDate')}\n"
        f"Created On: {po.get('CreationDate')}\n"
        f"City: {po.get('AddressCityName')}"
    )


# ✅ ✅ BUSINESS PARTNER
def check_business_partner(bp_number: str):

    bp_number = bp_number.strip()

    params = {
        "$format": "json",
        "$filter": f"BusinessPartner eq '{bp_number}'"
    }

    data = call_sap(BP_ODATA_URL, params)

    if data.get("status") == "error":
        return f"❌ {data['message']}\n{data.get('response','')}"

    results = data.get("d", {}).get("results", [])

    if not results:
        return f"❌ Business Partner {bp_number} not found."

    bp = results[0]

    return (
        f"✅ Business Partner Found\n"
        f"BP Number: {bp.get('BusinessPartner')}\n"
        f"Name: {bp.get('BusinessPartnerFullName')}\n"
        f"Customer ID: {bp.get('Customer')}\n"
        f"Supplier ID: {bp.get('Supplier')}"
    )


# ✅ MAIN PROGRAM
if __name__ == "__main__":

    print("\n1. Cost Center")
    print("2. Sales Order")
    print("3. Purchase Order")
    print("4. Business Partner")

    choice = input("\nChoose option (1/2/3/4): ").strip()

    if choice == "1":
        print("\n" + check_cost_center(input("Enter cost center: ")))

    elif choice == "2":
        print("\n" + check_sales_order(input("Enter Sales Order: ")))

    elif choice == "3":
        print("\n" + check_purchase_order(input("Enter Purchase Order: ")))

    elif choice == "4":
        print("\n" + check_business_partner(input("Enter BP: ")))

    else:
        print("Invalid option")