#!/usr/bin/env python3
"""Retry-hardened launcher for the canonical D1 historical shard acquisition.

This wrapper changes only transport/retry behaviour for transient Wikidata
infrastructure conditions. It does not change subject identity, matching,
missingness, DOB selection, or scientific outputs.
"""
from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

TARGET = Path(__file__).with_name('nexus-d1-acquire-historical-wikidata-demographics-v2-shard.py')
spec = importlib.util.spec_from_file_location('nexus_d1_hist_shard_v2', TARGET)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def resilient_request(params, attempts=18):
    q = urlencode({**params, 'format': 'json', 'formatversion': '2', 'maxlag': '5'})
    url = f'{mod.API}?{q}'
    last = 'unknown'
    for i in range(attempts):
        delay = min(60.0, 2.0 * (i + 1))
        try:
            req = Request(url, headers={'User-Agent': mod.UA, 'Accept': 'application/json'})
            with urlopen(req, timeout=45) as r:
                raw = r.read()
                payload = json.loads(raw)
            err = payload.get('error')
            if err:
                code = str(err.get('code') or '') if isinstance(err, dict) else ''
                if code in {'maxlag', 'ratelimited', 'readonly'}:
                    lag = float(err.get('lag') or 0.0) if isinstance(err, dict) else 0.0
                    delay = max(8.0, min(60.0, lag * 2.0 + 5.0, 5.0 * (i + 1)))
                    last = f'RETRYABLE_API_{code}: {err}'
                else:
                    raise RuntimeError(str(err))
            else:
                time.sleep(0.85)
                return payload, raw
        except HTTPError as e:
            last = f'HTTP {e.code}: {e.reason}'
            retry = (e.headers or {}).get('Retry-After')
            if retry:
                try:
                    delay = max(delay, min(120.0, float(retry)))
                except ValueError:
                    pass
            if e.code not in {429, 500, 502, 503, 504}:
                raise
        except URLError as e:
            last = f'URL error: {e.reason}'
        except TimeoutError as e:
            last = f'TimeoutError: {e}'
        if i + 1 < attempts:
            time.sleep(delay)
    raise RuntimeError(f'RETRY_BUDGET_EXHAUSTED_AFTER_{attempts}: {last}')


mod.request = resilient_request

if __name__ == '__main__':
    mod.main()
