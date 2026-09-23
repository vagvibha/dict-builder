#!/usr/bin/env bash
# Builds every dictionary for a content workspace.
#
# Usage: build_dictionaries.sh [--workspace DIR]   (default: current dir)
#
# The workspace must contain content/meta.yaml (see plan.py for the
# format). Everything the build produces lives in the workspace:
#   external/<source>/        fetched external sources (gitignore this)
#   build/stardict/<id>/      StarDict output
#   build/sources.txt         "<source> <repo> <sha>" for each fetched source
#   build/changed_dictionaries.txt
#   stats/<id>.stats          per-dictionary stats (commit these)
#
# Versioning: a dictionary gets a new version (the .ifo 'description') only
# if its content differs from the previously published copy in
# PUBLISHED_DIR (default: <workspace>/dictionaries). Unchanged dictionaries
# reuse the published files byte-for-byte.
#
# Env: PUBLISHED_DIR, SKIP_FETCH=1 (build from already-fetched sources).
set -euo pipefail

CODE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPTS="${CODE_ROOT}/scripts"

WORKSPACE="${PWD}"
while [ $# -gt 0 ]; do
    case "$1" in
        --workspace) WORKSPACE="$2"; shift 2 ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done
WORKSPACE="$(cd "${WORKSPACE}" && pwd)"

if [ ! -f "${WORKSPACE}/content/meta.yaml" ]; then
    echo "❌ ${WORKSPACE}/content/meta.yaml not found - is --workspace right?" >&2
    exit 2
fi

BUILD_DIR="${WORKSPACE}/build"
STARDICT_DIR="${BUILD_DIR}/stardict"
STATS_DIR="${WORKSPACE}/stats"
PUBLISHED_DIR="${PUBLISHED_DIR:-${WORKSPACE}/dictionaries}"

rm -rf "${STARDICT_DIR}"
mkdir -p "${BUILD_DIR}" "${STARDICT_DIR}" "${STATS_DIR}"

if [ "${SKIP_FETCH:-0}" != "1" ]; then
    python3 "${SCRIPTS}/plan.py" fetch --workspace "${WORKSPACE}" \
        --sources-file "${BUILD_DIR}/sources.txt"
fi

# "<id>\t<dir>\t<meta-defaults-json>" per dictionary. Parallel arrays and a
# plain read loop (no mapfile / assoc arrays) - macOS ships bash 3.2.
plan="$(python3 "${SCRIPTS}/plan.py" list --workspace "${WORKSPACE}")"
ids=(); dirs=(); defaults=()
while IFS=$'\t' read -r id dir meta; do
    if [ -n "${id}" ]; then ids+=("${id}"); dirs+=("${dir}"); defaults+=("${meta}"); fi
done <<< "${plan}"

# Drop stats for dictionaries that are no longer built (git history keeps them).
for f in "${STATS_DIR}"/*.stats; do
    [ -e "${f}" ] || continue
    keep=0
    for id in "${ids[@]}"; do
        if [ "${f}" = "${STATS_DIR}/${id}.stats" ]; then keep=1; fi
    done
    if [ ${keep} -eq 0 ]; then echo "Removing stale ${f##*/}"; rm -f "${f}"; fi
done

BUILD_TIME=$(TZ="America/Los_Angeles" date "+%Y%m%d-%H%M")
VERSION="${BUILD_TIME}:PST"

# Step 1: Generate tabfile output for each dictionary.
i=0
while [ $i -lt ${#ids[@]} ]; do
    id="${ids[$i]}"
    echo "Building ${id} ..."
    python3 "${SCRIPTS}/createDictionary.py" \
        --dict-dir "${dirs[$i]}" \
        --meta-defaults "${defaults[$i]}" \
        -o "${BUILD_DIR}/temp_${id}.tsv" \
        --stats-file "${STATS_DIR}/${id}.stats" \
        -s \
        -v "${VERSION}"
    i=$((i + 1))
done

# Step 2: Convert each tabfile to StarDict, then keep the published copy
# if nothing really changed.
changed=""
for id in "${ids[@]}"; do
    tsv_file="${BUILD_DIR}/temp_${id}.tsv"
    name_file="${BUILD_DIR}/temp_${id}.name"
    target_dir="${STARDICT_DIR}/${id}"
    published="${PUBLISHED_DIR}/${id}"

    [ -f "${tsv_file}" ] || continue

    echo "Creating Stardict for ${id} using PyGlossary..."
    python3 "${SCRIPTS}/build_dict.py" \
        "${tsv_file}" "${target_dir}" "$(cat "${name_file}")" "${VERSION}"
    rm -f "${tsv_file}" "${name_file}"

    if python3 "${SCRIPTS}/compare_stardict.py" "${published}" "${target_dir}"; then
        echo "  ${id}: unchanged, keeping published version"
        rm -rf "${target_dir}"
        cp -a "${published}" "${target_dir}"
    else
        echo "  ${id}: changed -> ${VERSION}"
        changed="${changed}${id}"$'\n'
    fi
done

printf '%s' "${changed}" > "${BUILD_DIR}/changed_dictionaries.txt"
echo "Changed dictionaries: $(echo ${changed:-none})"
