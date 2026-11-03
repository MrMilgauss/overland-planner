#!/usr/bin/env bash
# CI job 7 (step 01-09, D170): runs the external pytest selection (e.g. "compose or security") against the packaged
# planner with --run-external and the enabled slices in $PENDING_FLAGS.
# pytest exits 5 when the selection collects no test. That is accepted only while PENDING_FLAGS is empty, i.e. no
# slice is enabled yet and an empty selection is the expected state; once a slice is enabled it must select tests.
#
# Usage: pytest-selection.sh MARKER_EXPRESSION
set -uo pipefail

expression="${1:?usage: pytest-selection.sh MARKER_EXPRESSION}"
pending="${PENDING_FLAGS:-}"
summary="${GITHUB_STEP_SUMMARY:-/dev/null}"

# shellcheck disable=SC2086 # PENDING_FLAGS is a list of flags
uv run pytest -q -rs --run-external $pending -m "$expression"
status=$?

case "$status" in
  0) echo "pytest -m \"${expression}\": passed (PENDING_FLAGS: '${pending}')" >> "$summary" ;;
  5)
    if [ -z "${pending// /}" ]; then
      echo "pytest -m \"${expression}\": no test collected, empty by design while no slice is enabled in PENDING_FLAGS (exit 5 accepted)" | tee -a "$summary"
      exit 0
    fi
    echo "pytest -m \"${expression}\": selected no test although PENDING_FLAGS is '${pending}'" | tee -a "$summary" >&2
    ;;
  *) echo "pytest -m \"${expression}\": failed with exit code ${status}" >> "$summary" ;;
esac
exit "$status"
