# deep07 audit notes (Nov 19 2026)

Batch: bq111, bq165, bq169, bq024, bq079, bq220, bq090, bq442, bq112, bq113, bq018, bq030. Lane n = trace folder
lane_k(n+1). Pre-rewrite golds were read from the Spider2 submodule history (parent of commit 5fa8a517, and earlier
commits where a file changed more than once). Only the traces were used; no lane result beyond what the agent saw was
available, so claims about unseen rows are marked as inferences.

Verdicts: gold_right 7 (bq111, bq024, bq079, bq442, bq113, bq018, bq030), two_readings 3 (bq165, bq220, bq090),
scoring_defect 2 (bq169, bq112), gold_wrong 0, unclear 0.

Label changes: bq169 [] -> strict [0,1,2,3] / lenient [0,1,2,3]; bq112 [] -> [2,3] / [2,3];
bq220 [0,2] -> [0,2] / [0,2,3]; bq090 [] -> [] / [1].

## bq111

The question asks for per-chromosome Pearson correlations, with p-values, between Mitelman frequencies (Morph 3111,
Topo 0401) and TCGA frequencies "for each aberration type". No lane touches TCGA data. Every lane tried
(isb-cgc.tcga_harmonized, isb-cgc-bq.functions and others) and the harness refused each query as "not part of the
'mitelman' database". Spider2's BigQuery schema for this database lists only mitelman-db.prod; only the Snowflake twin
TCGA_MITELMAN has TCGA tables. So in this setup the question cannot be answered. What the lanes returned instead:
lane 0 correlates two Mitelman tables, lane 1 returned a table list, lane 2 correlates Mitelman gains with Mitelman
losses, and lane 3 lists Mitelman frequencies. All four are wrong under any reading, so the official "none right"
stands. The files are a mixed set. File a is the pre-rewrite gold unchanged: 21 chromosomes with amp, gain, loss and
del, as in the ISB-CGC notebook. Files b-e have gain and loss only and give four different values for the same cells
(chr1 gain r = 0.333, 0.792, 0.802, 0.696). They cannot be checked without warehouse data, and they affect no lane.
Verdict `gold_right`, medium.

## bq165

The original gold (Dec 2024) followed the ISB-CGC notebook on the cohort Morph 3111 AND Topo 0401: 783 samples, with
columns sCount, total_gain, total_loss, total_amp, total_del and the four frequencies. Both current files carry the
same counts on a different cohort. Every one of their 1,280 rounded frequencies fits a single denominator of 3,377,
and lane 0 counted 3,375 samples for Morph 3111 OR Topo 0401 (q29). The files cannot come from the AND cohort. They
report 616 samples losing chrY (18.24%) and 112 gaining it. Today's AND cohort has 7 cases with a chrY loss and no chrY
gain at all (bq111 lane 3, same database), and the old AND-based gold had 8 chrY losses among 783 samples. So the
rewrite moved to a union cohort, or at least to one not limited to breast tumours. "A cohort of breast cancer
(morphology='3111') and adenocarcinoma (topology='0401') samples" can literally mean breast-cancer samples plus
adenocarcinoma samples, especially since the question attaches one label to each code. But the source notebook
(bq111's document, with the same codes and the same swapped labels) defines a single breast-cancer cohort by both
codes. I treat this as two fair readings. It changes nothing: lanes 1 and 3 used AND and lane 0 used OR, yet all of
them hard-code or misclassify amplifications and deletions, and lane 2 returned a chromosome list. Verdict
`two_readings`, medium, labels unchanged.

## bq169

The lanes' logic matches the gold, and their only extra rows come from newer data. Files a-c list 119 clones, one row
each, picking an arbitrary segment when a clone has several (file c always takes the lowest start). File d lists all
139 segment combinations, and it equals the May-2025 file a. The lanes return 124 clones (lanes 1 and 3) or 144
combinations (lanes 0 and 2), five more at either grain. All 50 visible rows of lanes 0 and 2 are rows of file d,
karyotype strings included. Of the 76 clones visible in any lane's triple-match queries, 74 are in the gold. The other
two, 18577/182/1/2 and 18748/319/1/1, have RefNos above the gold's maximum of 17942. The May-2025 file b already
contained three newer-reference rows (18540/2/1 twice and 18577/182/1) on top of file a's 139, and the November
rewrite deleted it. The logic cannot explain the gap either. No segment boundary falls inside the three query regions,
and strict and inclusive overlap both give 124 clones, so "between positions" selects the same clones under any
convention. Without the new clones, lanes 0 and 2 equal file d and lanes 1 and 3 match file b, which scores only
RefNo, CaseNo and karyotype. Verdict `scoring_defect` (stale snapshot), medium because 3 of the 5 extra clones are
not visible; all four lanes are right.

## bq024

The four files hold two readings, and one of them is broken. Files a-c rank the 2012 evaluation groups by their single
largest condition (Wyoming 562012: 43,963.77 acres), but tied rows carry arbitrary evaluation types: EXPMORT in a,
EXPVOL in b, EXPCURR in c. File a also differs from b and c in four groups (NC, LA, NM, WV) and labels group 352012
"NEW MEXICO 2013". File d sums EXPCURR acres per status and gives more forest than the land area of several states:
Georgia 45.6M acres against about 37M acres of land, Alabama 42.9M against about 32M. So file d double counts. The
original gold took a third reading: single conditions on plots measured in 2012, which returned evaluation groups from
2014-2016. All lanes keep only plots measured in 2012 and sum acres per (group, type, status). Each group's "largest
condition" is therefore a partial total over the plots it happened to measure in 2012, for example 26.27M for Wyoming
2012 and 18.2M for Kansas 2014. That is not an area estimate under any reading, and lanes 0-2 also disagree with
lane 3, which used EXPCURR only. No lane is right, and none is accepted through file d. Verdict `gold_right`, medium,
with file d noted as wrong but harmless. The scorer never checks subplot acres, the ranking metric.

## bq079

All five files name Oregon (41, 412019) for timberland and California (6, 62019) for forestland. Lanes 0 and 2 apply
the question's formula: expansion factor times condition proportion times the MACR or SUBP adjustment factor when it
is above zero, using the latest EXPCURR group per state. They get 23,896,747.86 and 31,994,047.82 acres, equal to
file e within 0.01. Lanes 1 and 3 drop the condition proportion and fall back to a factor of 1, so each plot's full
area is counted once per condition (California 41.9M), and Georgia comes out first for timberland. Files a-d score
only state code, evaluation group and state name; their acreages are lower than file e's and are not reproduced in
any trace, but no lane depends on them. Verdict `gold_right`, high.

## bq220

All five current files agree: macroplot California 4,937.30 / 5,128.20 / 5,043.94, and subplot Wyoming 7,634.42,
Alaska 15,679.88, Wyoming 6,284.79 for 2015-2017. Lanes 0 and 2 get exactly these from condition x population with the
document's E x P x A formulas, without plot_tree. Lane 3 also joins plot_tree, which the question names ("Based on the
condition, plot_tree, and population tables"). The join repeats each condition once per tree on its plot and gives
subplot Wyoming 8,074.77 / 7,657.05 / 6,674.92 and macroplot California 5,142.66 / 5,441.47 / 5,228.31. Those are,
to six decimals, the original gold (Dec 2024 to Nov 2025). Lane 3's subplot values use the same proportion column as
lanes 0 and 2, so the difference there comes from the join, not from the formula. The unweighted average is the
sounder statistic, but following the question's table list, as the benchmark's own annotators did, is a fair reading.
Lane 1 restricts to plots with trees and averages per-plot means, matching neither (it puts Wyoming, not Alaska,
first in 2016). Verdict `two_readings`, medium: strict [0,2], lenient [0,2,3].

## bq090

The files changed the definition of intrinsic value. Lane 3's trace reproduces file a exactly: the average of
max(0, LastPx - StrikePrice) over long trades is 1.0123 for feeling-lucky and 1.2887 for momentum, a difference of
-0.2764. File b holds +0.2764. The gold SQL averages StrikePrice - LastPx instead and returns
0.0064617 - (-0.0166077) = 0.0230694, which was the gold until Nov 2025 and is exactly lane 1's "difference" column.
The schema says StrikePrice is the "Price at which the CFD closed" and LastPx the "Price at which the CFD was entered".
bq442's document for the same table also treats LastPx as the open price and StrikePrice as the close price. Under
those meanings the new formula measures a long trade's loss. Still, "intrinsic value" is an option term, and its
textbook form max(0, S - K) maps naturally onto columns named LastPx and StrikePrice, so I accept both readings.
Lanes 0, 2 and 3 average LastPx - StrikePrice without the floor (-0.0231): the opposite sign of the gold SQL, and not
an intrinsic value under the option reading either. Verdict `two_readings`, medium: strict [], lenient [1].

## bq442

Both files and the original gold list the same six BTCZ0 trades with tradeID = OrderID, as in the gold SQL (OrderID
AS tradeID). The lanes return the same six trades with identical algorithm, symbol, prices, direction and multiplier,
but they took tradeID from TradeReportID ("ID of this trade report"), which is the order ID with "-0" appended. The
document defines tradeID as "the unique identifier for each order in the dataset", and OrderID is the column described
as "Order identifier". tradeID is scored, so the lanes fail on a field the document assigns to a different column.
This is a real, if small, deviation from the document, not formatting. Verdict `gold_right`, high.

## bq112

Files a (True, 76.3, 57.07) and b (76.30, 57.07, Yes) agree with the gold SQL. The pre-rewrite gold held only the two
rates (76.3, 57.07). Lanes 2 and 3 compute exactly these from Allegheny County (geoid 42003) QCEW wages and the
Pittsburgh all-items CPI series. Both submissions state in words that wages "kept pace with (and exceeded) inflation".
Their table lacks only the yes/no column, which follows directly from 76.30 > 57.07. With condition_cols [], the
rewrite's new True/Yes column became mandatory, so answers identical to the gold SQL's output now fail. I count this
as a scoring defect, though one could argue an explicitly requested yes/no must appear in the table. Lane 0 used
Luzerne County (geoid 42079, 60.93%), and lane 1 used the national seasonally adjusted December CPI (50.69%), so both
stay wrong. Verdict `scoring_defect`, medium: lanes 2 and 3 right.

## bq113

All three files give Utah County with 135.92% (average third-month construction employment 10,466.25 in 2000 and
24,692.25 in 2018). Lanes 0-2 return Utah, 135.92 and match file c, which scores only the percentage. Lane 3 computes
the same numbers but returns the top five counties for a question that asks which county. As in deep06's bq328, a
ranking is a different answer from the single county asked for, so its 5-row vectors cannot match. Verdict
`gold_right`, high.

## bq018

03-09 has the largest day-over-day growth in cumulative US confirmed cases (806 to 1,190, +47.64%, file c's 0.4764).
That is the gold SQL's computation and also the original gold. Lane 3 ranks new_confirmed over the previous day's
cumulative count and gets 03-09. Lanes 0 and 1 rank the day-over-day change in daily new cases ((34 - 18) / 18 on
03-02). That measures growth in the daily increment, not growth in the confirmed case count. Lane 2 does the same
without restricting to 2020 and returns a 2022 date. Verdict `gold_right`, high.

## bq030

On 2020-05-10 only four countries with more than 50,000 cases report national recovered counts. France shows
1,531,017 recovered against 138,872 confirmed (1,102%), which is a data error; the others are China 94.17%,
Italy 48.01% and Brazil 39.92%. Lanes 0, 2 and 3 drop the impossible rate and return China, Italy and Brazil, equal to
file c. Lane 1 sums province-level rows, which cover only part of some countries (China 71,816 of 84,435 cases), and
its Germany 94.87 / China 93.47 / Italy 48.01 matches no file. File a, the original gold from an older snapshot,
accepts France at 2,112%, and file b cannot be reproduced from the traces. No lane matches either, so both are
harmless here. Verdict `gold_right`, high.
