# Mr. Ellenbogen's Linux Lab Updates

Updates for the school Linux lab laptops. Each laptop's **lab updater** checks this repo
whenever it gets online (and every 30 minutes), then installs any new updates found in `updates/`.

* `main` = what every lab laptop installs
* `testing` = what the test laptop installs first

Every commit laptops install must be **signed with the lab signing key**. Laptops reject anything else,
including commits made or merged on github.com. Make all changes from the teacher's computer.
