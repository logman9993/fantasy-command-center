def test_dashboard_is_top25_only():
    source=open("fcc/application.py",encoding="utf-8").read()
    assert 'ranks = rankings(scoring, TOP_N)' in source
    assert '@app.get("/api/rankings/<position>")' in source

def test_browser_stale_while_revalidate():
    html=open("templates/index.html",encoding="utf-8").read()
    assert 'loadCachedBoard' in html and 'saveCachedBoard' in html and 'loadDeepBoard' in html
