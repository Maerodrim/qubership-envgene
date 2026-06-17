#!/bin/bash
set -euxo pipefail

cd "${CI_PROJECT_DIR}"

export PYTHONPATH=${CI_PROJECT_DIR}
export FULL_ENV_NAME="sdp-dev/env-1"
export BG_STATE=""

rm -f junit.xml junit_*.xml

run_pytest_suite() {
  local name="$1"
  local dir="$2"
  (
    cd "${CI_PROJECT_DIR}/${dir}"
    pytest --capture=no -W ignore::DeprecationWarning --junitxml="${CI_PROJECT_DIR}/junit.xml"
  )
  mv "${CI_PROJECT_DIR}/junit.xml" "${CI_PROJECT_DIR}/junit_${name}.xml"
}

run_pytest_suite envgenehelper python/envgene/envgenehelper
run_pytest_suite pipegene build_pipegene/scripts
run_pytest_suite artifact_searcher python/artifact-searcher/artifact_searcher
run_pytest_suite bg_manage scripts/bg_manage
run_pytest_suite build_env_sd               scripts/build_env/tests/sd
run_pytest_suite build_env_env_template     scripts/build_env/tests/env-template
run_pytest_suite build_env_env_build        scripts/build_env/tests/env-build
run_pytest_suite build_env_app_reg_defs     scripts/build_env/tests/app_reg_defs
run_pytest_suite build_env_namespace_filter scripts/build_env/tests/namespace_filter
run_pytest_suite build_env_inventory        scripts/build_env/tests/env_inventory_generation
run_pytest_suite cred_rotation creds_rotation/scripts
run_pytest_suite build_effective_set_generator build_effective_set_generator/scripts

junitparser merge junit_*.xml junit.xml
