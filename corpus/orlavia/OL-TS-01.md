---
doc_id: OL-TS-01
title: ORTS reporting specification v2
country: OL
doc_type: technical_spec
version: "2"
published: 2025-02-01
valid_from: 2025-02-01
valid_to: null
announces: []
supersedes: []
authority: 2
lang: en
---
# ORTS reporting specification v2

## 1. Scope
This specification describes the invoice content required for real-time reporting to ORTS. Invoices follow the Core
Invoice Model (COM-02) in UBL 2.1 syntax with the Orlavian rules OL-01 to OL-05. The reporting deadline is set by
decree (currently 24 hours from the time of issue).

## 2. Tax identification numbers
An Orlavian tax ID consists of the letters OL followed by ten digits, for example OL1234567890. The seller's tax ID must
be an Orlavian tax ID (rule OL-01). Invoices to consumers do not need a buyer tax ID.

## 3. Issue time
Every invoice states its issue time in `cbc:IssueTime` (hh:mm:ss, Orlavian local time), because the reporting deadline
runs from the time of issue (rule OL-05).

## 4. QR payload
Every invoice carries the ORTS QR payload in `cac:AdditionalDocumentReference/cbc:ID` with `schemeID="ORTS-QR"`
(rule OL-02). The payload is a single line of fields separated by `|`, in this order:

`ORTS1|seller tax ID|invoice number|issue date|issue time|total with VAT|currency|hash`

The total with VAT is written with two decimals. The hash is the first 16 characters of the lowercase hexadecimal
SHA-256 digest of the UTF-8 text `seller tax ID|invoice number|issue date|issue time|total with VAT|currency`. The
payload must match the invoice it is printed on (rule OL-03).

## 5. Self-billing
A self-billed invoice uses the invoice type code 389. It must reference the self-billing agreement in
`cac:ContractDocumentReference`, with `cbc:DocumentTypeCode` "SBA" and the agreement number in `cbc:ID` (rule OL-04).

## 6. Responses
ORTS acknowledges each report with a reporting reference. A report that is rejected must be corrected and sent again
within the reporting deadline.
