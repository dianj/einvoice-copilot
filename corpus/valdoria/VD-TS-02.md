---
doc_id: VD-TS-02
title: VCP technical specification v2.1
country: VD
doc_type: technical_spec
version: "2.1"
published: 2025-11-15
valid_from: 2025-11-15
valid_to: null
announces: [2026-01-01]
supersedes: [VD-TS-01]
authority: 2
lang: en
---
# VCP technical specification v2.1

## 1. Scope and changes from version 1.4
This specification replaces version 1.4. It covers business-to-government invoices and, from 1 January 2026, the
business-to-business invoices of large taxpayers. Changes: the Clearance ID becomes mandatory on cleared invoices
(new rule VD-09), credit notes must reference the original Clearance ID (VD-05), the buyer's tax ID is checked on
business-to-business invoices (VD-02) and a scope check is added for the transition period (VD-06).

## 2. Submission and stages
An invoice is validated twice: by the supplier's software before submission (**pre-clearance**) and by VCP. After VCP
returns the Clearance ID, the supplier adds it to the invoice (**cleared** invoice) and sends that invoice to the buyer.
Rules that concern the Clearance ID apply to cleared invoices only.

## 3. Invoice numbering
An invoice number consists of a series prefix of two to four capital letters, the year of the issue date and a
six-digit sequence number, separated by hyphens, for example INV-2026-000123 (rule VD-03). Numbers within a series and
year must be consecutive and without gaps.

## 4. Tax identification numbers
A Valdorian tax ID consists of the letters VD followed by nine digits; the ninth digit is a check digit. The check
digit is computed with modulus 11: the first eight digits are multiplied by the weights 9, 8, 7, 6, 5, 4, 3 and 2; the
products are added; the check digit is 11 minus the remainder of that sum divided by 11. A result of 11 gives the check
digit 0; a result of 10 means the number is not a valid tax ID. Example: VD123456789 is valid.
The seller's tax ID is checked on every invoice (rule VD-01); on business-to-business invoices the buyer's tax ID is
checked in the same way (rule VD-02).

## 5. VAT exemptions
A VAT breakdown at a rate of 0 % must state the exemption reason in `cbc:TaxExemptionReason` (rule VD-04).

## 6. Clearance ID
VCP returns a Clearance ID in the format VCP-YYYY-NNNNNNNN (the year of clearance and an eight-digit number). Rule VD-09:
every cleared invoice issued from 1 January 2026 states its Clearance ID in
`cac:AdditionalDocumentReference/cbc:ID` with the attribute `schemeID="VCP"`. An invoice without a valid Clearance ID
is not a legally issued invoice.

## 7. Credit notes
A credit note (type code 381) corrects a cleared invoice. In addition to the reference required by the Core Invoice
Model, it states the Clearance ID of the original invoice in
`cac:BillingReference/cac:AdditionalDocumentReference/cbc:ID` with `schemeID="VCP"` (rule VD-05). The credit note is
cleared like an invoice.

## 8. Scope check during the transition
From 1 January 2026 until the date on which clearance becomes mandatory for all business-to-business invoices, only
large taxpayers (turnover above EUR 10 million in the previous calendar year) must clear business-to-business
invoices. The invoice itself does not show the supplier's turnover, so software must know the taxpayer size; when it
is unknown, rule VD-06 reports a warning.
