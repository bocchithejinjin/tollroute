"""検索 API の簡単な回数制限（使いすぎ防止）。

接続元ごとに、直近 60 秒の呼び出し回数を数える。プロセスごとのメモリに持つだけの簡易版
（gunicorn のワーカーごとに数えるので、実際の上限はワーカー数倍まで緩くなる）。
接続元は Cloudflare 経由なら CF-Connecting-IP、そうでなければ REMOTE_ADDR。
"""
from __future__ import annotations

import threading
import time
from collections import deque
from functools import wraps

from django.conf import settings
from django.http import JsonResponse

WINDOW = 60.0
_hits: dict[str, deque] = {}
_lock = threading.Lock()


def client_key(request) -> str:
    return request.META.get("HTTP_CF_CONNECTING_IP") or request.META.get("REMOTE_ADDR", "unknown")


def reset() -> None:
    with _lock:
        _hits.clear()


def limited(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        limit = getattr(settings, "SEARCH_RATE_LIMIT_PER_MIN", 30)
        if limit > 0:
            now = time.monotonic()
            key = client_key(request)
            with _lock:
                q = _hits.setdefault(key, deque())
                while q and now - q[0] > WINDOW:
                    q.popleft()
                if len(q) >= limit:
                    retry = int(WINDOW - (now - q[0])) + 1
                    res = JsonResponse({"error": f"検索が多すぎます。{retry} 秒ほど待ってからもう一度試してください。"},
                                       status=429)
                    res["Retry-After"] = str(retry)
                    return res
                q.append(now)
                if len(_hits) > 10_000:  # 古い接続元を捨ててメモリを抑える
                    for k in [k for k, v in _hits.items() if not v or now - v[-1] > WINDOW]:
                        del _hits[k]
        return view(request, *args, **kwargs)

    return wrapper
