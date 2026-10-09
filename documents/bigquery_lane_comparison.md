# BigQuery lane comparison

Spider 2.0-Lite BigQuery split: 204 instances (`bq###` 179, `ga###` 25) across 69 databases, `Qwen/Qwen3.6-35B-A3B` on one H200, greedy (temperature 0), `--max-steps 60` except the baseline's 40.

## Lanes

| lane | configuration | correct | n | accuracy | 95% CI |
|---|---|---:|---:|---:|---:|
| `bq_v2` | baseline (40 steps, truncating schema dump, dead `find_value`) | 69 | 204 | **33.8%** | ±6.5 |
| `bq_v3` | + 5 harness fixes, 60 steps | 84 | 204 | **41.2%** | ±6.8 |
| `bq_v3s` | + catalog retrieval (`search_context`, k=16, additive) | 87 | 204 | **42.6%** | ±6.8 |
| `bq_v3r` | + gated output-shape rubric | 95 | 200 | **47.5%** | ±6.9 |

Differences of fewer than about 14 questions sit inside these intervals. Read the flip counts, not the net.

## Questions by pattern across the lanes

| group | n | share | meaning |
|---|---:|---:|---|
| **always solved** | 35 | 17% | right in every lane; carries no signal about any change |
| **never solved** | 76 | 37% | wrong in every lane; the residual difficulty and the ceiling |
| **recovered** | 41 | 20% | wrong in `bq_v2`, right in `bq_v3r` — what the work bought |
| **regressed** | 13 | 6% | right in `bq_v2`, wrong in `bq_v3r` — the cost of the work |
| **unstable** | 39 | 19% | flips more than once; temperature-0 sampling variance |

111 of 204 questions (54%) have the same outcome in all four lanes. Every claim in this report rests on the 93 that move.

### Never solved in any lane (76)

Grouped by database, worst first. A database that never yields a correct answer across four configurations is a candidate for a schema-specific problem rather than a question-specific one.

| database | never solved | total in lane |
|---|---:|---:|
| `ga360` | 6 | 12 |
| `firebase` | 6 | 9 |
| `ga4` | 6 | 17 |
| `fda` | 4 | 5 |
| `ncaa_basketball` | 4 | 5 |
| `chicago` | 3 | 5 |
| `mitelman` | 3 | 3 |
| `fec` | 2 | 2 |
| `noaa_data` | 2 | 11 |
| `new_york` | 2 | 4 |
| `nhtsa_traffic_fatalities` | 2 | 4 |
| `CYMBAL_INVESTMENTS` | 2 | 2 |
| `gnomAD` | 2 | 3 |
| `cms_data` | 2 | 7 |
| `world_bank` | 2 | 6 |

## Per-question outcomes

`1` correct · `.` wrong · `-` not scored. `steps`/`GiB` are from the best lane that recorded them.

| instance | database | `bq_v2` | `bq_v3` | `bq_v3s` | `bq_v3r` | pattern | steps | GiB | detail (best lane) |
|---|---|:-:|:-:|:-:|:-:|---|---:|---:|---|
| `bq001` | ga360 | . | 1 | 1 | 1 | recovered | 12 | 0.0 | matches bq001_a.csv |
| `bq002` | ga360 | . | . | . | 1 | recovered | 51 | 0.1 | matches bq002_a.csv |
| `bq003` | ga360 | . | . | . | . | never solved | 11 | 0.0 | result_mismatch |
| `bq004` | ga360 | . | . | 1 | 1 | recovered | 16 | 0.2 | matches bq004_a.csv |
| `bq006` | austin | 1 | . | . | . | regressed | 6 | 0.0 | result_mismatch |
| `bq008` | ga360 | . | . | . | . | never solved | 17 | 0.1 | result_mismatch |
| `bq009` | ga360 | . | . | . | . | never solved | 9 | 0.0 | result_mismatch |
| `bq010` | ga360 | . | . | . | . | never solved | 21 | 0.3 | result_mismatch |
| `bq011` | ga4 | . | 1 | 1 | 1 | recovered | 7 | 1.8 | matches bq011_a.csv |
| `bq018` | covid19_open_data | 1 | . | 1 | 1 | unstable | 7 | 2.8 | matches bq018_a.csv |
| `bq019` | cms_data | 1 | 1 | 1 | 1 | always solved | 6 | 0.0 | matches bq019_d.csv |
| `bq021` | new_york | 1 | . | . | . | regressed | 9 | 33.0 | result_mismatch |
| `bq022` | chicago | . | . | . | . | never solved | 4 | 6.3 | result_mismatch |
| `bq023` | fec | . | . | . | . | never solved | 14 | 13.6 | result_mismatch |
| `bq024` | usfs_fia | . | . | . | . | never solved | 30 | 41.7 | result_mismatch |
| `bq025` | census_bureau_internationa | 1 | 1 | 1 | 1 | always solved | 13 | 0.6 | matches bq025_a.csv |
| `bq030` | covid19_open_data | 1 | 1 | 1 | 1 | always solved | 13 | 8.3 | matches bq030_c.csv |
| `bq031` | noaa_data | . | . | . | . | never solved | 19 | 2.6 | result_mismatch |
| `bq032` | noaa_data | 1 | 1 | . | 1 | unstable | 13 | 0.2 | matches bq032_a.csv |
| `bq034` | ghcn_d | . | . | . | . | never solved | 7 | 0.0 | result_mismatch |
| `bq035` | san_francisco | 1 | . | 1 | . | unstable | 9 | 0.1 | result_mismatch |
| `bq038` | new_york | . | . | . | . | never solved | 19 | 13.1 | result_mismatch |
| `bq039` | new_york_plus | . | 1 | 1 | 1 | recovered | 10 | 21.0 | matches bq039_e.csv |
| `bq040` | new_york_plus | . | 1 | 1 | 1 | recovered | 10 | 46.1 | matches bq040_a.csv |
| `bq041` | stackoverflow | 1 | 1 | . | . | regressed | 12 | 6.9 | result_mismatch |
| `bq042` | noaa_data | 1 | 1 | 1 | 1 | always solved | 9 | 3.3 | matches bq042_a.csv |
| `bq045` | noaa_data | . | 1 | . | 1 | unstable | 6 | 0.3 | matches bq045_a.csv |
| `bq046` | TCGA_bioclin_v0 | 1 | 1 | . | 1 | unstable | 9 | 0.7 | matches bq046_a.csv |
| `bq047` | new_york_noaa | . | 1 | . | 1 | unstable | 36 | 24.4 | matches bq047_a.csv |
| `bq048` | new_york_noaa | 1 | 1 | 1 | . | regressed | 37 | 21.5 | result_mismatch |
| `bq049` | iowa_liquor_sales_plus | 1 | . | 1 | . | unstable | 26 | 13.7 | result_mismatch |
| `bq051` | new_york_ghcn | . | . | . | 1 | recovered | 41 | 30.3 | matches bq051.csv |
| `bq053` | new_york | . | 1 | . | . | unstable | 20 | 0.2 | result_mismatch |
| `bq054` | new_york | . | . | . | . | never solved | 39 | 0.7 | result_mismatch |
| `bq055` | google_dei | . | 1 | . | 1 | unstable | 18 | 0.0 | matches bq055_b.csv |
| `bq059` | san_francisco_plus | 1 | 1 | 1 | 1 | always solved | 12 | 0.8 | matches bq059_a.csv |
| `bq060` | census_bureau_internationa | . | . | 1 | 1 | recovered | 4 | 0.0 | matches bq060_a.csv |
| `bq061` | census_bureau_acs_1 | 1 | . | 1 | 1 | unstable | 7 | 0.0 | matches bq061_b.csv |
| `bq064` | census_bureau_acs_1 | . | . | . | . | never solved | 22 | 2.0 | result_mismatch |
| `bq066` | sdoh | . | 1 | . | 1 | unstable | 27 | 0.0 | matches bq066_a.csv |
| `bq067` | nhtsa_traffic_fatalities | . | . | . | . | never solved | 22 | 0.0 | result_mismatch |
| `bq074` | sdoh | . | 1 | 1 | 1 | recovered | 23 | 0.0 | matches bq074_b.csv |
| `bq075` | google_dei | . | . | 1 | 1 | recovered | 32 | 0.0 | matches bq075_a.csv |
| `bq076` | chicago | . | . | . | . | never solved | 4 | 0.3 | result_mismatch |
| `bq077` | chicago | 1 | 1 | 1 | 1 | always solved | 9 | 1.2 | matches bq077_a.csv |
| `bq079` | usfs_fia | 1 | . | 1 | . | unstable | 28 | 14.8 | result_mismatch |
| `bq081` | san_francisco_plus | 1 | 1 | . | . | regressed | 6 | 0.2 | result_mismatch |
| `bq085` | covid19_jhu_world_bank | . | . | . | . | never solved | 19 | 0.0 | result_mismatch |
| `bq086` | covid19_open_world_bank | 1 | . | 1 | 1 | unstable | 18 | 6.1 | matches bq086_e.csv |
| `bq087` | covid19_symptom_search | 1 | 1 | 1 | 1 | always solved | 12 | 0.3 | matches bq087_a.csv |
| `bq088` | covid19_symptom_search | 1 | 1 | 1 | 1 | always solved | 11 | 0.0 | matches bq088_d.csv |
| `bq089` | covid19_usa | . | . | . | . | never solved | 9 | 0.0 | result_mismatch |
| `bq090` | CYMBAL_INVESTMENTS | . | . | . | . | never solved | 18 | 0.4 | result_mismatch |
| `bq094` | fec | . | . | . | . | never solved | 24 | 0.1 | result_mismatch |
| `bq096` | gbif | . | . | . | . | never solved | 60 | 0.0 | no_sql |
| `bq097` | sdoh | . | 1 | 1 | 1 | recovered | 16 | 0.0 | matches bq097_a.csv |
| `bq098` | new_york_plus | . | 1 | . | 1 | unstable | 11 | 60.7 | matches bq098_a.csv |
| `bq102` | gnomAD | . | . | . | . | never solved | 50 | 2.3 | result_mismatch |
| `bq103` | gnomAD | . | . | . | . | never solved | 20 | 0.0 | result_mismatch |
| `bq105` | nhtsa_traffic_fatalities_p | . | 1 | . | . | unstable | 60 | 1.3 | result_mismatch |
| `bq108` | nhtsa_traffic_fatalities | 1 | 1 | 1 | 1 | always solved | 5 | 0.0 | matches bq108_a.csv |
| `bq110` | sdoh | . | 1 | 1 | 1 | recovered | 9 | 0.0 | matches bq110_a.csv |
| `bq111` | mitelman | . | . | . | . | never solved | 60 | 0.2 | result_mismatch |
| `bq112` | bls | . | . | . | . | never solved | 28 | 0.7 | result_mismatch |
| `bq113` | bls | 1 | . | 1 | . | unstable | 17 | 0.0 | result_mismatch |
| `bq114` | openaq | . | . | . | 1 | recovered | 34 | 11.6 | matches bq114_a.csv |
| `bq115` | census_bureau_internationa | 1 | . | 1 | . | unstable | 4 | 0.1 | result_mismatch |
| `bq116` | sec_quarterly_financials | . | 1 | . | 1 | unstable | 12 | 54.7 | matches bq116_a.csv |
| `bq119` | noaa_data | . | 1 | 1 | 1 | recovered | 20 | 0.4 | matches bq119_a.csv |
| `bq120` | sdoh | . | 1 | 1 | 1 | recovered | 19 | 0.0 | matches bq120_a.csv |
| `bq123` | stackoverflow | . | . | . | . | never solved | 7 | 2.6 | result_mismatch |
| `bq124` | fhir_synthea | 1 | 1 | 1 | 1 | always solved | 13 | 6.5 | matches bq124_a.csv |
| `bq126` | the_met | 1 | 1 | 1 | 1 | always solved | 10 | 0.1 | matches bq126_b.csv |
| `bq130` | covid19_nyt | . | . | . | . | never solved | 7 | 0.1 | result_mismatch |
| `bq137` | census_bureau_usa | . | . | . | . | never solved | 10 | 0.5 | result_mismatch |
| `bq143` | CPTAC_PDC | . | 1 | 1 | . | unstable | 57 | 70.5 | result_mismatch |
| `bq144` | ncaa_insights | 1 | 1 | 1 | 1 | always solved | 20 | 0.0 | matches bq144_a.csv |
| `bq151` | pancancer_atlas_2 | . | . | . | . | never solved | 30 | 1.0 | result_mismatch |
| `bq161` | pancancer_atlas_2 | 1 | 1 | 1 | 1 | always solved | 19 | 0.6 | matches bq161_a.csv |
| `bq162` | HTAN_1 | . | . | . | . | never solved | 38 | 0.5 | result_mismatch |
| `bq165` | mitelman | . | . | . | . | never solved | 31 | 0.3 | result_mismatch |
| `bq169` | mitelman | . | . | . | . | never solved | 60 | 0.3 | result_mismatch |
| `bq172` | cms_data | 1 | 1 | 1 | 1 | always solved | 5 | 1.5 | matches bq172_a.csv |
| `bq177` | cms_data | 1 | 1 | 1 | 1 | always solved | 8 | 0.1 | matches bq177_a.csv |
| `bq181` | noaa_data | . | . | . | . | never solved | 16 | 1.0 | result_mismatch |
| `bq185` | new_york_plus | . | 1 | 1 | 1 | recovered | 6 | 20.1 | matches bq185_b.csv |
| `bq186` | san_francisco | . | . | . | . | never solved | 8 | 0.1 | result_mismatch |
| `bq198` | ncaa_basketball | 1 | . | 1 | 1 | unstable | 10 | 0.0 | matches bq198_d.csv |
| `bq199` | iowa_liquor_sales | . | . | . | . | never solved | 7 | 5.0 | result_mismatch |
| `bq200` | mlb | . | . | . | 1 | recovered | 30 | 6.3 | matches bq200_a.csv |
| `bq202` | new_york_plus | . | . | . | . | never solved | 7 | 4.4 | result_mismatch |
| `bq203` | new_york_plus | . | . | 1 | . | unstable | 5 | 0.0 | result_mismatch |
| `bq204` | eclipse_megamovie | 1 | 1 | . | 1 | unstable | 9 | 0.0 | matches bq204_a.csv |
| `bq208` | new_york_noaa | 1 | 1 | . | 1 | unstable | 17 | 3.5 | matches bq208_a.csv |
| `bq218` | iowa_liquor_sales | 1 | . | . | . | regressed | 5 | 2.2 | result_mismatch |
| `bq220` | usfs_fia | . | 1 | 1 | 1 | recovered | 19 | 5.6 | matches bq220_a.csv |
| `bq227` | london | . | . | . | . | never solved | 8 | 2.2 | result_mismatch |
| `bq228` | london | 1 | 1 | 1 | 1 | always solved | 4 | 0.6 | matches bq228_a.csv |
| `bq229` | open_images | . | . | . | 1 | recovered | 13 | 21.6 | matches bq229_a.csv |
| `bq230` | usda_nass_agriculture | 1 | 1 | . | 1 | unstable | 12 | 9.7 | matches bq230_a.csv |
| `bq232` | london | 1 | 1 | 1 | 1 | always solved | 6 | 1.5 | matches bq232_a.csv |
| `bq234` | cms_data | . | . | . | . | never solved | 15 | 4.8 | result_mismatch |
| `bq235` | cms_data | . | 1 | 1 | 1 | recovered | 8 | 0.0 | matches bq235_a.csv |
| `bq268` | ga360 | . | . | 1 | 1 | recovered | 12 | 0.2 | matches bq268_b.csv |
| `bq269` | ga360 | . | 1 | 1 | 1 | recovered | 25 | 0.0 | matches bq269_a.csv |
| `bq270` | ga360 | . | 1 | 1 | 1 | recovered | 7 | 0.0 | matches bq270_a.csv |
| `bq275` | ga360 | . | . | . | . | never solved | 11 | 0.2 | result_mismatch |
| `bq277` | noaa_ports | . | . | . | . | never solved | 34 | 0.5 | result_mismatch |
| `bq278` | sunroof_solar | . | . | . | 1 | recovered | 10 | 0.0 | matches bq278_b.csv |
| `bq279` | austin | 1 | . | . | . | regressed | 48 | 1.4 | result_mismatch |
| `bq280` | stackoverflow | 1 | 1 | 1 | 1 | always solved | 5 | 2.0 | matches bq280_a.csv |
| `bq281` | austin | 1 | . | . | . | regressed | 8 | 0.5 | result_mismatch |
| `bq282` | austin | 1 | . | . | . | regressed | 6 | 0.0 | result_mismatch |
| `bq284` | bbc | 1 | 1 | 1 | 1 | always solved | 6 | 0.0 | matches bq284_a.csv |
| `bq285` | fda | . | . | . | . | never solved | 4 | 0.0 | result_mismatch |
| `bq286` | usa_names | . | . | 1 | . | unstable | 8 | 0.8 | result_mismatch |
| `bq287` | fda | . | . | . | . | never solved | 59 | 0.1 | result_mismatch |
| `bq288` | fda | . | 1 | 1 | 1 | recovered | 8 | 0.0 | matches bq288_a.csv |
| `bq290` | noaa_data | . | . | . | 1 | recovered | 6 | 0.5 | matches bq290_a.csv |
| `bq293` | new_york_geo | . | . | . | . | never solved | 22 | 48.5 | result_mismatch |
| `bq300` | stackoverflow | 1 | 1 | 1 | 1 | always solved | 11 | 5.7 | matches bq300_b.csv |
| `bq301` | stackoverflow | 1 | 1 | 1 | 1 | always solved | 11 | 16.0 | matches bq301_a.csv |
| `bq302` | stackoverflow | 1 | . | 1 | 1 | unstable | 6 | 2.9 | matches bq302_a.csv |
| `bq303` | stackoverflow | 1 | 1 | 1 | 1 | always solved | 13 | 18.5 | matches bq303_a.csv |
| `bq304` | stackoverflow | 1 | . | . | . | regressed | 8 | 107.6 | result_mismatch |
| `bq305` | stackoverflow | 1 | . | 1 | . | unstable | 14 | 6.6 | result_mismatch |
| `bq306` | stackoverflow | 1 | 1 | 1 | 1 | always solved | 21 | 35.2 | matches bq306_a.csv |
| `bq308` | stackoverflow | . | 1 | . | . | unstable | 11 | 5.6 | result_mismatch |
| `bq309` | stackoverflow | 1 | 1 | . | 1 | unstable | 18 | 108.7 | matches bq309_a.csv |
| `bq310` | stackoverflow | 1 | 1 | 1 | 1 | always solved | 9 | 8.3 | matches bq310_c.csv |
| `bq326` | world_bank | . | . | . | . | never solved | 11 | 0.9 | result_mismatch |
| `bq327` | world_bank | . | 1 | 1 | 1 | recovered | 6 | 0.3 | matches bq327_a.csv |
| `bq328` | world_bank | . | . | . | . | never solved | 7 | 0.7 | result_mismatch |
| `bq330` | fda | . | . | . | . | never solved | 12 | 8.0 | result_mismatch |
| `bq338` | census_bureau_acs_1 | 1 | 1 | 1 | 1 | always solved | 8 | 0.0 | matches bq338_a.csv |
| `bq339` | san_francisco_plus | . | . | . | . | never solved | 5 | 0.1 | result_mismatch |
| `bq352` | sdoh | . | 1 | 1 | 1 | recovered | 16 | 0.0 | matches bq352_a.csv |
| `bq354` | cms_data | . | . | . | . | never solved | 60 | 33.4 | result_mismatch |
| `bq355` | cms_data | . | 1 | 1 | 1 | recovered | 14 | 15.6 | matches bq355_a.csv |
| `bq356` | noaa_data | 1 | 1 | . | 1 | unstable | 26 | 1.6 | matches bq356_a.csv |
| `bq357` | noaa_data | 1 | . | . | . | regressed | 6 | 0.7 | result_mismatch |
| `bq360` | nppes | . | . | . | . | never solved | 15 | 2.1 | result_mismatch |
| `bq362` | chicago | . | . | . | 1 | recovered | 6 | 19.9 | matches bq362_b.csv |
| `bq363` | chicago | . | . | . | . | never solved | 7 | 12.7 | result_mismatch |
| `bq366` | the_met | . | . | . | 1 | recovered | 16 | 0.1 | matches bq366_d.csv |
| `bq374` | ga360 | . | . | . | . | never solved | 16 | 0.3 | result_mismatch |
| `bq376` | san_francisco_plus | . | . | . | . | never solved | 11 | 0.2 | result_mismatch |
| `bq383` | ghcn_d | 1 | 1 | 1 | 1 | always solved | 10 | 12.7 | matches bq383_a.csv |
| `bq389` | epa_historical_air_quality | . | 1 | 1 | . | unstable | 17 | 7.6 | result_mismatch |
| `bq391` | fhir_synthea | . | . | 1 | . | unstable | 21 | 10.9 | result_mismatch |
| `bq392` | noaa_gsod | 1 | 1 | 1 | 1 | always solved | 4 | 0.1 | matches bq392_a.csv |
| `bq393` | hacker_news | . | . | . | . | never solved | 18 | 10.6 | result_mismatch |
| `bq394` | noaa_data | . | 1 | 1 | 1 | recovered | 10 | 6.3 | matches bq394_b.csv |
| `bq395` | sdoh | . | 1 | 1 | . | unstable | 10 | 0.0 | result_mismatch |
| `bq396` | nhtsa_traffic_fatalities | 1 | . | . | 1 | unstable | 8 | 0.0 | matches bq396_c.csv |
| `bq397` | ecommerce | 1 | . | 1 | . | unstable | 17 | 0.1 | result_mismatch |
| `bq398` | world_bank | 1 | 1 | 1 | 1 | always solved | 9 | 0.9 | matches bq398_a.csv |
| `bq399` | world_bank | . | 1 | 1 | 1 | recovered | 8 | 1.1 | matches bq399_a.csv |
| `bq400` | san_francisco_plus | 1 | 1 | 1 | 1 | always solved | 15 | 0.2 | matches bq400_a.csv |
| `bq402` | ecommerce | . | 1 | 1 | . | unstable | 8 | 0.1 | result_mismatch |
| `bq403` | irs_990 | . | . | . | . | never solved | 10 | 0.2 | result_mismatch |
| `bq406` | google_dei | . | . | . | . | never solved | 21 | 0.0 | result_mismatch |
| `bq407` | covid19_usa | . | . | . | 1 | recovered | 15 | 1.3 | matches bq407_d.csv |
| `bq413` | dimensions_ai_covid19 | 1 | 1 | 1 | 1 | always solved | 9 | 0.3 | matches bq413_b.csv |
| `bq414` | the_met | . | 1 | 1 | . | unstable | 8 | 0.1 | result_mismatch |
| `bq418` | targetome_reactome | . | . | . | . | never solved | 41 | 0.2 | result_mismatch |
| `bq419` | noaa_data | 1 | 1 | 1 | . | regressed | 17 | 0.0 | result_mismatch |
| `bq424` | world_bank | . | . | 1 | 1 | recovered | 25 | 3.5 | matches bq424_d.csv |
| `bq425` | ebi_chembl | . | . | . | . | never solved | 60 | 0.9 | result_mismatch |
| `bq427` | ncaa_basketball | . | . | . | . | never solved | 22 | 3.2 | result_mismatch |
| `bq428` | ncaa_basketball | . | . | . | . | never solved | 15 | 0.7 | result_mismatch |
| `bq430` | ebi_chembl | . | . | . | . | never solved | 25 | 8.3 | result_mismatch |
| `bq432` | fda | . | . | . | . | never solved | 34 | 0.3 | result_mismatch |
| `bq441` | nhtsa_traffic_fatalities | . | . | . | . | never solved | 60 | 0.0 | result_mismatch |
| `bq442` | CYMBAL_INVESTMENTS | . | . | . | . | never solved | 6 | 0.2 | result_mismatch |
| `bq445` | gnomAD | . | . | . | 1 | recovered | 40 | 133.1 | matches bq445_a.csv |
| `bq457` | libraries_io | . | . | . | . | never solved | 25 | 16.6 | result_mismatch |
| `bq461` | ncaa_basketball | . | . | . | . | never solved | 30 | 5.6 | result_mismatch |
| `bq462` | ncaa_basketball | . | . | . | . | never solved | 15 | 0.0 | result_mismatch |
| `ga001` | ga4 | . | 1 | . | . | unstable | 5 | 0.2 | result_mismatch |
| `ga002` | ga4 | . | 1 | 1 | 1 | recovered | 19 | 1.9 | matches ga002_a.csv |
| `ga003` | firebase | 1 | 1 | 1 | 1 | always solved | 7 | 0.0 | matches ga003_a.csv |
| `ga004` | ga4 | 1 | 1 | 1 | . | regressed | 7 | 0.2 | result_mismatch |
| `ga005` | firebase | . | . | . | . | never solved | 20 | 3.4 | result_mismatch |
| `ga006` | ga4 | 1 | 1 | 1 | 1 | always solved | 8 | 1.0 | matches ga006_a.csv |
| `ga007` | ga4 | 1 | 1 | . | 1 | unstable | 25 | 0.1 | matches ga007_b.csv |
| `ga008` | ga4 | 1 | 1 | 1 | 1 | always solved | 6 | 0.1 | matches ga008_a.csv |
| `ga009` | ga4 | . | . | . | 1 | recovered | 14 | 3.7 | matches ga009_a.csv |
| `ga010` | ga4 | . | . | . | . | never solved | 13 | 0.7 | result_mismatch |
| `ga011` | ga4 | . | . | . | . | never solved | 17 | 2.9 | result_mismatch |
| `ga012` | ga4 | 1 | 1 | 1 | 1 | always solved | 9 | 0.0 | matches ga012_d.csv |
| `ga013` | ga4 | . | . | . | . | never solved | 26 | 0.1 | result_mismatch |
| `ga014` | ga4 | . | . | . | . | never solved | 27 | 4.2 | result_mismatch |
| `ga017` | ga4 | 1 | 1 | 1 | 1 | always solved | 5 | 0.7 | matches ga017_a.csv |
| `ga018` | ga4 | . | . | . | . | never solved | 60 | 0.2 | result_mismatch |
| `ga019` | firebase | . | . | 1 | 1 | recovered | 13 | 1.6 | matches ga019_d.csv |
| `ga020` | firebase | . | . | . | - | never solved | 14 | 0.8 | result_mismatch |
| `ga021` | firebase | . | . | . | - | never solved | 60 | 6.8 | result_mismatch |
| `ga022` | firebase | . | . | . | - | never solved | 21 | 1.0 | result_mismatch |
| `ga025` | firebase | . | . | 1 | - | recovered | 15 | 1.1 | matches ga025_b.csv |
| `ga028` | firebase | . | . | . | . | never solved | 12 | 1.7 | result_mismatch |
| `ga030` | firebase | . | . | . | . | never solved | 39 | 2.0 | result_mismatch |
| `ga031` | ga4 | . | . | . | . | never solved | 9 | 0.0 | result_mismatch |
| `ga032` | ga4 | . | . | 1 | 1 | recovered | 15 | 0.2 | matches ga032_b.csv |
