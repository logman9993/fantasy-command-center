from fcc.cache import timed_cache

def test_timed_cache_reuses_bucket():
    calls=[]
    @timed_cache(ttl=3600)
    def f(x):
        calls.append(x);return x*2
    assert f(2)==4 and f(2)==4 and calls==[2]
