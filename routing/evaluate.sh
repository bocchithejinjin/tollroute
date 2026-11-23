#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# Keep Linux container paths intact when calling docker.exe from Git Bash.
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'

case "${1:-all}" in
  all) engines=(osrm valhalla) ;;
  osrm|valhalla) engines=("$1") ;;
  *) printf 'Usage: bash routing/evaluate.sh [osrm|valhalla|all]\n' >&2; exit 2 ;;
esac

if command -v python3 >/dev/null && python3 -c 'import sys' 2>/dev/null; then
  python_cmd=(python3)
elif command -v python >/dev/null && python -c 'import sys' 2>/dev/null; then
  python_cmd=(python)
else
  python_cmd=(py -3)
fi

mkdir -p data/osm data/routing
pbf=data/osm/kanto-latest.osm.pbf
kanto_url=https://download.geofabrik.de/asia/japan/kanto-latest.osm.pbf
japan_url=https://download.geofabrik.de/asia/japan-latest.osm.pbf
work=$(mktemp -d data/routing/kanto-XXXXXXXX)
export ROUTING_RUN="../$work"
printf 'Results: %s\n' "$work"

curl --fail --silent --show-error --location --head --max-time 30 "$japan_url" \
  > "$work/japan-headers.txt" || printf 'Japan HEAD request failed\n' >&2
if [[ ! -s "$pbf" ]]; then
  part=$(mktemp data/osm/kanto-XXXXXXXX.part)
  trap 'rm -f -- "$part"' EXIT
  curl --fail --show-error --location --retry 2 --connect-timeout 15 \
    --output "$part" "$kanto_url"
  mv -- "$part" "$pbf"
  trap - EXIT
fi

docker info --format '{{json .}}' | "${python_cmd[@]}" routing/evaluate.py metadata "$pbf" \
  > "$work/environment.json"
ncpu=$("${python_cmd[@]}" -c 'import json,sys; print(json.load(open(sys.argv[1]))["NCPU"])' "$work/environment.json")
export ROUTING_THREADS=${ROUTING_THREADS:-$(( ncpu < 4 ? ncpu : 4 ))}
if [[ ! "$ROUTING_THREADS" =~ ^[1-9][0-9]*$ ]]; then
  printf 'ROUTING_THREADS must be a positive integer\n' >&2
  exit 2
fi
printf '%s\n' "$ROUTING_THREADS" > "$work/threads.txt"

project="routing-${work##*/}"
project=${project,,}
engine=
build_container=
compose() {
  docker compose --project-name "$project-$engine" -f "routing/compose.$engine.yaml" "$@"
}
cleanup() {
  if [[ -n "$build_container" ]]; then
    docker rm -f "$build_container" >/dev/null 2>&1 || true
  fi
  if [[ -n "$engine" ]]; then
    compose logs --no-color server > "$work/$engine/server.log" 2>&1 || true
    compose down >/dev/null || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

input=/input/kanto-latest.osm.pbf
osm_dir=$("${python_cmd[@]}" -c 'from pathlib import Path; print(Path("data/osm").resolve())')
docker run --rm --mount "type=bind,source=$osm_dir,target=/input,readonly" \
  --entrypoint osmium iboates/osmium:1.19.0 tags-filter --omit-referenced \
  --output-format=osm "$input" n/highway=motorway_junction > "$work/junctions.osm"
"${python_cmd[@]}" routing/evaluate.py targets "$work/junctions.osm" > "$work/targets.json"

measure() {
  local stage=$1
  shift
  build_container="$project-$engine-$stage"
  printf 'Building %s / %s\n' "$engine" "$stage"
  compose run --no-deps --detach -T --name "$build_container" builder "$@" >/dev/null
  "${python_cmd[@]}" routing/evaluate.py measure "$build_container" "$work/$engine/$stage"
  docker rm "$build_container" >/dev/null
  build_container=
}

query_failed=0
for engine in "${engines[@]}"; do
  mkdir -p "$work/$engine"
  compose pull
  if [[ "$engine" == osrm ]]; then
    measure extract osrm-extract --threads "$ROUTING_THREADS" --profile /opt/car.lua \
      --output /graph/kanto.osrm "$input"
    measure partition osrm-partition --threads "$ROUTING_THREADS" /graph/kanto.osrm
    measure customize osrm-customize --threads "$ROUTING_THREADS" /graph/kanto.osrm
  else
    compose run --rm --no-deps -T builder valhalla_build_config \
      --mjolnir-tile-dir /graph/tiles --mjolnir-tile-extract /graph/tiles.tar \
      --mjolnir-admin /graph/admin.sqlite --mjolnir-include-bicycle false \
      --mjolnir-include-pedestrian false --service-limits-allow-hard-exclusions true \
      --service-limits-auto-max-locations 50 --output /graph/valhalla.json
    measure admins valhalla_build_admins -c /graph/valhalla.json "$input"
    measure tiles valhalla_build_tiles -c /graph/valhalla.json -j "$ROUTING_THREADS" "$input"
  fi
  "${python_cmd[@]}" routing/evaluate.py build-summary "$engine" "$work/$engine"
  compose up -d --no-deps server
  "${python_cmd[@]}" routing/evaluate.py query "$engine" "$work" || query_failed=1
  cleanup
  engine=
done
exit "$query_failed"
