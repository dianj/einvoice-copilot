---
doc_id: KS-TS-01
title: KesNet invoice profile v3
country: KS
doc_type: technical_spec
version: "3"
published: 2024-05-15
valid_from: 2024-05-15
valid_to: null
announces: [2024-09-01]
supersedes: []
authority: 2
lang: en
---
# KesNet invoice profile v3

## 1. Profile scope
This profile defines the structured invoice exchanged over KesNet from 1 September 2024. It builds on the Core Invoice
Model (COM-02) in UBL 2.1 syntax and adds the Kestrian rules KS-01 to KS-06 below.

## 2. Participant identifiers
The seller and the buyer are identified by their KesNet endpoint IDs, stated in `cac:Party/cbc:EndpointID` with
`schemeID="KESNET"` for both parties (rule KS-02). The access points route the invoice by these identifiers.

## 3. Tax identification numbers
A Kestrian tax ID consists of the letters KS followed by eight digits, for example KS12345678; it has no check digit.
The seller's tax ID must be a Kestrian tax ID (rule KS-01).

## 4. Multi-currency invoices
An invoice may be issued in any currency of the Core Invoice Model. When the document currency is not KSK:
- `cbc:TaxCurrencyCode` must be KSK (rule KS-03), and
- a second `cac:TaxTotal` states the total VAT in KSK, with only `cbc:TaxAmount` and `currencyID="KSK"` (rule KS-04).

## 5. VAT categories and rates
VAT categories: S (standard rate), AA (reduced rate) and E (exempt, 0 %). The rate of each VAT subtotal must be the
rate valid on the tax point date according to the Kestrian VAT code list in force (rule KS-05). The tax point date is
`cbc:TaxPointDate` when the invoice states it, otherwise the issue date.

## 6. Public-sector buyers
An invoice to a public-sector buyer states the buyer reference in `cbc:BuyerReference` (rule KS-06).
