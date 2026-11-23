---
doc_id: VD-TS-01
title: VCP technical specification v1.4
country: VD
doc_type: technical_spec
version: "1.4"
published: 2024-09-01
valid_from: 2024-09-01
valid_to: 2025-11-14
announces: [2025-01-01]
supersedes: []
authority: 2
lang: en
---
# VCP technical specification v1.4

## 1. Scope
This specification describes how suppliers submit business-to-government invoices to the Valdoria Clearance Platform
(VCP) from 1 January 2025. Invoices follow the Core Invoice Model (COM-02) in UBL 2.1 syntax, with the Valdorian rules
below.

## 2. Submission
Invoices are submitted to the VCP interface as UBL 2.1 XML documents, one invoice per request, over a mutually
authenticated connection. VCP answers with either a Clearance ID or a list of rule violations.

## 3. Invoice numbering
Each supplier uses one or more numbering series. An invoice number consists of a series prefix of two to four capital
letters, the year of issue and a six-digit sequence number, separated by hyphens, for example INV-2025-000042
(rule VD-03). Numbers within a series and year must be consecutive.

## 4. Tax identification numbers
A Valdorian tax ID consists of the letters VD followed by nine digits; the ninth digit is a check digit (rule VD-01).
The check digit is computed with modulus 11: the first eight digits are multiplied by the weights 9, 8, 7, 6, 5, 4,
3 and 2; the products are added; the check digit is 11 minus the remainder of that sum divided by 11. A result of 11
gives the check digit 0; a result of 10 means the number is not a valid tax ID.

## 5. VAT exemptions
A VAT breakdown at a rate of 0 % must state the exemption reason (rule VD-04).

## 6. Clearance response
VCP returns a Clearance ID in the format VCP-YYYY-NNNNNNNN. In version 1.4 of this specification, stating the
Clearance ID on the invoice sent to the buyer is recommended.
