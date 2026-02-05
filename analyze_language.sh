#!/usr/bin/env bash

find . -type f | sed 's/.*\.//' | sort | uniq -c | sort -rn