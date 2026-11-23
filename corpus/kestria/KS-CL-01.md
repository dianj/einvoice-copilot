---
doc_id: KS-CL-01
title: Kestria VAT rates and category codes v2026
country: KS
doc_type: code_list
version: "2026"
published: 2026-01-15
valid_from: 2026-01-15
valid_to: null
announces: [2026-03-01]
supersedes: [KS-CL-00]
authority: 2
lang: en
---
# Kestria VAT rates and category codes v2026

## 1. Rates
| Category | Meaning | Rate |
|---|---|---|
| S | Standard rate | 25 % |
| AA | Reduced rate (food, books, passenger transport) | 12 % for supplies up to and including 28 February 2026; 10 % for supplies from 1 March 2026 |
| E | Exempt (financial services, health care) | 0 % |

## 2. Which rate applies
The reduced rate is lowered from 12 % to 10 %. The rate is determined by the tax point date of the supply: the
`cbc:TaxPointDate` of the invoice when stated, otherwise its issue date (rule KS-05). An invoice issued on 2 March 2026
for a supply made on 27 February 2026 therefore uses 12 % if it states that tax point date.

## 3. Transition notes
Software vendors should update their rate tables before 1 March 2026. Credit notes use the rate of the invoice they
correct.
