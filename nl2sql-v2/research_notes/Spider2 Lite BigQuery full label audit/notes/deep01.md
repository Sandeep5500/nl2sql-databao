# deep01 audit notes (Nov 19 2026)

Batch: ga002, ga004, ga006, ga007, ga009, ga013, ga014, ga018, ga031, ga032, bq286, bq230.
Lane n = trace folder lane_k(n+1); "k2 q8" means query q8 in the lane_k2 trace. Pre-rewrite golds were read from
the Spider2 submodule history (parent of commit 5fa8a517). The scorer copy used here maps NULL to 0.

Verdicts: gold_right 7 (ga002, ga006, ga007, ga013, ga018, ga032, bq286), gold_wrong 2 (ga014, ga031),
scoring_defect 1 (ga004), two_readings 1 (bq230), unclear 1 (ga009).
Label changes: ga004 [0] -> [0, 1, 2, 3] / [0, 1, 2, 3]; ga031 [] -> [0, 1, 2] / [0, 1, 2]; bq230 [0, 1] -> [0, 1] / [0, 1, 2, 3].

## ga002

The question asks, for each month from Nov 2020 to Jan 2021, which other product the Red Speckled Tee buyers bought
most. Both files, the pre-rewrite gold and the gold SQL all take the month's buyers and their other purchases that
month: Google Decal 17, Google Navy Speckled Tee 10, Google PNW Campus Sticker 12. Lanes 1-3 do the same and match.
The runners-up are 14, 8 and 7 (k2 q8), so ties are not an issue. Lane 0 matches purchases by transaction_id
instead, and its list of Red Tee transactions includes '(not set)', the transaction ID that every purchase from
Nov 1-11 carries (26-64 purchase events a day, k1 q4). Its November winner (Google Unisex Eco Tee Black, 59) comes
from those unrelated purchases, and December reads 9 instead of 10. Lane 0 is wrong under either reading. One caveat:
purchase events are often logged twice (transaction 355017 lists every item twice, including 8 decals, k1 q3), so
quantities include duplicates. No lane removed duplicates and the question does not ask for it, so no label
depends on this.

Labels unchanged: [1, 2, 3].

## ga004

The question asks for "the average difference in pageviews between users who bought something and those who
didn't", which is one number. Lanes 1-3 return exactly that, 45.37456967714961. File a's DIFFERENCE column is
45.37457, but condition_cols is empty, so the two group averages (49.093165 and 3.718595) are also required, and a
one-column answer fails. The gold SQL itself returns only the difference, and the pre-rewrite gold was the single
value 45.37456968, which lanes 1-3 would have passed. So the rewrite added required columns the question never asks
for. Lane 0 returns all three values and passes. File b can never match an exact answer: its 3.73 is 0.011 away from
3.718595, and its own 49.09 - 3.73 is 45.36, not 45.37.

Labels: official [0] -> strict [0, 1, 2, 3], lenient [0, 1, 2, 3].

## ga006

The question asks for each user's "average purchase revenue in USD per session", grouping sessions by ga_session_id.
The file (identical to the pre-rewrite gold) sums revenue within each session and averages over the user's purchase
sessions, e.g. 264.67 for user 10295267.8818269139 with 3 sessions. Lanes 0, 2 and 3 do this and match. Lane 1
averages over purchase events instead: 132.33 for that user (6 events) and 139.43 instead of 244.0 for user
12291446.3815334458 (7 events in 4 sessions). That is revenue per event, not per session. Duplicated purchase events
(see ga002) inflate the per-session sums, but the question prescribes summing per session, and lane 1's numbers are
not de-duplicated session means either.

Labels unchanged: [0, 2, 3].

## ga007

All values share the denominator 8,450, the page_view count for Jan 2 (k1 q1). File a is 1,455/8,450 = 17.218935;
its header holds the Snowflake SQL, which replaces '+' with a space before matching the 4th and 5th URL segments.
File b and the pre-rewrite gold are 1,478/8,450 = 17.49. The lanes count 1,171 (lane 0) or 1,172 (lanes 1-3) PDP
views. They compare segments like 'google+redesign' or 'campus+collection' with 'google redesign' or
'campus collection', which never match. So every product page under a multi-word category with no single-word
category beside it is missed, e.g. /Google+Redesign/Bags/... and /Google+Redesign/Campus+Collection/... The document
says "spaces are typically replaced by the '+' sign", so the lanes break its rule. The two files differ by 23 views,
probably exact versus substring category matching. No lane is near either file.

Labels unchanged: none right.

## ga009

Under the question's definition (session_engaged = '1', sessions keyed by user_pseudo_id + ga_session_id), December
2020 has 72,239 engaged sessions among 59,762 users (k4 q14, k1 q2) and 104,315 users in all (ga004 k1 q4, k3 q1). The
pre-rewrite gold, 0.69250826822604616, is exactly 72,239/104,315, the usual "engaged sessions per user". File a,
1.1276709965009826, is exactly 117,633/104,315: the same users but 45,394 more engaged sessions. One possible source
is the 115,423 December events that store session_engaged as integer 1 instead of string '1' (k1 q1, k2 q2), but no
trace counts sessions that way. File b, 1.142345, cannot be built from 72,239 or from 104,315 with any whole-number
partner, so it is unexplained. Files a and b also differ from each other by 0.0147. The lanes' 1.2088 is
72,239/59,762, an average over only the users who had an engaged session. Every gold version divides by all users,
and GA4 defines "Engaged sessions per active user" as "the average number of engaged sessions per active user"
(support.google.com/analytics/answer/9143382), where active users include users without an engaged session. So the
lanes are wrong whichever numerator is right, while the files themselves cannot be checked without warehouse data.

Labels unchanged: none right. Verdict unclear for the files only.

## ga013

The user viewed 10 distinct pages in 13 page views on Jan 2 (the pre-rewrite gold lists all 13 with URLs). Lane 2's
10 rows (Home, PDP x2, PLP x6, Page Unavailable) equal file d's PAGE_NAME column, and file a holds the same labels
per view, so lane 2 is right. It hard-codes each URL's class, but its output is correct. Lane 0's SELECT DISTINCT
collapses everything to 4 labels. Lane 1 collapses to 6 names, and its PLP rule never fires because 'Google+Redesign'
contains '+'. Lane 3 labels PDPs and PLPs correctly but prints two raw URLs where the question asks for "the names of
these pages" (Home, Page Unavailable). Two files are lax but affect no lane. File b scores only a category column
with 'Other' for the two non-product pages. File c reads the PLP rule's "Neither the fourth nor the fifth segment
contains a '+'" literally, so every /Google+Redesign/ listing page keeps its title.

Labels unchanged: [2].

## ga014

All three files count sessions by traffic_source, the user-level record of "the traffic source that first acquired
the user" (Spider2's GA4 schema document). The question asks for channels "using the information from the
'event_params'". The proof is exact: in the ga010 traces, two lanes (k2, k3) counted session_start events grouped by
traffic_source.source/medium and got file a to the session: Organic Search 45,298, Direct 30,516, Unassigned 27,035,
Referral 23,092, Paid Search 5,895. Files b and c differ by 2-17 per channel. This is also why the files have only
5 channels. traffic_source has no affiliate or email media, but event_params do: source 'Partners' with medium
'affiliate', and newsletter campaigns with medium 'email', 17 events each on Dec 1 alone (k3 q9). The pre-rewrite
gold had 9 channels, including Affiliates 225 and Email 66, total 133,368. No lane is right under an event_params
gold either. Lane 0 counts a session in every channel its events touch. Lanes 1 and 3 take MAX(source) and
MAX(medium) separately, so 'referral' beats 'organic' alphabetically. Lane 2 drops the 32,623 session IDs that have
no event with both source and medium (96,753 of 129,376).

Labels unchanged: none right. Gold wrong.

## ga018

The question mixes two phrasings: "the percentage of times users transition from a PLP view to a PDP view" and "how
many PLP views eventually led to a PDP view in the same session". The pre-rewrite gold, 10.79661512, is exactly
370/3,427: the gold SQL's immediate transitions (next page_view is a PDP). Both current files use 743 PLP views,
over 3,427 (file a, 21.68%) or 3,433 (file b, 21.64%), which fits the "eventually" reading. Lane 0 computed "PLP
followed later by a PDP" as 753/3,427 (k1 q20, q22), close to the files, but submitted 947/3,427, which also counts
PLP views after the session's last PDP. That matches neither reading. Lanes 1 and 2 find only 2,462 PLP views
because they match spaced category names against '+'-joined segments. Lane 2 also checks only the session's first
PDP and gets 173. Lane 3 ignores the category list (999 views, 32.96%). Since no lane takes either fair reading, this
is not two_readings. Minor issues that affect no lane: file b's 3,433 includes six PLP views of 4-segment URLs, and
the 743 vs 753 gap is unexplained.

Labels unchanged: none right.

## ga031

The question defines the rate as "the percentage of user visits that reached both the Home and Checkout Confirmation
pages in one session, relative to those that landed on the Home page", so both counts are visits. On Jan 2 there
are 2,606 sessions with page views, 805 with a 'Home' view and 14 with 'Checkout Confirmation', all 14 also with Home
(k2 trace, k4 q9). Session IDs are obfuscated 10-digit numbers, so keying by user plus session cannot add hundreds of
sessions. File a is exactly 14/1,146 and file b 14/1,166. They keep the visit numerator, but their denominators
exceed the 805 visits that viewed Home at all. Those denominators match the size of a day's Home page views instead:
the home URL alone had 1,533 views on Jan 31, a day with 9,498 page views against Jan 2's 8,450 (ga017 traces). So
the files divide visits by page views. Reading "landed on" as the landing page would only lower the denominator
below 805, so the files fail that reading too. Lanes 0-2 return 14/805 = 1.7391, the visit-level rate. Lane 3 returns
only the four counts and no rate. The pre-rewrite gold (37/1,671 = 2.214%) was not a visit rate either.

Labels: official [] -> strict [0, 1, 2], lenient [0, 1, 2]. Confidence medium: no trace counts Home page views on
Jan 2 directly.

## ga032

Both files (and the pre-rewrite pair) hold the same 45-step flow, differing only in '>>' spacing. Lanes 0, 1 and 3
reproduce file b exactly with a simple rule: at least 5 URL parts, '+' in the last part means PDP, otherwise PLP. On
this user's pages it gives the document's result. Lane 2 matches 'Google\s+Redesign' and 'Notebooks\s+Journals'
against '+'-joined segments. So .../Google+Redesign/Notebooks+Journals/Google+Large+Standard+Journal+Grey, a PDP
under the document's rule, stays a title. Its PLP rule also rejects 'Google+Redesign', leaving every listing page as
'Notebooks | Stationery | Google Merchandise Store'. The PDP miss alone makes lane 2 wrong under any reading of the
PLP rule.

Labels unchanged: [0, 1, 3].

## bq286

5 of the 80 girls named Bentley in 2021 were born in Wyoming (6.25%), far above the next names, Hadlee (5 of 347,
1.44%) and Wrenley (6 of 592) (k1 q3, k3 q2). Both files and the pre-rewrite gold say Bentley, so there is no tie
problem. Lanes 0, 2 and 3 match file a. Lane 1 puts state = 'WY' in the WHERE clause, so its national total is also
the Wyoming count and every share is 1. Its tie-break by Wyoming count then returns the most common name, Olivia.
File b scores the share in percent with all four columns required, which lane 0 (0.0625) fails, but file a accepts
it.

Labels unchanged: [0, 2, 3].

## bq230

All three files are wide, one row per state with a corn and a mushroom column, and agree on every value. They differ
only in whether OTHER STATES and zero rows appear (41, 42 or 50 rows). Lanes 0 and 1 give the same wide table (42
rows; NULL mushroom cells score as 0) and pass. Lanes 2 and 3 give a stacked table, one row per state and commodity
(51 rows). All 42 corn totals and 9 mushroom totals equal file a exactly (e.g. IOWA corn 12,486,150,000;
PENNSYLVANIA mushrooms 446,585,765). "Combine both results so that each state's 2022 corn and mushroom totals are
presented" reads most naturally as the wide table. But stacking the two results is also a way to "combine" them,
and a careful analyst could choose it, so I count lanes 2 and 3 under the lenient reading only. A caveat on
substance that affects no label: every file and lane sums all rows the listed filters allow, about four corn records
per state (176 rows for 42 entries), so each "total" is a multiple of the state's actual crop. The question's filter
list prescribes this sum.

Labels: official [0, 1] -> strict [0, 1], lenient [0, 1, 2, 3].
