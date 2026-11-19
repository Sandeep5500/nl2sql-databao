# Light review, batch light1 (21 questions)

In every question all 4 lanes match an accepted gold file. 20 are `gold_right`. In one, bq120, the file that lane 2 matches is wrong in substance: it ranks single office rows of the SNAP table instead of counties, so it leaves out Cook County, the county with the second-highest total. Lane 2 leaves both right lists. Several other questions accept two fair readings in different files (bq300, bq074, ga012, bq395, bq352); the lanes take one of them each time, so their labels stand.

## bq280

The question asks for the display name of the user with the most answers among users whose reputation is above 10. The lanes' own top-10 query shows Gordon Linoff at 85,130 answers, then akrun at 36,082 and Jon Skeet at 35,491 (k1 q2, k2 q3). With a lead this large, two details cannot change the winner: counting distinct questions instead of answers, and lane 2 grouping by display_name only, which could merge namesakes. All four lanes return Gordon Linoff, the single file's value. Verdict: `gold_right`.

## bq300

The two files hold two readings of "Python 2 specific question ... excluding any discussions that involve Python 3". File a (26) presumably comes from the gold SQL, which finds Python 2 questions by tag or text and drops any whose title or body mentions Python 3. File b (43) is the tag reading: tagged python-2.7 and carrying no Python 3 tag. All lanes take the tag reading; the top question is 27835619, "urllib and SSL: CERTIFICATE_VERIFY_FAILED Error", with 43 answers and tags python|python-2.7|ssl|ssl-certificate|urllib. k2 also admitted python-2.x and python-2.6, excluded every python-3.* tag, and still got 43. k1 excluded only python-3.x, but the top question has no Python 3 tag, so its value is the same. Using answer_count instead of counting rows in posts_answers is a fair choice. Verdict: `gold_right`.

## bq301

The lanes return the same four accepted answers as both files, and every value equals file a (for example 34629303: answerer reputation 76,627, answer score 4, 0 answer comments, 2,262 question views). File b lists the same answers with lower view counts (58-96) and 2 comments on one answer, which fits an older data snapshot. The lanes' filters follow the question word for word: javascript plus one of the four security tags, the question and the accepted answer both posted in January 2016. Verdict: `gold_right`.

## bq303

"Each of their contributions" means one row per question, answer and comment, each with the parent question's tags. k4's output labels each row with its type: 14 questions, 6 answers, 15 comments on questions and 8 comments on answers, 43 rows. As a multiset, the lanes' rows equal file a exactly (checked locally). File b is a 21-row subset of file a that matches no clean subset of contribution types, and no lane relies on it. Verdict: `gold_right`.

## bq305

Only the user ID column is scored. All nine files and all four lanes list the same ten users, led by Jon Skeet and VonC. The view totals differ by at most 1.1% between versions (tie-breaking in the "top three answers" rule, and data versions); lane 0 equals file d and lanes 2-3 equal file e exactly. The lanes' association rules follow the question's five conditions. Verdict: `gold_right`.

## bq306

The question spells out the formula, and the lanes apply it directly. For each answer by user 1908967 before 2018-06-07 they count vote_type_id 2 and vote_type_id 1 votes, then for each tag they sum 10 x upvotes + 15 x acceptances. All ten tags and scores equal the single file, including the four-way tie at 1,850 (http-headers, meta, penetration-testing, owasp). Verdict: `gold_right`.

## bq309

All lanes reproduce the ten longest qualifying questions (36322879 at 71,445 characters down to 68291731 at 53,259) and the askers' reputation, net votes and badge counts. These values are identical in all three files. There is a scoring quirk: file c's column list includes its RN rank column, so file c accepts only answers that include a 1-10 rank. File a does not score the badge column, and file b does not score the question IDs. None of this affects the lanes, which match files a and b in every value. Verdict: `gold_right`.

## bq310

All lanes return "How to close/hide the Android soft keyboard programmatically?" (1,752,733 views), which is file c. The lanes accepted any tag containing "android" instead of the question's list of specified tags. But this question carries android-edittext, one of the gold SQL's ten tags, and it is the most viewed android "how" question of all (the next has 1,692,967 views, k1 q5), so a narrower android tag list still selects it. Files a and b give other titles from other tag sets, and the lanes do not depend on them. Verdict: `gold_right`.

## bq011

The lanes define the 7-day window as the daily tables 20210101-20210107 and the 2-day window as 20210106-20210107. They count users with positive engagement time in the first window but not the second: 12,212, the single file's value. The gold SQL instead bounds the windows by UTC timestamps and starts its 2-day table range at 20210105, which can differ at the edges if the daily tables follow the property's local time. The accepted file follows the table-date reading, and that reading is fair. Verdict: `gold_right`.

## ga001

The lanes read "alongside" as "in the same transaction". In December 2020 transactions that include the Navy Speckled Tee, Google 24oz Ring Bottle Blue has the highest quantity among the other items, 32, ahead of Google Pen White (24) and Google Metallic Notebook Set (19). File a holds the same item. File b repeats that item and quantity 32 for each of 42 buyers, which shows that the gold SQL's buyer-level reading gives the same product. Verdict: `gold_right`. File b can only be matched by a 42-row per-buyer answer, which is harmless here.

## ga008

The files follow the question's month-level restriction ("users who made at least one purchase in November 2020"), not the stale gold SQL's purchase-day restriction. The lanes compute exactly that. Per day, they take the page views of November purchasers and divide by the number of those purchasers who viewed pages that day. All 30 rows equal file a to every printed digit (Nov 1: 642 and 19.4545; Nov 30: 5,522 and 30.8492). Verdict: `gold_right`.

## ga011

After the path is extracted and repeated slashes are collapsed, the ranking is "/" (about 53,860 views), "/basket.html" (about 30,845) and "/Google+Redesign/Apparel" (28,575) (k3 q8). The second place is the same with or without cleaning (k2 q11: 53,807 and 30,841). All lanes return "/basket.html", which is in files a and b; file c drops the leading slash. Verdict: `gold_right`.

## ga012

Tax and revenue are recorded per purchase event, not per item, so a category's tax rate has to aggregate over the events that contain the category. Two aggregations are reasonable. Averaging the per-event ratios (k1 q2, k3 q6) puts Shop by Brand on top at 0.1088, against 0.0990 for Campus Collection, mainly because order 631543 paid $1 tax on $3 (33%). That gives file a's 13 transactions, which lanes 0-2 match. The ratio of sums, which is what the gold SQL computes, puts Campus Collection on top (0.0958 against 0.0936, k4 q5). That gives the 23 transactions of files c and d, which lane 3 matches. Both aggregations fit "dividing tax value in usd by purchase revenue in usd for purchase events", and the gold accepts both, so every lane's label stands. File b is degenerate: it names "(not set)" as the category and lists 134 transactions, essentially every purchase that day, including orders whose items are Apparel (e.g. 109852). No lane matches it. Verdict: `gold_right`, medium confidence, because the winning category depends on the aggregation.

## ga017

The most viewed page_location in January 2021 is the shop home page (71,599 views; the next has 40,583), with 30,467 distinct users, equal to file a. File b's 37,165 presumably merges home-page variants (the bare and www domains, or the "Home" title); the lanes do not need it. Verdict: `gold_right`.

## bq074

"An increase in unemployment" can mean more unemployed people or a higher unemployment rate. k1 computed both on the same joins: the count gives 98 (q13, file a) and the rate gives 104 (q12, file b). All lanes use the rate and return 104. Both readings are fair and both are accepted; file c's 99 is a third variant. Verdict: `gold_right`.

## bq097

The lanes take the 14 county GeoNames ending in ", MA" and subtract the 2012 average earnings per job from the 2017 value. All 14 increases equal the file, from Suffolk (10,664) down to Dukes (822), and the increase is the only scored column. Verdict: `gold_right`.

## bq110

The lanes join the 2012 and 2018 rows on CoC_Number for New York and report the change in homeless veterans. All 26 rows equal the file in every column (checked locally), for example New York City, 3,790 to 605, a change of -3,185. Verdict: `gold_right`.

## bq120

The question asks for "the top 10 regions (counties) with the highest total number of SNAP-participating households". In the SNAP table, Cook County, IL (FIPS 17031) is split into 30 office rows on 2017-01-01 (k4 q17: COOK - NORTHERN 47,549, COOK - SOUTH SUBURBAN 46,290 and so on; 13 rows are 0). The rows sum to 480,564 (k1 q11, k2 q9), the second-highest county total after Los Angeles (533,894). Every other county in the top ten has a single row. Files a, b and c rank county totals and include Cook (ratio 0.7156). File d ranks single rows, as the stale gold SQL does (it joins rows without summing). Cook's largest office row (47,549) is far below the top ten, so Cook drops out and San Diego (135,503, ratio 1.0222) comes in tenth. A top-ten list of counties that leaves out the county with the second-highest total does not answer the question. Lanes 0, 1 and 3 sum by FIPS and match file a. Lane 2 filtered Program = 'EBT', did not sum, and matched only file d, even though its own trace (k3 q7) showed 30 rows for 17031. Verdict: `gold_wrong` (file d); lane 2 leaves both lists, so strict and lenient are [0, 1, 3]. Confidence is high: the data and the word "(counties)" decide it.

## bq352

Six Wisconsin counties pass the commuting filter: Kenosha, Racine, Rock, Walworth, Washington and Waukesha (file b; k4 names the same six). Their 2018 averages range from 11.24 to 13.35 prenatal weeks. All lanes return 12.18, the unweighted mean of these six values (73.08 / 6), which is file a. The wording "list the average number of prenatal weeks ... for counties" leans toward file b's per-county list. But "the average ... for counties" can also be read as one average over the qualifying counties, the maintainers accept that reading, and the single number rests on the right six counties. I keep the official labels. Verdict: `gold_right`, medium confidence.

## bq395

Summing by CoC prefix gives 54 jurisdictions (the 50 states plus DC, PR, GU and VI), with an average 2015-2018 change of 13.07%. The closest five are MO, VA, DC, NH and KY; NE is sixth, 0.09 points behind KY (k3 q5, k4 q8). All lanes return these five, equal to file b. File a (MO, VA, NH, KY, NE) is what you get when DC, the three territories, or both are left out. I recomputed all three choices from the lanes' per-state values, and each gives the same five. That is a strict reading of "each state". HUD's own CoC numbering treats DC, PR, GU and VI as state codes, so both readings are fair, and both are accepted. Verdict: `gold_right`.

## bq398

The lanes rank Russia's indicators by their largest value and return the three principal-repayment indicators: DT.AMT.DLXF.CD (18.50 billion), DT.AMT.DPPG.CD (9.57 billion) and DT.AMT.PRVT.CD (9.55 billion). These equal file a. File b names the same three, and its values are exactly 56 times file a's (18,498,824,669.4 x 56 = 1,035,934,181,486.4). That is the sum over the table's 56 duplicate copies of each value, the duplication noted in the Nov 18 audit for bq424. Only the names are scored. These indicators are repayment flows rather than debt stocks, but the long-term debt stock is entirely NULL in this table, so they are the highest debt values available. Verdict: `gold_right`.
