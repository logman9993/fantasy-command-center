def test_yahoo_cookie_policy_source():
    source=open("fcc/application.py",encoding="utf-8").read()
    assert 'httponly=True' in source
    assert 'samesite="Lax"' in source
    assert 'YAHOO_TOKEN_SECRET' in source

def test_espn_rate_limit_source():
    source=open("fcc/application.py",encoding="utf-8").read()
    assert '20 per minute' in source
    assert 'extension_identity_ok' in source
