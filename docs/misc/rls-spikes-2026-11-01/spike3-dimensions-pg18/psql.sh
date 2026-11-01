#!/bin/bash
r=$1; shift
exec docker exec -i -e PGPASSWORD=spike spike3-rls-pg psql -v ON_ERROR_STOP=1 -h 127.0.0.1 -U $r -d spike "$@"
