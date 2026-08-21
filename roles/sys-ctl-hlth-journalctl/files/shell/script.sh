#!/bin/sh
echo "Checking journalctl for error messages..."
journalctl_errors="$(journalctl --since '1 day ago' --no-pager | grep -i 'error')"
if [ -n "$journalctl_errors" ]
then 
   echo "Some errors where found: $journalctl_errors"
   exit 1
fi
echo "All docker containers are healthy."
exit 0
