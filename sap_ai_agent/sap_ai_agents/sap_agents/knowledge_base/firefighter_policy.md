# SAP Firefighter Policy Knowledge Base

## Purpose

The SAP Firefighter functionality provides temporary elevated access to authorized users for emergency or exceptional business situations where normal authorizations are insufficient.

The SAP AI Assistant uses this policy to assist controllers during Firefighter session reviews. The AI provides recommendations only. Final approval remains the responsibility of the assigned Controller.

---

# Key Principles


- Firefighter access is granted only to authorized users.
- Firefighter IDs are assigned for emergency business activities.
- Activities must match the approved business reason.
- All activities are logged and reviewed.
- Every Firefighter ID has an assigned Owner and Controller.
- FF_ALL is the only Firefighter ID allowed to have SAP_ALL authorization.
- Firefighter assignments are reviewed quarterly.
- Firefighter IDs are valid for one year unless renewed.

## 1. Authorized Access

SAP Firefighter access shall be granted only to authorized individuals based on their job responsibilities.

AI Validation

- Verify Firefighter User exists
- Verify Firefighter ID exists
- Verify Firefighter assignment information is available

---

## 2. Assignment Validity

Firefighter roles are granted for one year.

After one year, the assignment must be reconfirmed.

AI Validation

- Verify assignment validity if available
- If validity information is unavailable, mention it in the report

---

## 3. Appropriate Usage

Firefighter users shall use elevated privileges only for authorized business purposes.

Firefighter access shall not be used for personal gain or unauthorized activities.

AI Validation

- Review stated business reason
- Compare executed activities with the stated reason
- Highlight activities that appear inconsistent

---

## 4. Monitoring

All Firefighter activities must be monitored and logged.

AI Validation

Verify:

- Login Time
- Logout Time
- Executed Activities
- Activity Log availability

---

## 5. Approval

All Firefighter access requests must be reviewed and approved according to company procedures.

AI Validation

Verify:

- Controller assigned
- Owner assigned
- Review information available

---

## 6. SAP_ALL Restriction

Only FF_ALL account may have SAP_ALL authorization.

AI Validation

If authorization information becomes available:

- Verify only FF_ALL has SAP_ALL

---

## 7. Quarterly Review

Firefighter assignments are reviewed quarterly.

AI Validation

If review dates become available:

- Verify review status

---

## 8. Firefighter Ownership

Every Firefighter account must have an assigned Owner responsible for monitoring.

Exceptions:

- FF_O2C_WEB1
- FF_O2C_WEB2
- FF_REL