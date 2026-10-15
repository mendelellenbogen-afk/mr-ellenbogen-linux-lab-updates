#!/bin/bash
# Copy a Clonezilla image folder from one USB stick to others, then compare
# every byte of each copy with the original.
#
# Easiest (on any Ubuntu machine with the sticks plugged in and opened in Files):
#   sudo bash copy-image.sh --all IMAGE_NAME
#     source  = the mounted USB drive that has IMAGE_NAME
#     targets = every other mounted ext4 USB drive labelled CLONEZILLA-IMG*
# Or explicitly:
#   sudo bash copy-image.sh SOURCE_MOUNT TARGET_MOUNT IMAGE_NAME
#
# Never deletes anything except its own unfinished IMAGE.partial copy. Skips a target that already has the image or lacks
# space. Each finished target is unmounted, so it is safe to unplug.
set -uo pipefail

[ "$EUID" -eq 0 ] || { echo "Run with sudo."; exit 1; }

copy_one() {   # SOURCE_DIR TARGET_ROOT -> 0 ok, 1 failed, 2 skipped
    local source_dir="$1" target_root="$2" name target_dir need free file bad=0
    name="$(basename "$source_dir")"
    target_dir="$target_root/$name"
    echo
    echo "=== Target: $target_root ($(findmnt -no SOURCE "$target_root"))"

    if [ -e "$target_dir" ]; then echo "Already has $name. Skipped."; return 2; fi
    if [ -e "$target_dir.partial" ]; then
        echo "Removing an unfinished earlier copy ($name.partial)..."
        rm -rf "$target_dir.partial"; sync
    fi
    need=$(du -sb "$source_dir" | cut -f1)
    free=$(df -B1 --output=avail "$target_root" | tail -n 1)
    echo "Image: $((need / 1000000000)) GB. Free on this stick: $((free / 1000000000)) GB."
    if [ "$free" -le $((need + 500000000)) ]; then
        echo "Not enough space. Skipped (nothing changed)."; return 2
    fi

    echo ">>> Copying..."
    rsync -a --info=progress2 "$source_dir/" "$target_dir.partial/" || { echo "COPY FAILED"; return 1; }
    sync
    mv "$target_dir.partial" "$target_dir"
    sync

    echo ">>> Comparing every file with the original..."
    { echo 3 > /proc/sys/vm/drop_caches; } 2>/dev/null || true   # read back from the stick, not memory
    for file in "$source_dir"/*; do
        if cmp -s "$file" "$target_dir/$(basename "$file")"; then
            echo "OK   $(basename "$file")"
        else
            echo "BAD  $(basename "$file")"; bad=1
        fi
    done
    [ "$bad" = 0 ] || { echo "THIS COPY IS BAD. Do not use this stick for $name."; return 1; }

    umount "$target_root" && echo "Identical copy. This stick is unmounted and safe to unplug."
    return 0
}

if [ "${1:-}" = "--all" ]; then
    image="${2:?usage: copy-image.sh --all IMAGE_NAME}"
    source_dir=""
    targets=()
    while read -r target fstype label; do
        case "$target" in /run/media/*|/media/*) ;; *) continue ;; esac
        if [ -f "$target/$image/clonezilla-img" ]; then
            source_dir="$target/$image"
        elif [ "$fstype" = "ext4" ] && [[ "$label" == CLONEZILLA-IMG* ]]; then
            targets+=("$target")
        fi
    done < <(findmnt -rn -o TARGET,FSTYPE,LABEL)

    [ -n "$source_dir" ] || { echo "No mounted drive has $image. Open the sticks in Files first."; exit 1; }
    echo "Source: $source_dir ($(findmnt -no SOURCE "$(dirname "$source_dir")"))"
    [ "${#targets[@]}" -gt 0 ] || { echo "No other CLONEZILLA-IMG sticks are mounted. Open them in Files first."; exit 1; }
    echo "Targets: ${targets[*]}"

    status=0
    for target in "${targets[@]}"; do
        copy_one "$source_dir" "$target"
        [ $? -eq 1 ] && status=1
    done
    echo
    if [ "$status" = 0 ]; then echo "ALL DONE. The source stick is still mounted; eject it in Files before unplugging."
    else echo "DONE WITH ERRORS (see above)."; fi
    exit "$status"
fi

source_dir="${1:?source mount}/${3:?image name}"
[ -f "$source_dir/clonezilla-img" ] || { echo "Not a Clonezilla image: $source_dir"; exit 1; }
mountpoint -q "$2" || { echo "Not a mounted drive: $2"; exit 1; }
copy_one "$source_dir" "$2"
