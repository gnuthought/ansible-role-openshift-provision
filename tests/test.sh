#!/bin/bash

START_AT="$1"

set -e
set -x

for PLAYBOOK in test-*.yml; do
  if [[ -s $PLAYBOOK && ! $PLAYBOOK < "$START_AT" ]]; then
    ansible-playbook $PLAYBOOK
  fi
done
