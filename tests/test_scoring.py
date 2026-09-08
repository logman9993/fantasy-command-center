from fcc.scoring import scoring_rules, score_stats, slots_from

def test_ppr_scoring():
    rules,_=scoring_rules("PPR")
    assert score_stats({"receptions":5,"receiving_yards":100,"receiving_tds":1},rules)==21

def test_flex_slots():
    assert slots_from({"QB":1,"RB":2,"WR":2,"FLEX":1})["FLEX"]==1
