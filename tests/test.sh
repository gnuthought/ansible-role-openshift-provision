#!/bin/bash

set -e
set -x

for PLAYBOOK in test-*.yml; do
  if [ -s $PLAYBOOK ]; then
    ansible-playbook $PLAYBOOK
  fi
done
