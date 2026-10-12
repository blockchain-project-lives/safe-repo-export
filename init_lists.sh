#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 027

main() {
  local script_dir python_bin candidate
  script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
  python_bin=${SAFE_REPO_EXPORT_PYTHON:-}
  if [[ -n $python_bin ]]; then
    if ! "$python_bin" -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
      printf 'ERROR: SAFE_REPO_EXPORT_PYTHON must point to Python 3.10 or newer.\n' >&2
      return 2
    fi
  else
    for candidate in python3 python; do
      if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
        python_bin=$candidate
        break
      fi
    done
  fi
  if [[ -z $python_bin ]]; then
    printf 'ERROR: Python 3.10 or newer is required.\n' >&2
    return 2
  fi
  exec "$python_bin" "$script_dir/scripts/init_lists.py" "$@"
}

main "$@"
