# Sample invoice sources

Ten specimen utility bills from 7 countries in 6 languages, covering electricity, gas and water. Each file is the original PDF exactly as downloaded (byte for byte; nothing trimmed or edited). All files were retrieved on 2026-10-01.

## Why these count as "real, not made up"

Each document is a specimen bill published by the utility itself (or by its government water agency) to show customers how to read their bill. Utilities use the same billing system and print layout for these specimens as for real bills, so the layout, field labels, tariff lines, units, tax treatment and legal footer all match a real production bill. Only the customer details are placeholders, such as "Max Mustermann", "John Q. Customer", "J Citizen", "Constantine the Octopus", masked IBANs and dummy account numbers. As a result we get real-world format variety without handling anyone's personal data. No leaked bills from private customers were used, and none of the files was created or edited by us.

## Files

Text-layer check: `python -c "import pypdf,sys; r=pypdf.PdfReader(sys.argv[1]); print(len(r.pages), [len((p.extract_text() or '').strip()) for p in r.pages])" FILE`. The numbers are extracted characters per page. For every file we also spot-checked that the vendor name, dates, usage figures and totals appear in the extracted text.

| File | Utility / vendor (as printed) | Country | Language | Utility type(s) | What the document is | Pages | Text layer (chars/page) | Source URL |
|---|---|---|---|---|---|---|---|---|
| `invoices/01_us_en_electricity-gas_sdge.pdf` | San Diego Gas & Electric (SDG&E) | US | en | electricity + gas (dual fuel) | Bill guide ("Understanding your SDG&E bill") made of specimen bill pages 1-2 of 4, dated Jun 8, 2016 | 2 | [3499, 6613] | https://www.sdge.com/sites/default/files/FINAL_S1660077_SDGE_UYB_TierUpdate_0.pdf |
| `invoices/02_us_en_gas_peoples-gas.pdf` | Peoples Gas (Chicago; WEC Energy Group print stream) | US | en | gas | Specimen bill page ("JOHN Q. CUSTOMER"), bill period 01/05/2026 to 02/02/2026 | 1 | [2931] | https://www.peoplesgasdelivery.com/payment-bill/pdf/sample-bill.pdf |
| `invoices/03_gb_en_electricity-gas_octopus-energy.pdf` | Octopus Energy (Octopus Energy Operations Limited) | GB | en | electricity + gas (dual fuel) | Annotated specimen statement with callouts, 2 June 2023 | 3 | [4554, 4017, 2364] | https://octoenergy-production-media.s3.amazonaws.com/documents/Annotated_Statement_rebranded.pdf |
| `invoices/04_gb_en_water_affinity-water.pdf` | Affinity Water Limited (bills on behalf of Thames Water for waste water) | GB | en | water + waste water | Specimen bill in the production layout ("Mr A B Sample"), 04 March 2020. Hosted by the Behavioural Insights Team, which worked with Affinity Water on the bill redesign | 6 | [822, 1041, 944, 2081, 3183, 2794] | https://www.bi.team/wp-content/uploads/2022/12/Old-Bill.pdf |
| `invoices/05_de_de_electricity-gas-water_mindener-stadtwerke.pdf` | Mindener Stadtwerke GmbH (water billed in the name of Mindener Wasser GmbH) | DE | de | electricity + gas + water | Musterrechnung: annual statement (Jahresrechnung 2022, dated 20. Januar 2023). 8 bill pages plus 3 pages of glossary and notices | 11 | [1944, 1335, 2436, 1332, 2504, 810, 3162, 404, 3655, 3086, 1197] | https://www.mindener-stadtwerke.de/wp-content/uploads/2024/11/musterrechnung.pdf |
| `invoices/06_fr_fr_electricity_edf-entreprises.pdf` | EDF (EDF SA / EDF Entreprises, "Garanti Pro" offer) | FR | fr | electricity | Bill guide ("Comprendre votre nouvelle facture") with the full business bill embedded and numbered explanations; invoice dated 27/02/2017 | 3 | [2950, 3925, 3269] | https://www.edf.fr/sites/default/files/contrib/entreprise/Contrats-et-factures/votre-facture/comprendre-sa-facture/v19/desc_dmep_om_inf36_garanti_pro_prix_integres.pdf |
| `invoices/07_it_it_electricity_enel-energia.pdf` | Enel Energia S.p.A. | IT | it | electricity | "Bolletta Luce - Fac simile": full specimen residential bill (ARERA 2025 format), invoice dated 09/09/2024 | 5 | [2770, 3359, 2228, 7813, 8905] | https://www.enel.it/content/dam/asset/documenti/blog/guide/come-leggere-bolletta-luce/bolletta-luce-b2c-2025.pdf |
| `invoices/08_br_pt_electricity_enel-ceara.pdf` | Companhia Energética do Ceará (Enel Ceará). **Trap:** the text layer also holds a hidden, older Enel Distribuição Goiás bill under white boxes | BR | pt | electricity (high-voltage Group A) | Bill guide ("Entenda a sua conta", large customers) with an embedded full bill, issued 09/08/2018. The visible bill and the text layer disagree (see Gaps) | 9 | [19, 344, 7267, 7218, 7333, 7662, 7341, 7360, 130] | https://www.enel.com.br/content/dam/enel-br/one-hub-brasil---2018/imagens/Entenda_sua_conta_ce_grandesclientes.pdf |
| `invoices/09_be_nl_electricity-gas_eneco.pdf` | Eneco Belgium nv | BE | nl | electricity + gas (dual fuel) | Bill guide ("Jouw jaarafrekening") with an embedded SPECIMEN annual statement summary page dated 28/08/2018; page 2 is an FAQ | 2 | [3797, 2570] | https://cdn.eneco.be/downloads/nl/b2c/ret/facturen/jaarafrekening.pdf |
| `invoices/10_au_en_water_state-water-nsw.pdf` | State Water Corporation, billing agent for the NSW Office of Water | AU | en | water (licence water management charges) | Bill guide ("How to read your water bill") with an embedded specimen TAX INVOICE ("This is a sample bill - do not pay"), dated 29/10/2014 | 2 | [31460, 18093] | https://publications.water.nsw.gov.au/watergroupjspui/bitstream/100/1477/1/Fees_Unreg_How_To_Read_Your_Water_Bill.pdf |

All files were retrieved on 2026-10-01. Total size is about 5.8 MB, and the largest file is 1.6 MB.

## Coverage

- **Utility types:** electricity (01, 03, 05-09), gas (01, 02, 03, 05, 09), water (04, 05, 10). The dual-fuel or multi-service bills are 01, 03, 05 (three services on one invoice) and 09.
- **Languages (6):** English, German, French, Italian, Portuguese, Dutch.
- **Units:** kWh, therms, CCF (converted to therms), m3 of gas converted to kWh (03, 05), m3 and litres of water (04, 05), megalitres (10), kW demand and kvarh/UFER reactive energy (08), kW contracted power (07).
- **Layouts:** a US one-page summary bill (02), US multi-section dual-fuel bills (01), a UK annotated statement (03), a German multi-page annual statement (05), an Italian ARERA "bolletta sintetica" (07), a Brazilian Group A fiscal invoice with a payment slip (08), a summary-only annual statement (09) and an Australian tax invoice (10).

## Gaps

- **File 08 has two bills in one PDF.** The visible bill is Enel Ceará (issued 09/08/2018, 151,229 kWh). Hidden under white rectangles, the text layer also contains an older Enel Goiás bill (issued 07/07/2018). A text-only pipeline cannot tell which one a person sees; ground truth follows the visible bill.

- No Spanish bill. Candidates from the CNMC, Endesa, Canal de Isabel II, EMASESA, CFE (Mexico), EPM (Colombia) and Aguas Andinas were all image-only, blocked, or not bills.
- No bill in a non-Latin script. Japanese (TEPCO, Kyushu, Chugoku, Osaka water), Hong Kong (CLP) and Singapore (SP Group) specimens were image-only or blocked.
