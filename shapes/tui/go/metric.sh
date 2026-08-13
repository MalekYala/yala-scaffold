#!/usr/bin/env sh
if /app/qa-check >/dev/null 2>&1; then
    echo 1.0
else
    echo 0.0
fi
