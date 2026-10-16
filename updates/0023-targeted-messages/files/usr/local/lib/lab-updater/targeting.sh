# Targeting helpers for lab updates (installed by update 0023).
# In an update's install.sh, after sourcing $LAB_UPDATER_HELPERS:
#     source /usr/local/lib/lab-updater/targeting.sh
#
#   only_on_laptops lab-jq8fzm2 lab-5cd137g4vb
#       Stops the update (as done, without changes) on every other laptop.
#
#   for account in $(student_accounts 349681030 123456789); do ...; done
#       Prints the tdsb-<ID> accounts that exist on THIS laptop (none = nothing).
#
# Updates run once per laptop: a laptop or student added later does not get
# an earlier targeted fix. Send another update if that's needed.

only_on_laptops() {
    local me name
    me="$(hostname)"
    for name in "$@"; do
        [ "${name,,}" = "${me,,}" ] && return 0
    done
    say "not for this laptop ($me); nothing to do"
    exit 0
}

student_accounts() {
    local id account
    for id in "$@"; do
        account="tdsb-${id,,}"
        getent passwd "$account" >/dev/null && echo "$account"
    done
    return 0
}
