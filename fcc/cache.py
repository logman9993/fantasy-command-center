"""Shared cache backend: Render Key Value/Redis first, atomic disk fallback second."""
from __future__ import annotations

import csv
import io
import json
import os
import tempfile
import time
from functools import lru_cache, wraps
from pathlib import Path

from fcc.config import CACHE_DIR, REDIS_URL

try:
    import redis
except Exception:  # optional locally; required on Render via requirements.txt
    redis = None

_PREFIX = "fcc:v101:"
_redis = None


def redis_client():
    global _redis
    if _redis is False:
        return None
    if _redis is not None:
        return _redis
    if not REDIS_URL or redis is None:
        _redis = False
        return None
    try:
        client = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=2, socket_timeout=3)
        client.ping()
        _redis = client
        return client
    except Exception:
        _redis = False
        return None


def _atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def timed_cache(maxsize=128, ttl=900):
    def decorate(fn):
        @lru_cache(maxsize=maxsize)
        def cached(bucket, *args, **kwargs):
            return fn(*args, **kwargs)
        @wraps(fn)
        def wrapped(*args, **kwargs):
            return cached(int(time.time() // ttl), *args, **kwargs)
        wrapped.cache_clear = cached.cache_clear
        return wrapped
    return decorate


def _redis_get_json(key):
    client = redis_client()
    if not client:
        return None
    try:
        raw = client.get(_PREFIX + key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def _redis_set_json(key, value, ttl=None):
    client = redis_client()
    if not client:
        return
    try:
        raw = json.dumps(value, separators=(",", ":"))
        if ttl:
            client.setex(_PREFIX + key, int(ttl), raw)
        else:
            client.set(_PREFIX + key, raw)
    except Exception:
        pass


def cached_json(name, ttl, loader):
    key=f"json:{name}"
    cached=_redis_get_json(key)
    if cached is not None:
        return cached
    path=CACHE_DIR/f"{name}.json"
    if path.exists() and time.time()-path.stat().st_mtime < ttl:
        try:
            data=json.loads(path.read_text(encoding="utf-8"))
            _redis_set_json(key,data,ttl)
            return data
        except Exception:
            pass
    data=loader()
    _atomic_write(path,json.dumps(data))
    _redis_set_json(key,data,ttl)
    return data


def stale_cached_json(name, ttl, stale_ttl, loader, force=False):
    now=time.time(); key=f"stale:{name}"
    packed=_redis_get_json(key)
    if packed and isinstance(packed,dict) and "data" in packed and "saved_at" in packed:
        age=max(0,now-float(packed["saved_at"]))
        if not force and age < ttl:
            return packed["data"], {"cached":True,"stale":False,"age_seconds":int(age),"backend":"redis"}
    path=CACHE_DIR/f"{name}.json"
    existing=None; age=None
    if packed and isinstance(packed,dict):
        existing=packed.get("data"); age=max(0,now-float(packed.get("saved_at",now)))
    elif path.exists():
        try:
            age=max(0,now-path.stat().st_mtime)
            existing=json.loads(path.read_text(encoding="utf-8"))
            if not force and age < ttl:
                _redis_set_json(key,{"data":existing,"saved_at":now-age},stale_ttl)
                return existing,{"cached":True,"stale":False,"age_seconds":int(age),"backend":"disk"}
        except Exception:
            existing=None; age=None
    try:
        data=loader(); saved=time.time()
        _atomic_write(path,json.dumps(data))
        _redis_set_json(key,{"data":data,"saved_at":saved},stale_ttl)
        return data,{"cached":False,"stale":False,"age_seconds":0,"backend":"origin"}
    except Exception as exc:
        if existing is not None and age is not None and age < stale_ttl:
            return existing,{"cached":True,"stale":True,"age_seconds":int(age),"refresh_error":str(exc)[:180],"backend":"redis/disk"}
        raise


def cached_csv(name, ttl, urls, must_have, http_text):
    key=f"csv:{name}"
    client=redis_client()
    text=None
    if client:
        try:text=client.get(_PREFIX+key)
        except Exception:text=None
    if text and all(x.lower() in text[:12000].lower() for x in must_have):
        return list(csv.DictReader(io.StringIO(text))), "redis cache"
    path=CACHE_DIR/f"{name}.csv"
    if path.exists() and time.time()-path.stat().st_mtime < ttl:
        text=path.read_text(encoding="utf-8",errors="replace")
        if all(x.lower() in text[:12000].lower() for x in must_have):
            if client:
                try:client.setex(_PREFIX+key,int(ttl),text)
                except Exception:pass
            return list(csv.DictReader(io.StringIO(text))),"disk cache"
    last=None
    for url in urls:
        try:
            text=http_text(url)
            if not all(x.lower() in text[:12000].lower() for x in must_have):
                raise ValueError(f"unexpected CSV schema from {url}")
            _atomic_write(path,text)
            if client:
                try:client.setex(_PREFIX+key,int(ttl),text)
                except Exception:pass
            return list(csv.DictReader(io.StringIO(text))),url
        except Exception as exc:
            last=exc
    raise RuntimeError(last or "no source URL succeeded")
