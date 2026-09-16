#!/bin/sh
set -eu

# Railway mounts a Volume after the image is built, so image-time ownership
# settings do not apply to the mounted directory.
for directory in /data /app/data; do
    mkdir -p "$directory"
    chown -R streak:streak "$directory"
done

exec gosu streak "$@"
