# Evaluation report

**Field accuracy: 116/120 (96.7%)** across 10 invoices.

- Wrong values that the `needs_review` flag caught: 1/4
- Rows flagged for review that really had an error: 1/3
- Extra service rows not in the labels: none

## Per field

| field | correct | accuracy |
|---|---|---|
| vendor_name | 15/15 | 100% |
| invoice_date | 14/15 | 93% |
| service_address | 15/15 | 100% |
| utility_type | 15/15 | 100% |
| usage_amount | 14/15 | 93% |
| usage_unit | 15/15 | 100% |
| billing_period_start | 14/15 | 93% |
| billing_period_end | 14/15 | 93% |

## Per invoice

| invoice | language | fields correct |
|---|---|---|
| 01_us_en_electricity-gas_sdge.pdf | en | 16/16 |
| 02_us_en_gas_peoples-gas.pdf | en | 8/8 |
| 03_gb_en_electricity-gas_octopus-energy.pdf | en | 16/16 |
| 04_gb_en_water_affinity-water.pdf | en | 8/8 |
| 05_de_de_electricity-gas-water_mindener-stadtwerke.pdf | de | 24/24 |
| 06_fr_fr_electricity_edf-entreprises.pdf | fr | 8/8 |
| 07_it_it_electricity_enel-energia.pdf | it | 8/8 |
| 08_br_pt_electricity_enel-ceara.pdf | pt | 5/8 |
| 09_be_nl_electricity-gas_eneco.pdf | nl | 16/16 |
| 10_au_en_water_state-water-nsw.pdf | en | 7/8 |

## Misses

| invoice | utility | field | expected | got | flagged for review |
|---|---|---|---|---|---|
| 08_br_pt_electricity_enel-ceara.pdf | electricity | invoice_date | 2018-08-09 | 2018-07-07 | NO |
| 08_br_pt_electricity_enel-ceara.pdf | electricity | billing_period_start | 2018-07-05 | 2018-06-04 | NO |
| 08_br_pt_electricity_enel-ceara.pdf | electricity | billing_period_end | 2018-08-06 | 2018-07-04 | NO |
| 10_au_en_water_state-water-nsw.pdf | water | usage_amount | 100 | 250.0 | yes |
