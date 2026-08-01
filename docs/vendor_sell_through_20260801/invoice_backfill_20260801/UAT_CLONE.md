# Production-shaped TEST clone UAT — invoice commercial backfill

**Clone DB:** `pet_spot_elsahel_vst_uat` (restored from Production dump, vector/AI tables skipped)  
**Module:** `petspot_vendor_sell_through` **19.0.1.4.3**  
**Unit tests:** `0 failed, 0 error(s) of 72` (`test_suite_v143.log`)

## Approved quantity match (exact bill product IDs)

| Product ID | Code / name | Approved | Invoice-only allocated | Stock | Match |
|-----------:|-------------|---------|------------------------:|------:|:-----:|
| 34 | APOQ-16 | 60 | 60 | 0 | yes |
| 23 | VAC-VP8 | 3 | 3 | 0 | yes |
| 69 | SHP-82-82 | 3 | 3 | 0 | yes |
| 67 | tenizol | 3 | 3 | 0 | yes |
| 75 | Evatri | 2 | 2 | 0 | yes |
| 133 | flomarbidine | 2 | 2 | 0 | yes |
| 66 | aquadent | 1 | 1 | 0 | yes |
| 73 | Nobivac Rabies | 1 | 1 | 0 | yes |
| 74 | Nobivac DHPPi | 1 | 1 | 0 | yes |
| 77 | Prednicortex | 1 | 1 | 0 | yes |
| 90 | Pyoderm | 1 | 1 | 0 | yes |
| 91 | Cortavance | 1 | 1 | 0 | yes |
| 102 | MULTIBOOST | 1 | 1 | 0 | yes |
| 116 | salmon max | 1 | 1 | 0 | yes |
| 119 | vetoplex | 1 | 1 | 0 | yes |
| 128 | aurizon | 1 | 1 | 0 | yes |
| 36 | SIMT-2.5-5 | 0 | 0 | — | excluded |
| 39 | SIMT-20-40 | 0 | 0 | — | excluded |
| 42 | REVC-45 | 0 | 0 | — | excluded |

## APOQ-16 UoM proof

- Base UoM: Tablet  
- Bill UoM: Box (100 Tablets)  
- 1 bill unit = **100** tablets (configured relative UoM)  
- 60 tablets = **0.6** bill units  
- Billed qty on BILL/2026/07/0002: 3 boxes  

Evidence: `08b_apoq_uom.json`

## Rebuild ×3

Identical: eligible_sum **15889.2**, invoice_qty **83.0**, sources **27**, duplicates **0**  
Evidence: `08b_rebuild_x3.json`, `08b_source_keys.json`

## Payment wizard preview (not posted)

| Bill | Cap / eligible | Residual |
|------|---------------:|---------:|
| BILL/2026/08/0002 | 1205.00 | 13016.00 |
| BILL/2026/08/0001 | 9844.00 | 192790.25 |
| BILL/2026/07/0002 | 3631.20 | 72371.10 |
| BILL/2026/07/0001 | 1209.00 | 19975.00 |

No supplier payment posted on the clone.

## Safety

- Production dump taken before clone: `pet_spot_elsahel_pre_vst_backfill_20260801-222406.dump`  
- No product merges  
- No inventory adjustments counted as sales  
- WH/OUT/00001 supplier return excluded (stock allocator only)  
- Corrective invoice/refund closed loops excluded (APOQ INV/00068 ↔ RINV/00002)
