# deep02 audit notes (Nov 19 2026)

Batch: bq001, bq003, bq004, bq008, bq009, bq010, bq268, bq275, bq374 (all ga360). Lane n = trace folder lane_k(n+1).
Pre-rewrite golds were read from the Spider2 submodule history (parent of commit 5fa8a517; Snow twins at the parent of
575a7a4f). Full lane results were not stored, so lane values come from the traces (the previews each agent saw and its
intermediate queries).

Verdicts: gold_right 5 (bq001, bq003, bq004, bq010, bq268), gold_wrong 3 (bq009, bq275, bq374), two_readings 1
(bq008), scoring_defect 0, unclear 0.

## bq001

The question asks, per visitor who transacted in February 2017, the days from their first February visit to their first
February transaction, and the device of that transaction. Files a and b agree visitor for visitor (666 visitors, same
days and devices, 493 with 0 days), and lanes 0, 2 and 3 match file a on the only scored column (days, as a sorted
vector); their visible rows (12, 50 and 20) also agree on the unscored device. File c is exactly one day higher for 163
visitors and never lower. The traces explain it: in lane 1's q3, every transaction session that starts after 16:00
Pacific, which is the next day in UTC, belongs to a visitor file c shifts (7750340404205493317 at 22:53 PST on Feb 28:
a 0, c 1; 4822692999413007561 at 22:51 PST: a 4, c 5; 9806766048628835536 at 18:18 PST: a 0, c 1), and the 19 sessions
that start earlier are unshifted. So file c takes the transaction date in UTC and the first-visit date in local time, a
mix no fair reading supports, but no lane matches it. Lane 1 hit the step limit and its fallback is a count of visitors
(666), wrong under any reading.

Labels: official [0, 2, 3] -> strict [0, 2, 3], lenient [0, 2, 3].

## bq003

The question asks for the "average pageviews per visitor" by month for purchase and non-purchase sessions. Both files
divide total pageviews by distinct visitors (April: 25.8897 purchase, 3.9793 non-purchase). Lane 1's intermediate q5,
which sums pageviews per visitor and month before averaging, reproduces file b exactly for purchase (25.88965517,
23.61137441, 25.73576310, 27.72095436) and within 0.004 for non-purchase. Lane 1 then submitted its per-session q4 (24.27
and 3.32) instead. Lanes 0, 2 and 3 also average per session; lane 0 also drops sessions without product rows and lane
2 groups by visitor and day. A per-session average is not a fair reading of "per visitor". The pre-rewrite gold (June
94.02 and 316.87) came from the gold SQL, which sums totals.pageviews once per product row; the rewrite fixed that.

Labels: official [] -> strict [], lenient [].

## bq004

The question asks, among visitors who bought a YouTube product in July 2017, for the non-YouTube product with the
highest total quantity purchased. Identifying YouTube products by name and limiting both the YouTube purchase and the
counted quantities to purchase hits (action_type 6) gives Sport Bag 508, then Google Spiral Journal with Pen 502 (lane 2
q3). File c holds exactly Sport Bag, 508, and files a and b hold the name. Lane 0 groups by visitor and product over all
hit types, so its 1,849 water bottles are one visitor's add-to-cart, checkout and purchase rows. Lane 3 does the same
with a category filter on any hit (Google Stylus Pen, 902). Lane 1 showed that the 'Home/Shop by Brand/YouTube/' category
never appears on purchase hits (q7, q9, q13, q15 all empty). It then took any session that had a transaction and
showed a YouTube-category product somewhere, which does not establish that a YouTube product was bought (Suitcase
Organizer Cubes, 57). The pre-rewrite gold (Google 22 oz Water Bottle) came from the gold SQL, which never filters to
purchases.

Labels: official [2] -> strict [2], lenient [2].

## bq008

The question asks which page Data Share visitors most commonly visited next after a '/home' page in January 2017, and
the longest time they spent on '/home' "before moving on". Both files say men's outerwear. Every lane says /home,
because the page hit after a /home pageview is /home 114 times and men's outerwear 75 times (lane 0 q34); the repeats are
real later views, with gaps from 20 s to 20 minutes, not duplicate hits. The files take the next *different* page, as the
gold SQL does by keeping one entry per page per session, and "before moving on" supports that. But Google's own
definitions support the lanes: "If a user clicks reload after reaching the page, this is counted as an additional
pageview", and time on page "is calculated as the difference between the initiation of successive pageviews"
(support.google.com/analytics/answer/1257084 and /2731565). On that convention the answer is /home with 1785.274 s, the
gap from /home at 0 s to men's outerwear at 1785.274 s in session 8048318129624286340 (lane 0 q37). File b's
1785.274 is that same gap. File a's 2848.473 (the gold SQL's output and the pre-rewrite gold) is session
9155241064844669128 measured from its first /home view to its first different page, which spans a /home repeat at
1259.148 s. I mark two readings: lanes 0 and 2 (/home, 1785) are right under the pageview convention, although their
integer 1785 would still miss 1785.274 by more than the 0.01 tolerance. Lane 1 computes LEAD over /home rows only (its
2451 s spans other pages) and lane 3 reports milliseconds as seconds (1,785,274), so both are wrong under either
reading.

Labels: official [] -> strict [], lenient [0, 2].

## bq009

The question asks for the traffic source with the most 2017 transaction revenue and the difference between its highest
and lowest monthly totals. All four lanes find (direct) and see the same monthly totals (revenue / 10^6): Jan 96,134.16,
Feb 98,118.79, Mar 94,102.63, Apr 99,197.44, May 96,132.33, Jun 97,231.62, Jul 126,887.80, Aug 8,872.04 (the data ends on
Aug 1). Max minus min is 118,015.76 with the one-day August, which is what the gold SQL computes over
ga_sessions_2017*; it was also the pre-rewrite gold for both bq009 and sf_bq009. Over full months only it is 32,785.17.
Both new files say 4,659.15, which is not the difference between any two monthly totals (closest pairs: 5,094.81 Apr -
Mar and 4,016.16 Feb - Mar). It is not reached with product revenue either: (direct)'s Jan-Jun product revenue from the
bq002 traces spans 4,905.81. The question names "total transaction revenue", the documented totals.totalTransactionRevenue,
so the files contradict the field's observed values. I mark gold wrong at medium confidence (a field nobody looked at
could in principle produce it). Lanes 0, 1 and 2 return 118,015.76 and are right under the SQL's convention, where "in
millions" means the stored value divided by 10^6. Lane 3 divided by 10^9 (118.02), which is neither dollars nor true
millions.

Labels: official [] -> strict [0, 1, 2], lenient [0, 1, 2].

## bq010

The question asks for the top-selling product among customers who bought the YouTube Men's Vintage Henley in July 2017.
Twelve visitors bought it. Among their purchase hits, Google Sunglasses leads with 20 units (4 SKUs x 5) over 7 for the
runner-up, whether the counted purchases are limited to July or cover the whole dataset (lane 1 q5, q6). File a, the
pre-rewrite gold and the gold SQL's July-only logic all give it. Lanes 1 and 2 count all-time purchases and lane 3 sums
quantity over all July hits (its 120 is inflated by add-to-cart and checkout rows), but only the name is scored and all
three name the right product. File b (YouTube Men's Vintage Tank, 32,952) cannot be a sales count for 12 buyers;
it looks like a count of impression rows, but no lane matches it. Lane 0 counts anyone who merely saw the Henley and
sums quantities over all hits of the whole year (Google 22 oz Water Bottle, 7,113), wrong under any reading.

Labels: official [1, 2, 3] -> strict [1, 2, 3], lenient [1, 2, 3].

## bq268

The question asks for the longest gap between a user's first visit and "the last recorded event (either the last visit
or the first transaction)" when that event was on a mobile device. The gold SQL uses the first transaction as the event
for buyers and the last visit otherwise, with deviceCategory = 'mobile'. That gives 357 (user 8024562944722892732,
2016-08-09 to 2017-08-01), which is file a and the pre-rewrite gold. Read literally, "last recorded event" is the later
of the two, which is always the last visit (lane 2 q7 finds no first transaction after a last visit). That gives 359 via
user 5682452231721622029: mobile in every session, first visit 2016-08-03, last visit 2017-07-28, first transaction
2016-08-30. This is file b and lanes 0 and 2. isMobile is also true for tablets (lane 0 q1), which is a second route to
359. Since the files accept both readings, the labels stand. Lane 3 is right only by value: it ranked users by the integer
difference of YYYYMMDD strings, hard-coded the top pair's dates (357), and ran out of steps after its q30 showed two
359-day users. File c's 212 could not be explained, but no lane matches it. Lane 1's fallback is a LIMIT 5 exploration
query.

Labels: official [0, 2, 3] -> strict [0, 2, 3], lenient [0, 2, 3].

## bq275

The question asks for the visitors whose first transaction was on a 'mobile' device on a later date than their first
visit, with no time window. The gold SQL computes exactly that and produced the pre-rewrite gold of 230 visitors. Lanes
0, 2 and 3 run the same logic and return 230 rows, every visible row (50, 12, 12) in that set. Lane 1 requires the
earliest transaction session itself to be mobile, which is a stricter version of the same condition, and it also returns
230 rows (all 50 visible in the set), so its set must be the same. The four new files hold 33, 23, 37 and 8 visitors,
of which 17, 22, 36 and 8 are in the 230. File d shares no visitor with the others. Files a, b and c all include
4950411203281265700, which the full-period logic excludes. The dated members suggest each file was computed over only
some months: 10 of 11 dated file-b visitors first bought in July 2017, and both dated file-d visitors in January 2017.
No file answers the question as asked, and no complete answer can pass. Confidence is high for the gold being wrong;
that the lanes equal the old 230 rests on identical logic, row counts and visible rows.

Labels: official [] -> strict [0, 1, 2, 3], lenient [0, 1, 2, 3].

## bq374

The question asks for the percentage of new users (Aug 1 2016 to Apr 30 2017) who stayed over 5 minutes on their first
visit and bought on a later visit "at any later time". Lane 0 counts 549,137 new users, 48,532 with timeOnSite > 300 on
the first visit, and 1,691 of those with a later purchase, = 0.30794%. The other lanes give 0.31, 0.30757 and 0.31, with
small ordering conventions (visitNumber versus visitStartTime). The pre-rewrite gold was 0.30848% (about 1,694 users),
the gold SQL's own result, and every lane is within 0.0015 of it. The new files say 0.152247% and 0.04%, which would mean
about 836 and 220 qualifying users. Even restricting the purchase to the window, which "at any later time" rules out,
removes at most 326 users (lane 0 q5) and leaves at least 0.249%. I found no reading that produces either file, so the
gold is wrong (medium, since the files' own method is unknown) and all four lanes are right.

Labels: official [] -> strict [0, 1, 2, 3], lenient [0, 1, 2, 3].
