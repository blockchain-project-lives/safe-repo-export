#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

main() {
  local script_dir version message
  if [[ $# -eq 0 || $1 == -h || $1 == --help ]]; then
    printf 'Usage: ./commit_and_tag.sh vX.Y.Z [MESSAGE] [--push] [--dry-run]\n'
    return 0
  fi
  script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
  version=${1#v}
  shift
  message="Release v$version"
  if [[ $# -gt 0 && $1 != --* ]]; then
    message=$1
    shift
  fi
  exec bash "$script_dir/bump_version.sh" "$version" --tag --message "$message" "$@"
}

main "$@"
