Each update is a folder named `NNNN-short-name` (4 digits, then lowercase letters, digits, dashes),
for example `0001-fix-suspend-wifi`. Laptops apply updates once each, in number order.

A folder must contain `install.sh`. Anything else in the folder (files to copy, notes) is up to the update.

## Updates for particular laptops or students (after 0023)

```bash
source "$LAB_UPDATER_HELPERS"
source /usr/local/lib/lab-updater/targeting.sh

only_on_laptops lab-jq8fzm2 lab-5cd137g4vb      # every other laptop stops here (counted as done)

for account in $(student_accounts 349681030); do  # tdsb-<ID> accounts that exist on this laptop
    say "fixing $account"
done
```

Updates run once per laptop. A laptop or student account added later does not get an earlier targeted fix; publish another update if it needs one.
