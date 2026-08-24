#!/bin/bash
exit_code=0
for path in $(btrfs filesystem show | awk '/ path /{print $NF}')
do
  echo "Checking health for $path..."
  result=$(btrfs device stats "$path")
  echo "$result"
  regex='\.(.*)_errs(\s*)[1-9]'
  [[ "$result" =~ $regex ]] && echo "Errors found!" && exit_code=1;
done
exit $exit_code
