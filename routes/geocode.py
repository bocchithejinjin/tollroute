"""住所・駅名 → 緯度・経度。

住所: jageocoder（手元の辞書だけで変換し、外部には送らない）。
  辞書: jageocoder の街区レベル辞書（gaiku_all_*.zip）。置き場所は環境変数 JAGEOCODER_DB2_DIR
  （未設定なら <プロジェクト>/data/jageocoder/db）。辞書がなければ GeocoderUnavailable を出す。
駅名: HeartRails Express API（https://express.heartrails.com/ ）の getStations。
  「新宿三丁目駅」のように「駅」で終わる入力か、住所として見つからない短い入力のときだけ使う。
  外部に送るのは駅名（末尾の「駅」を除いたもの）だけ。結果はメモリにキャッシュする。
  無料で使う条件として、画面に「HeartRails Express」のクレジットを表示する（STATION_CREDIT）。
"""
from __future__ import annotations

import json
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "jageocoder" / "db"

# jageocoder の住所レベル
LEVEL_LABEL = {1: "都道府県", 2: "郡", 3: "市区町村", 4: "政令市の区", 5: "大字・町", 6: "丁目・字", 7: "街区・地番", 8: "住居番号"}
# 駅名検索で見つけた地点のレベル（jageocoder のレベルとは別に、駅を表す値）
STATION_LEVEL = 100
LEVEL_LABEL[STATION_LEVEL] = "駅"

HEARTRAILS_URL = "https://express.heartrails.com/api/json"
HEARTRAILS_TIMEOUT = 3.0  # 秒
USER_AGENT = "tollroute/0.1"
# 画面に出すクレジット（HeartRails Express を無料で使う条件）
STATION_CREDIT = "駅名検索: HeartRails Express"
STATION_CREDIT_URL = "https://express.heartrails.com/"
# 同名の駅から選ぶときの基準点（今の対象地域は関東なので東京駅付近）
PREFERRED_CENTER = (35.6812, 139.7671)


class GeocoderUnavailable(RuntimeError):
    pass


class AddressNotFound(ValueError):
    pass


class StationLookupUnavailable(GeocoderUnavailable):
    """駅名検索の API に接続できない（ビューでは 503 にする）。"""


@dataclass(frozen=True)
class Place:
    name: str
    lat: float
    lon: float
    level: int
    detail: str = ""  # 駅なら「東京都 東京メトロ丸ノ内分岐線」など
    others: tuple[str, ...] = ()  # 同じ名前のほかの駅（路線・都道府県）

    @property
    def level_label(self) -> str:
        return LEVEL_LABEL.get(self.level, str(self.level))


@lru_cache(maxsize=1)
def _init():
    db = Path(os.environ.get("JAGEOCODER_DB2_DIR", DEFAULT_DB))
    if not db.exists():
        raise GeocoderUnavailable(f"住所の辞書が見つかりません（{db}）。README の手順で入れてください。")
    try:
        import jageocoder
    except ImportError as exc:  # pragma: no cover
        raise GeocoderUnavailable("jageocoder が入っていません") from exc
    jageocoder.init(db_dir=str(db), mode="r")
    return jageocoder


def geocode(text: str) -> Place:
    """住所か駅名の文字列を、いちばんよく当たった地点にする。見つからなければ AddressNotFound。

    - 「駅」で終わる入力は駅名として検索する（見つからなければ AddressNotFound）。
    - それ以外は住所として jageocoder で探し、見つからない（か辞書がない）ときに、
      短い入力なら駅名としても探す。
    """
    text = text.strip()
    if not text:
        raise AddressNotFound("住所が空です")
    if looks_like_station(text):
        return geocode_station(text)
    try:
        return geocode_address(text)
    except (AddressNotFound, GeocoderUnavailable) as exc:
        if not maybe_station(text):
            raise
        try:
            return geocode_station(text)
        except (AddressNotFound, GeocoderUnavailable):
            # 住所として探した結果のエラーを優先する（駅名はついでに試しただけ）
            raise exc from None


def geocode_address(text: str) -> Place:
    """住所の文字列を jageocoder で地点にする。"""
    text = text.strip()
    if not text:
        raise AddressNotFound("住所が空です")
    jg = _init()
    result = jg.search(text)
    cands = result.get("candidates") or []
    if not cands or not result.get("matched"):
        raise AddressNotFound(f"住所が見つかりません: {text}")
    best = cands[0]
    lat, lon = float(best["y"]), float(best["x"])
    if not (20 <= lat <= 46 and 122 <= lon <= 154):
        raise AddressNotFound(f"住所の座標が見つかりません: {text}")
    name = "".join(best.get("fullname") or [best.get("name", text)])
    level = int(best.get("level", 0))
    if level < 5:
        raise AddressNotFound(f"住所を町名より細かく特定できません: {text}（{name} まで一致）")
    return Place(name, lat, lon, level)


# ---- 駅名検索（HeartRails Express） ----

MAX_STATION_CHARS = 20  # 駅名とみなす入力の長さの上限
SHORT_TEXT_CHARS = 10  # 住所で見つからないとき、駅名としても探す入力の長さの上限
# 番地らしい文字（数字・ハイフン・カンマ）を含む入力は駅名とみなさない（長音「ー」は駅名に使うので除外しない）
_NOT_STATION = re.compile(r"[0-9０-９\-－‐,，]")
_cache: dict[str, list[dict]] = {}
_cache_lock = threading.Lock()
_CACHE_MAX = 1000


def station_query(text: str) -> str:
    """入力から検索に使う駅名を取り出す（末尾の「駅」を除く）。"""
    name = text.strip().replace("　", "").replace(" ", "")
    return name[:-1] if name.endswith("駅") else name


def looks_like_station(text: str) -> bool:
    """「新宿三丁目駅」のように「駅」で終わる短い入力か。"""
    t = text.strip()
    return t.endswith("駅") and 2 <= len(t) <= MAX_STATION_CHARS and not _NOT_STATION.search(t)


def maybe_station(text: str) -> bool:
    """住所で見つからなかったとき、駅名として探してみる入力か（短く、番地を含まない）。"""
    t = text.strip()
    return 1 <= len(t) <= SHORT_TEXT_CHARS and not _NOT_STATION.search(t)


def _fetch_stations(name: str) -> list[dict]:
    """HeartRails Express の getStations を呼ぶ。送るのは駅名だけ。テストではこれを差し替える。"""
    query = urllib.parse.urlencode({"method": "getStations", "name": name})
    req = urllib.request.Request(f"{HEARTRAILS_URL}?{query}", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=HEARTRAILS_TIMEOUT) as res:
            data = json.loads(res.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise StationLookupUnavailable(
            "駅名検索（HeartRails Express）に接続できませんでした。しばらくしてからもう一度試すか、住所で入力してください。"
        ) from exc
    resp = data.get("response") if isinstance(data, dict) else None
    if not isinstance(resp, dict):
        raise StationLookupUnavailable("駅名検索（HeartRails Express）の応答が読み取れませんでした。")
    stations = resp.get("station")
    if not stations:  # 見つからないときは {"response": {"error": "Station '...' not found."}}
        return []
    return [s for s in stations if isinstance(s, dict)]


def _stations(name: str) -> list[dict]:
    """駅名で検索した結果（メモリにキャッシュする。見つからなかった結果もキャッシュする）。"""
    with _cache_lock:
        if name in _cache:
            return _cache[name]
    stations = _fetch_stations(name)
    with _cache_lock:
        if len(_cache) >= _CACHE_MAX:
            _cache.clear()
        _cache[name] = stations
    return stations


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def geocode_station(text: str) -> Place:
    """駅名を地点にする。駅名が完全に一致する最初の駅を使い、ほかの同名駅は others に入れる。"""
    name = station_query(text)
    if not name:
        raise AddressNotFound("駅名が空です")
    found = []
    for s in _stations(name):
        if s.get("name") != name:
            continue
        try:
            lat, lon = float(s["y"]), float(s["x"])
        except (KeyError, TypeError, ValueError):
            continue
        if 20 <= lat <= 46 and 122 <= lon <= 154:
            found.append((s, lat, lon))
    if not found:
        raise AddressNotFound(f"駅が見つかりません: {name}駅")
    # 同じ名前の駅が複数あるとき（府中駅は東京・広島・徳島・京都…）は、対象地域（関東）の中心に近い駅を選ぶ
    found.sort(key=lambda f: (f[1] - PREFERRED_CENTER[0]) ** 2 + (f[2] - PREFERRED_CENTER[1]) ** 2)
    best, lat, lon = found[0]
    detail = " ".join(x for x in (best.get("prefecture"), best.get("line")) if x)
    others = tuple(dict.fromkeys(
        " ".join(x for x in (s.get("prefecture"), s.get("line")) if x) for s, _, _ in found[1:]
    ))
    return Place(f"{name}駅", lat, lon, STATION_LEVEL, detail=detail, others=others)
