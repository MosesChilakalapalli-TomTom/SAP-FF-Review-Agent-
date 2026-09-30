# Firefighter Access Matrix

## Authorized Firefighter Users

| User | Firefighter ID | Description |
|------|---------------|-------------|
| Moses Chilakalapalli | FF_MDM | Firefighter - Master Data Management |
| Bhaskar Nadargi | FF_ALL | Firefighter - All Access |
| Ron Hogeboom | FF_ALL | Firefighter - All Access |
| Srinivasu Koppada | FF_ALL | Firefighter - All Access |
| Sravanalaxmi Vishwanadha | FF_O2C_WEB1 | Firefighter - Order to Cash Web |
| Nicola Leonard | FF_ITBI | Firefighter - IT BI |
| Murali Chilakalapalli | FF_GRCAC | Firefighter - GRC Admin |
| Milind Patil | FF_ALL | Firefighter - All Access |
| Eric Soffer | FF_ALL | Firefighter - All Access |
| Elena Sadovnikova | FF_ALL | Firefighter - All Access |
| CTAC-ADM | FF_ALL | Firefighter - All Access |
| Akshay Bolia | FF_ALL | Firefighter - All Access |
| CTAC-BEHEER | FF_ITBAS | Firefighter - IT Basis |

---

# FF_MDM

## Firefighter ID
FF_MDM

## Business Area
Master Data Management

## Purpose
Emergency access for creation, maintenance, correction, and support of SAP master data.

## Expected Transaction Categories

- Customer Master Management
- Vendor Master Management
- Material Master Maintenance
- Business Partner Maintenance
- Data Correction Activities

## Typical Business Activities

- Customer master maintenance
- Vendor master maintenance
- Material master updates
- Business partner maintenance
- Master data correction activities

## Allowed Activities

- Create and maintain master data records
- Correct data inconsistencies
- Support urgent business operations requiring master data updates

## Restricted Activities

- Financial posting activities unrelated to master data
- Security administration changes
- Basis administration activities

## Special Rules

### BP

Expected for Business Partner maintenance.

### XK02

Expected for Vendor Master updates.

### XD02

Expected for Customer Master maintenance.

### MM02

Expected for Material Master maintenance.

## AI Review Rules

### Approve if

- Activity relates to master data maintenance.
- Business justification is documented.
- Session activities align with master data support.

### Escalate if

- Sensitive transactions unrelated to master data are executed.
- Security, finance, or basis activities are performed without justification.

---

# FF_ALL

## Firefighter ID
FF_ALL

## Business Area
Cross-Functional SAP Support

## Purpose

Emergency access providing broad SAP authorization for critical business and technical support activities.

## Expected Transaction Categories

- Incident Resolution
- Production Support
- Emergency Fixes
- Cross-Functional Troubleshooting
- Configuration Validation

## Typical Business Activities

- Incident resolution
- Production support
- Configuration validation
- Emergency system corrections
- Cross-module troubleshooting

## Allowed Activities

- Activities necessary for approved emergency support
- Cross-functional business process validation
- Critical production issue resolution

## Restricted Activities

- Activities not related to approved business justification
- Unauthorized master data manipulation
- User/security maintenance without approval

## Special Rules

Because FF_ALL provides broad access, transaction reviews must focus on the documented business reason.

No transaction should automatically be considered suspicious solely because it appears sensitive.

### SE16N

Expected during troubleshooting and analysis.

### SE38

Expected when executing approved support programs.

### SM37

Expected during production incident investigation.

### ST22

Expected during dump analysis.

## AI Review Rules

### Approve if

- Activities match the documented emergency reason.
- All executed transactions are justified and logged.

### Request Justification if

- Activities are broad but business context is unclear.

### Escalate if

- High-risk activities are performed without sufficient justification.

---

# FF_O2C_WEB1

## Firefighter ID
FF_O2C_WEB1

## Business Area
Order to Cash (O2C)

## Purpose

Emergency access for Order-to-Cash web applications and related SAP business processes.

## Expected Transaction Categories

- Sales Order Processing
- Web Order Processing
- Customer Order Support
- IDOC Monitoring
- Order Troubleshooting

## Typical Business Activities

- Sales order troubleshooting
- Customer order processing support
- Order status validation
- O2C integration issue resolution

## Allowed Activities

- Order monitoring and corrections
- Customer order support
- Business process troubleshooting

## Restricted Activities

- Security administration
- Basis administration
- Financial configuration changes

## Special Rules

### VA01

VA01 may be triggered automatically during Web Order IDOC processing.

Automatically generated sales orders should be treated as expected activity.

Only flag VA01 when there is evidence that it was manually executed.

### BD87

Expected during IDOC reprocessing.

### WE02

Expected during IDOC monitoring.

### WE05

Expected during IDOC analysis.

### WE19

Expected only during approved testing activities.

## AI Review Rules

### Approve if

- Activities support Order-to-Cash operations.
- Business reason aligns with executed transactions.
- VA01 activity is consistent with Web Order processing.

### Escalate if

- Activities fall outside Order-to-Cash scope.
- Manual VA01 execution appears unrelated to the approved business reason.

---

# FF_ITBI

## Firefighter ID
FF_ITBI

## Business Area
IT Business Intelligence

## Purpose

Emergency access for BI, reporting, analytics, and data investigation activities.

## Expected Transaction Categories

- Reporting
- Analytics
- BI Support
- BW Administration
- Data Validation

## Typical Business Activities

- Report validation
- Data analysis
- BI troubleshooting
- Analytics support

## Allowed Activities

- Execute reports
- Analyze and validate data
- Resolve BI-related incidents

## Restricted Activities

- Production configuration changes
- Security administration
- Basis administration

## Special Rules

### RSA1

Expected for BW administration.

### RSMO

Expected for BW request monitoring.

### SM37

Expected when reviewing BW jobs.

## AI Review Rules

### Approve if

- Activities are related to reporting, analytics, or BI support.

### Escalate if

- Activities exceed BI operational scope.

---

# FF_GRCAC

## Firefighter ID
FF_GRCAC

## Business Area
SAP GRC Access Control

## Purpose

Emergency administrative access for SAP GRC Access Control support and maintenance.

## Expected Transaction Categories

- Firefighter Administration
- Risk Analysis
- Access Control
- Workflow Management

## Typical Business Activities

- Access request troubleshooting
- Firefighter administration
- Risk analysis support
- GRC workflow maintenance

## Allowed Activities

- GRC Access Control administration
- Firefighter management
- Access governance support

## Restricted Activities

- Basis administration
- Business transaction processing unrelated to GRC

## Special Rules

### GRAC*

Expected for GRC administration activities.

### Firefighter Log Reviews

Expected when investigating access issues.

## AI Review Rules

### Approve if

- Activities support GRC administration or access governance.

### Escalate if

- Activities are unrelated to GRC processes.

---

# FF_ITBAS

## Firefighter ID
FF_ITBAS

## Business Area
SAP Basis

## Purpose

Emergency access for SAP Basis administration, monitoring, and technical support activities.

## Expected Transaction Categories

- Basis Administration
- Monitoring
- Background Job Management
- System Analysis
- Technical Troubleshooting

## Typical Business Activities

- System monitoring
- Job management
- Transport management
- Performance analysis
- Technical troubleshooting

## Allowed Activities

- Basis administration
- Technical support
- System monitoring and maintenance

## Restricted Activities

- Business transaction processing unrelated to Basis operations

## Special Rules

### SM37

Expected for job monitoring and troubleshooting.

### ST22

Expected for dump analysis.

### SM21

Expected for system log analysis.

### SM50

Expected for work process monitoring.

### SM51

Expected for application server monitoring.

### SU53

Expected for authorization troubleshooting.

### AL08

Expected for session monitoring.

## AI Review Rules

### Approve if

- Activities align with Basis administration responsibilities.

### Escalate if

- Business transactions are executed without technical justification.

---

# Global Special Rules

## IDOC Processing

### BD87

Expected for IDOC reprocessing.

### WE02

Expected for IDOC monitoring.

### WE05

Expected for IDOC analysis.

### WE19

Expected only during approved testing.

---

## Transport Management

### STMS

Expected for transport activities.

### SE09

Expected for transport release.

### SE10

Expected for transport administration.

---

## Financial Interfaces

### FB01

FB01 may be executed automatically by SAP during Concur IDOC processing.

This should not automatically be treated as a manual financial posting.

Only flag FB01 where evidence indicates manual execution outside the approved interface process.

---

## Basis Activities

### SM37

Expected for Basis troubleshooting.

### ST22

Expected for dump analysis.

### SM21

Expected for system log analysis.

---

# Controller Review Guidance

The Controller should verify:

- Business reason matches activities performed.
- Firefighter ID scope matches executed transactions.
- Controller and Owner assignments are valid.
- Activity log is complete and reviewed.
- No unauthorized or unrelated activities were executed.
- Special Rules are considered before escalating activities.

---

# Approval Recommendation Logic

## Approve

- Business reason is valid.
- Activities match firefighter scope.
- Session is logged properly.
- Controller and Owner are assigned.
- Activities align with documented Special Rules.

## Request Justification

- Missing activity details.
- Business reason unclear.
- Insufficient documentation.
- Activities cannot be clearly linked to the stated purpose.

## Escalate

- Activities outside firefighter scope.
- Sensitive transactions lack justification.
- Potential policy or compliance violations.
- Activities remain unexplained after applying Special Rules.