#!/bin/sh
# Keeps frontend/dist (served by Django on :8000) in step with the sources. Compares modification times instead of
# file change events: bind mounts from macOS (Colima) deliver no change events into the container.
set -e
until [ -x node_modules/.bin/vite ]; do sleep 2; done  # the frontend service installs the packages
while true; do
  if [ ! -f dist/index.html ] || [ -n "$(find src public index.html vite.config.ts -newer dist/index.html -print -quit 2>/dev/null)" ]; then
    node_modules/.bin/vite build --logLevel warn || true  # a broken edit must not stop the loop
  fi
  sleep 2
done
