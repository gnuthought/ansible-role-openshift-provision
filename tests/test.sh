#!/bin/bash

set -e
set -x

for PLAYBOOK in test-*.yml; do
  ansible-playbook $PLAYBOOK
done
