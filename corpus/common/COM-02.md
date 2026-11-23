---
doc_id: COM-02
title: Core Invoice Model (CIM) v1.0
country: COMMON
doc_type: technical_spec
version: "1.0"
published: 2023-10-02
valid_from: 2023-10-02
valid_to: null
announces: []
supersedes: []
authority: 2
lang: en
---
# Core Invoice Model (CIM) v1.0

## 1. Purpose and scope
The Core Invoice Model (CIM) is the common semantic model for electronic invoices exchanged in Valdoria, Kestria and
Orlavia. It defines the business terms every structured invoice must carry and the generic rules that apply in all
three countries, from 1 January 2024. National specifications add their own rules on top of the CIM; they may not
relax it. The CIM is expressed in OASIS UBL 2.1 syntax: every business term below is mapped to a UBL element.

## 2. Business terms
| Business term | UBL element |
|---|---|
| Invoice number | `cbc:ID` |
| Issue date | `cbc:IssueDate` |
| Invoice type code | `cbc:InvoiceTypeCode` |
| Document currency | `cbc:DocumentCurrencyCode` |
| Seller legal name and tax ID | `cac:AccountingSupplierParty/cac:Party` (`cac:PartyLegalEntity/cbc:RegistrationName`, `cac:PartyTaxScheme/cbc:CompanyID`) |
| Buyer legal name | `cac:AccountingCustomerParty/cac:Party/cac:PartyLegalEntity/cbc:RegistrationName` |
| Invoice lines | `cac:InvoiceLine` (quantity, price, net amount) |
| VAT breakdown | `cac:TaxTotal/cac:TaxSubtotal` (taxable amount, tax amount, category and rate) |
| Document totals | `cac:LegalMonetaryTotal` (line total, total without and with VAT, prepaid amount, amount due) |

## 3. Code lists
Invoice type codes: **380** (commercial invoice) and **381** (credit note). A national specification may add codes
for national use cases; for example, Orlavia adds **389** for self-billed invoices. National specifications may
extend a CIM code list but may never remove a code from it (rules CORE-03 and CORE-04).

Currency codes: a subset of the ISO 4217 codes (EUR, USD, GBP, CHF, SEK, NOK, DKK, PLN, CZK, HUF, RON, JPY) plus the
Kestrian krona, **KSK**, which is used only in Kestria.

## 4. Mandatory content
Every invoice must have an invoice number (CORE-01) and an issue date written as YYYY-MM-DD (CORE-02). The invoice type
code and the document currency must come from the code lists in section 3 (CORE-03, CORE-04). The legal names of the
seller and of the buyer must be stated (CORE-05), as must the seller's tax ID (CORE-06). An invoice has at least one
invoice line (CORE-07).

## 5. Arithmetic rules
All amounts are rounded to two decimals; differences of up to 0.01 are tolerated.
- The net amount of a line equals its quantity multiplied by its price (CORE-08).
- The sum of the line net amounts equals the document line total (CORE-09).
- For each VAT rate, the tax amount equals the taxable amount multiplied by the rate, and the VAT total equals the
  sum of the VAT subtotals (CORE-10).
- The amount due equals the total with VAT minus any prepaid amount, plus a rounding amount if stated (CORE-11).

## 6. Corrections
An issued invoice is never changed. Corrections are made with a credit note (type code 381) that references the
number of the original invoice in `cac:BillingReference/cac:InvoiceDocumentReference/cbc:ID` (CORE-12). National
specifications may require further references, such as a clearance identifier.

## 7. Relation to national rules
A national rule applies in addition to the CIM rules. Where a national specification and the CIM describe the same
element, the stricter requirement applies. Each national specification lists the dates from which its rules apply;
the CIM rules apply to all invoices issued from 1 January 2024.
