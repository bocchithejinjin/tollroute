"""Collect and normalize the data for the Kantō routing benchmark."""

import argparse
import csv
import hashlib
import json
import math
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path


ORIGIN = (35.4657, 139.6223)  # 横浜駅
DESTINATION = (35.6896, 139.7006)  # 新宿駅
TARGET_COUNT = 30
STAGES = {"osrm": ("extract", "partition", "customize"), "valhalla": ("admins", "tiles")}
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def metadata(pbf, docker_info):
    with pbf.open("rb") as input_file:
        checksum = hashlib.file_digest(input_file, "sha256").hexdigest()
    return {
        **{key: docker_info[key] for key in ("NCPU", "MemTotal", "OSType", "Architecture", "ServerVersion")},
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "kanto_pbf_bytes": pbf.stat().st_size,
        "kanto_pbf_sha256": checksum,
    }


def distance_km(first, second):
    lat1, lon1 = map(math.radians, first)
    lat2, lon2 = map(math.radians, second)
    a = math.sin((lat2 - lat1) / 2) ** 2
    a += math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(a))


def pick_targets(xml):
    candidates = []
    for node in ET.parse(xml).getroot().iterfind("node"):
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in node.iterfind("tag")}
        name = tags.get("name:ja") or tags.get("name") or ""
        if tags.get("highway") != "motorway_junction" or not name:
            continue
        if re.search(r"ジャンクション|\b(?:JCT|JUNCTION)\b", name, re.IGNORECASE):
            continue
        point = [float(node.attrib["lat"]), float(node.attrib["lon"])]
        if distance_km(ORIGIN, point) <= 120:
            candidates.append({"osm_node_id": int(node.attrib["id"]), "name": name, "lat_lon": point})
    candidates.sort(key=lambda item: (distance_km(ORIGIN, item["lat_lon"]), item["osm_node_id"]))
    selected = []
    for item in candidates:
        if any(
            item["name"] == other["name"] or distance_km(item["lat_lon"], other["lat_lon"]) < 3
            for other in selected
        ):
            continue
        selected.append(item)
        if len(selected) == TARGET_COUNT:
            return selected
    raise ValueError(f"Only {len(selected)} distinct junctions found, expected {TARGET_COUNT}")


def docker_output(*args):
    return subprocess.check_output(["docker", *args], encoding="utf-8").strip()


def usage_bytes(value):
    match = re.fullmatch(r"([\d.]+)\s*(B|[KMGT]iB)", value.split("/")[0].strip())
    if match is None:
        raise ValueError(f"Unknown Docker memory unit: {value}")
    number, unit = match.groups()
    return round(float(number) * 1024 ** ("B", "KiB", "MiB", "GiB", "TiB").index(unit))


def container_state(name):
    return json.loads(docker_output("inspect", "--format", "{{json .State}}", name))


def measure(name, output):
    state = container_state(name)
    samples = []
    with output.with_suffix(".stats.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["utc", "docker_mem_usage", "approx_usage_bytes"])
        while state["Running"]:
            try:
                raw = docker_output("stats", "--no-stream", "--format", "{{.MemUsage}}", name)
            except subprocess.CalledProcessError:
                state = container_state(name)
                if state["Running"]:
                    raise
                break
            if raw and (value := usage_bytes(raw)) > 0:
                writer.writerow([datetime.now(timezone.utc).isoformat(), raw, value])
                stream.flush()
                samples.append(value)
            time.sleep(1)
            state = container_state(name)
    # Docker records the timestamps even for a stage shorter than the first stats sample.
    started = datetime.fromisoformat(state["StartedAt"].replace("Z", "+00:00"))
    finished = datetime.fromisoformat(state["FinishedAt"].replace("Z", "+00:00"))
    result = {
        "elapsed_s": (finished - started).total_seconds(),
        "sampled_peak_bytes": max(samples, default=None),
        "samples": len(samples),
        "exit_code": state["ExitCode"],
        "oom_killed": state["OOMKilled"],
    }
    with output.with_suffix(".log").open("wb") as stream:
        subprocess.run(["docker", "logs", name], stdout=stream, stderr=subprocess.STDOUT, check=True)
    save_json(output.with_suffix(".json"), result)
    if result["exit_code"]:
        raise SystemExit(f"{name} exited with status {result['exit_code']}. See {output}.log.")


def build_summary(engine, folder):
    stages = {
        stage: json.loads((folder / f"{stage}.json").read_text(encoding="utf-8"))
        for stage in STAGES[engine]
    }
    if engine == "osrm":
        paths = list(folder.glob("kanto.osrm.*"))
        if (folder / "kanto.osrm").is_file():
            paths.append(folder / "kanto.osrm")
    else:
        paths = list((folder / "tiles").rglob("*.gph"))
    if not paths:
        raise SystemExit(f"No graph files found in {folder}")
    if engine == "valhalla":
        paths.extend(folder / name for name in ("admin.sqlite", "valhalla.json"))
    peaks = [stage["sampled_peak_bytes"] for stage in stages.values()]
    measurements = {
        "stages": stages,
        "elapsed_s": sum(stage["elapsed_s"] for stage in stages.values()),
        "sampled_peak_bytes": max((peak for peak in peaks if peak is not None), default=None),
        "every_stage_sampled": all(peak is not None for peak in peaks),
        "graph_bytes": sum(path.stat().st_size for path in paths),
    }
    headers = (folder.parent / "japan-headers.txt").read_text(encoding="ascii", errors="replace")
    responses = re.split(r"(?m)^HTTP/\S+ (\d{3})[^\n]*\n", headers)
    length = None
    if len(responses) >= 3 and responses[-2] == "200":
        length = re.search(r"(?im)^content-length:[ \t]*([1-9][0-9]*)[ \t]*$", responses[-1])
    if length:
        environment = json.loads((folder.parent / "environment.json").read_text(encoding="utf-8"))
        japan_pbf_bytes = int(length[1])
        ratio = japan_pbf_bytes / environment["kanto_pbf_bytes"]
        measurements["japan_extrapolation"] = {
            "pbf_bytes": japan_pbf_bytes,
            "pbf_ratio": ratio,
            "elapsed_s": round(measurements["elapsed_s"] * ratio, 3),
            "sampled_peak_bytes": round(max(peaks) * ratio) if all(p is not None for p in peaks) else None,
            "graph_bytes": round(measurements["graph_bytes"] * ratio),
        }
    save_json(folder / "build.json", measurements)


def request(base, endpoint, payload=None, timeout=120):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(base + endpoint, body, {"Content-Type": "application/json"})
    start = time.perf_counter()
    try:
        with HTTP.open(req, timeout=timeout) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as error:
        with error:
            status, raw = error.code, error.read()
    elapsed_ms = (time.perf_counter() - start) * 1000
    return status, raw, elapsed_ms


def wait_for_server(base, endpoint):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            status, _, _ = request(base, endpoint, timeout=3)
            if status == 200:
                return
        except (OSError, ValueError):
            pass
        time.sleep(1)
    raise SystemExit(f"Service did not become ready at {base}{endpoint}")


def osrm_coordinate(point):
    return f"{point[1]},{point[0]}"


def valhalla_location(point, exclude_toll=False):
    return {"lat": point[0], "lon": point[1], "search_filter": {"exclude_toll": exclude_toll}}


def osrm_requests(points):
    route_points = ";".join(map(osrm_coordinate, (ORIGIN, DESTINATION)))
    route = "/route/v1/driving/" + route_points + "?steps=true&overview=false"
    table_points = ";".join(map(osrm_coordinate, [ORIGIN, *points]))
    indices = ";".join(map(str, range(1, len(points) + 1)))
    table = f"/table/v1/driving/{table_points}?sources=0&destinations={indices}&exclude=toll"
    return {
        "route-allow": (route, None),
        "route-exclude": (route + "&exclude=toll", None),
        "matrix-exclude": (table, None),
    }


def valhalla_requests(points):
    allow = {"costing": "auto", "units": "kilometers"}
    exclude = {**allow, "costing_options": {"auto": {"exclude_tolls": True}}}
    return {
        "route-allow": ("/route", {**allow, "locations": [
            valhalla_location(ORIGIN), valhalla_location(DESTINATION)
        ]}),
        "route-exclude": ("/route", {**exclude, "locations": [
            valhalla_location(ORIGIN, True), valhalla_location(DESTINATION, True)
        ]}),
        "matrix-exclude": ("/sources_to_targets", {
            **exclude, "verbose": True, "sources": [valhalla_location(ORIGIN, True)],
            "targets": [valhalla_location(point, True) for point in points],
        }),
    }


def route_result(engine, body):
    if engine == "osrm":
        route = body["routes"][0]
        has_toll = any(
            "toll" in intersection.get("classes", [])
            for leg in route["legs"]
            for step in leg["steps"]
            for intersection in step["intersections"]
            if "out" in intersection
        )
        return {"duration_s": route["duration"], "distance_km": route["distance"] / 1000,
                "toll_class_detected": has_toll}
    trip = body["trip"]["summary"]
    return {"duration_s": trip["time"], "distance_km": trip["length"],
            "toll_class_detected": trip["has_toll"]}


def matrix_result(engine, body, targets):
    if engine == "osrm":
        durations = body["durations"][0]
    else:
        row, = body["sources_to_targets"]
        indexed = {item["to_index"]: item["time"] for item in row if item["from_index"] == 0}
        durations = [indexed[index] for index in range(len(targets))]
    if len(durations) != len(targets):
        raise ValueError(f"Expected {len(targets)} durations, got {len(durations)}")
    return [{**target, "duration_s": duration} for target, duration in zip(targets, durations)]


def query(engine, folder):
    targets = json.loads((folder / "targets.json").read_text(encoding="utf-8"))
    points = [target["lat_lon"] for target in targets]
    if engine == "osrm":
        base = "http://127.0.0.1:5000"
        health = "/nearest/v1/driving/" + osrm_coordinate(ORIGIN)
        requests = osrm_requests(points)
    else:
        base = "http://127.0.0.1:8002"
        health = "/status"
        requests = valhalla_requests(points)
    wait_for_server(base, health)
    output = folder / engine
    results = {}
    for name, (endpoint, payload) in requests.items():
        result = {}
        try:
            status, raw, latency = request(base, endpoint, payload)
            (output / f"{name}.response.json").write_bytes(raw)
            result.update(http_status=status, latency_ms=round(latency, 3))
            if status != 200:
                raise ValueError(f"HTTP {status}")
            body = json.loads(raw)
            if name.endswith("-exclude") and any(
                warning.get("code") == 208 for warning in body.get("warnings", [])
            ):
                raise ValueError("Valhalla reported that hard exclusions were disabled")
            if name.startswith("route"):
                result.update(route_result(engine, body))
                if name == "route-exclude" and result["toll_class_detected"]:
                    raise ValueError("Toll road detected on excluded route")
            else:
                result["destinations"] = matrix_result(engine, body, targets)
        except (OSError, ValueError, KeyError, IndexError, TypeError) as error:
            result["error"] = str(error)
        results[name] = result
    save_json(output / "queries.json", results)
    if any("error" in result for result in results.values()):
        raise SystemExit(f"Some {engine} queries failed. See {output / 'queries.json'}.")


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("metadata").add_argument("pbf", type=Path)
    commands.add_parser("targets").add_argument("xml", type=Path)
    measurement = commands.add_parser("measure")
    measurement.add_argument("container")
    measurement.add_argument("output", type=Path)
    for command in ("build-summary", "query"):
        action = commands.add_parser(command)
        action.add_argument("engine", choices=STAGES)
        action.add_argument("folder", type=Path)
    args = parser.parse_args()

    if args.command in ("metadata", "targets"):
        sys.stdout.reconfigure(encoding="utf-8")
        value = metadata(args.pbf, json.load(sys.stdin)) if args.command == "metadata" else pick_targets(args.xml)
        print(json.dumps(value, indent=2, ensure_ascii=False))
    elif args.command == "measure":
        measure(args.container, args.output)
    elif args.command == "build-summary":
        build_summary(args.engine, args.folder)
    else:
        query(args.engine, args.folder)


if __name__ == "__main__":
    main()
