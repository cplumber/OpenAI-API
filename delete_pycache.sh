#!/bin/sh
# delete all __pycache__ dirs recursively

find . -type d -name "__pycache__" -print -exec rm -rf {} +
