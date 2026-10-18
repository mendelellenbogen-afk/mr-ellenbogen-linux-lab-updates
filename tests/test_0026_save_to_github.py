#!/usr/bin/env python3
"""Tests for 0026-save-to-github: the "Save to GitHub" app.
Temp folders only; no network, no root. GitHub is a fake `gh` plus bare git
repos in a temp folder (git's url.insteadOf makes https://github.com/... point
there). The window runs on a private Broadway display when gtk4-broadwayd is
installed (never the user's screen).

    python3 -I update-repo/tests/test_0026_save_to_github.py
"""

import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
UPDATE = os.path.join(HERE, "..", "updates", "0026-save-to-github")
APP = os.path.join(UPDATE, "files", "usr", "local", "lib", "lab-github", "save-to-github.py")

FAKE_GH = textwrap.dedent('''\
    #!/usr/bin/env python3
    # A stand-in for the GitHub CLI. State lives in $FAKE_GH_DIR:
    #   token (signed in), remotes/<owner>/<name>.git (bare repos), calls.log
    import json, os, subprocess, sys, time
    state = os.environ["FAKE_GH_DIR"]
    remotes = os.path.join(state, "remotes")
    login = os.environ.get("FAKE_GH_LOGIN", "student1")
    args = sys.argv[1:]
    with open(os.path.join(state, "calls.log"), "a") as log:
        log.write(" ".join(args) + "\\n")
    token = os.path.join(state, "token")
    def fail(text):
        sys.stderr.write(text + "\\n"); sys.exit(1)
    def online():
        if os.path.exists(os.path.join(state, "offline")):
            fail("error connecting to api.github.com")
    if args[:2] == ["auth", "token"]:
        sys.exit(0 if os.path.exists(token) else 1)
    if args[:2] == ["auth", "login"]:
        assert "--web" in args and "--insecure-storage" in args, args
        print(); print("! First copy your one-time code: AB12-CD34", flush=True)
        print("Open this URL to continue in your web browser: https://github.com/login/device", flush=True)
        time.sleep(float(os.environ.get("FAKE_GH_LOGIN_WAIT", "0.3")))
        open(token, "w").write("gho_fake")
        sys.exit(0)
    if args[:2] == ["auth", "setup-git"]:
        open(os.path.join(state, "setup-git"), "w").write("yes")
        sys.exit(0)
    if args[:2] == ["auth", "logout"]:
        os.path.exists(token) and os.remove(token)
        sys.exit(0)
    if not os.path.exists(token):
        fail("To get started with GitHub CLI, please run:  gh auth login")
    online()
    if args == ["api", "user"]:
        print(json.dumps({"login": login, "id": 4242, "name": "Student One"}))
        sys.exit(0)
    if args[:2] == ["repo", "view"]:
        sys.exit(0 if os.path.isdir(os.path.join(remotes, args[2] + ".git")) else 1)
    if args[:2] == ["repo", "create"]:
        name = args[2]
        assert "--private" in args, args
        source = args[args.index("--source") + 1]
        bare = os.path.join(remotes, login, name + ".git")
        os.makedirs(bare)
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", bare], check=True)
        open(bare + ".private", "w").write("yes")
        url = f"https://github.com/{login}/{name}.git"
        subprocess.run(["git", "-C", source, "remote", "add", "origin", url], check=True)
        subprocess.run(["git", "-C", source, "push", "-q", "-u", "origin", "HEAD"], check=True)
        print(f"https://github.com/{login}/{name}")
        sys.exit(0)
    if args[:2] == ["api", "--paginate"]:
        for owner in sorted(os.listdir(remotes)) if os.path.isdir(remotes) else []:
            for repo in sorted(os.listdir(os.path.join(remotes, owner))):
                if repo.endswith(".git"):
                    name = repo[:-4]
                    print(json.dumps({"full_name": f"{owner}/{name}", "name": name, "private": True,
                                      "clone_url": f"https://github.com/{owner}/{name}.git",
                                      "html_url": f"https://github.com/{owner}/{name}"}))
        sys.exit(0)
    fail("fake gh: unexpected " + " ".join(args))
''')


def load_app():
    loader = importlib.machinery.SourceFileLoader("save_to_github", APP)
    spec = importlib.util.spec_from_loader("save_to_github", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class Lab(unittest.TestCase):
    """Each test gets fresh 'laptop' homes, a fake GitHub and a git config."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.state = os.path.join(self.dir, "github")
        os.makedirs(os.path.join(self.state, "remotes"))
        gh = os.path.join(self.dir, "gh")
        with open(gh, "w") as handle:
            handle.write(FAKE_GH)
        os.chmod(gh, 0o755)
        self.gitconfig = os.path.join(self.dir, "gitconfig")
        with open(self.gitconfig, "w") as handle:
            handle.write(f'[url "file://{self.state}/remotes/"]\n\tinsteadOf = https://github.com/\n'
                         '[init]\n\tdefaultBranch = main\n[protocol "file"]\n\tallow = always\n')
        self.saved_env = dict(os.environ)
        os.environ.update(LAB_GITHUB_GH=gh, FAKE_GH_DIR=self.state, GIT_CONFIG_GLOBAL=self.gitconfig,
                          GIT_CONFIG_NOSYSTEM="1", HOME=self.dir)
        self.app = load_app()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.saved_env)
        shutil.rmtree(self.dir)

    # helpers
    def home(self, name="laptop1"):
        path = os.path.join(self.dir, name)
        for folder in ("CS/Python", "CS/Java", "CS/C++", "CS/JavaFX"):
            os.makedirs(os.path.join(path, folder), exist_ok=True)
        return path

    def write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write(text)

    def sign_in(self):
        with open(os.path.join(self.state, "token"), "w") as handle:
            handle.write("gho_fake")
        user = self.app.finish_sign_in()
        return user

    def remote_files(self, owner, name, branch="main"):
        bare = os.path.join(self.state, "remotes", owner, name + ".git")
        out = subprocess.run(["git", "-C", bare, "ls-tree", "-r", "--name-only", branch],
                             capture_output=True, text=True, check=True).stdout
        return sorted(out.split())

    def remote_show(self, owner, name, spec):
        bare = os.path.join(self.state, "remotes", owner, name + ".git")
        return subprocess.run(["git", "-C", bare, "show", spec], capture_output=True, text=True, check=True).stdout


class FindingProjects(Lab):
    def test_usual_folders_and_other_git_projects(self):
        home = self.home()
        self.write(f"{home}/CS/Python/hello.py", "print('hi')\n")            # loose file → the folder itself
        self.write(f"{home}/CS/Java/Game/src/Main.java", "class Main {}\n")
        os.makedirs(f"{home}/CS/Java/EmptyOne")                               # empty → not listed
        self.write(f"{home}/IdeaProjects/App/src/A.java", "class A {}\n")
        os.makedirs(f"{home}/IdeaProjects/App/.git")
        self.write(f"{home}/Desktop/robot/robot.ino", "void setup(){}\n")
        os.makedirs(f"{home}/Desktop/robot/.git")
        os.makedirs(f"{home}/.cache/thing/.git")                              # hidden → not listed
        os.makedirs(f"{home}/snap/firefox/x/.git")                            # snap → not listed
        found = [os.path.relpath(path, home) for path in self.app.find_projects(home)]
        self.assertEqual(sorted(found), ["CS/Java/Game", "CS/Python", "Desktop/robot", "IdeaProjects/App"])

    def test_a_folder_that_is_a_project_hides_its_subfolders(self):
        home = self.home()
        self.write(f"{home}/CS/Python/a/one.py", "1\n")
        self.write(f"{home}/CS/Python/b/two.py", "2\n")
        os.makedirs(f"{home}/CS/Python/.git")
        found = [os.path.relpath(path, home) for path in self.app.find_projects(home)]
        self.assertEqual(found, ["CS/Python"])

    def test_names(self):
        home = "/home/tdsb-1"
        self.assertEqual(self.app.repo_name(f"{home}/CS/C++", home), "CS-Cpp")
        self.assertEqual(self.app.repo_name(f"{home}/CS/Python", home), "CS-Python")
        self.assertEqual(self.app.repo_name(f"{home}/IdeaProjects/My Game!", home), "My-Game")
        self.assertEqual(self.app.repo_name(f"{home}/IdeaProjects/!!!", home), "my-project")

    def test_github_addresses(self):
        full = self.app.full_name
        self.assertEqual(full("https://github.com/Kid/Proj.git"), "Kid/Proj")
        self.assertEqual(full("https://github.com/kid/proj"), "kid/proj")
        self.assertEqual(full("git@github.com:kid/proj.git"), "kid/proj")
        self.assertIsNone(full("https://gitlab.com/kid/proj.git"))
        self.assertIsNone(full("https://github.com/kid"))
        self.assertIsNone(full(None))
        self.assertEqual(self.app.web_url("https://github.com/kid/proj.git"), "https://github.com/kid/proj")


class SigningIn(Lab):
    def test_code_is_shown_then_git_is_set_up(self):
        self.assertFalse(self.app.signed_in())
        codes = []
        process = self.app.start_sign_in(codes.append)
        process.wait()
        process.reader.join(5)
        self.assertEqual(process.returncode, 0)
        self.assertEqual(codes, ["AB12-CD34"])
        self.assertTrue(self.app.signed_in())
        user = self.app.finish_sign_in()
        self.assertEqual(user["login"], "student1")
        self.assertTrue(os.path.exists(os.path.join(self.state, "setup-git")))
        email = subprocess.run(["git", "config", "--global", "user.email"], capture_output=True, text=True).stdout
        name = subprocess.run(["git", "config", "--global", "user.name"], capture_output=True, text=True).stdout
        self.assertEqual(email.strip(), "4242+student1@users.noreply.github.com")
        self.assertEqual(name.strip(), "Student One")

    def test_own_email_is_kept(self):
        subprocess.run(["git", "config", "--global", "user.email", "me@example.com"], check=True)
        subprocess.run(["git", "config", "--global", "user.name", "Me"], check=True)
        self.sign_in()
        email = subprocess.run(["git", "config", "--global", "user.email"], capture_output=True, text=True).stdout
        self.assertEqual(email.strip(), "me@example.com")

    def test_sign_out(self):
        self.sign_in()
        self.app.sign_out()
        self.assertFalse(self.app.signed_in())

    def test_messages_for_students(self):
        friendly = self.app.friendly
        self.assertIn("Wi-Fi", friendly("fatal: unable to access 'https://github.com/x': Could not resolve host"))
        self.assertIn("Sign out", friendly("remote: Invalid username or password.\nfatal: Authentication failed"))
        self.assertIn("too big", friendly("remote: error: File big.bin is 120 MB; this exceeds GitHub's file size limit"))
        self.assertIn("aren't allowed", friendly("remote: Permission to x/y.git denied to kid."))
        self.assertTrue(friendly("weird\nthing happened").startswith("Something went wrong"))


class Saving(Lab):
    def test_first_save_makes_a_private_project(self):
        home = self.home()
        user = self.sign_in()
        project = f"{home}/CS/Java/Game"
        self.write(f"{project}/Main.java", "class Main {}\n")
        self.write(f"{project}/out/Main.class", "binary")
        self.write(f"{project}/__pycache__/x.pyc", "binary")
        self.assertEqual(self.app.status(project)["state"], "new")
        result = self.app.save(project, user, home)
        self.assertIn("Game", result["message"])
        self.assertEqual(result["url"], "https://github.com/student1/Game")
        self.assertTrue(os.path.exists(os.path.join(self.state, "remotes", "student1", "Game.git.private")))
        self.assertEqual(self.remote_files("student1", "Game"), [".gitignore", "Main.java"])
        self.assertEqual(self.app.status(project)["state"], "saved")
        log = self.remote_show("student1", "Game", "--format=%an <%ae>%n%s")
        self.assertIn("Student One <4242+student1@users.noreply.github.com>", log)
        self.assertIn("Saved from ", log)

    def test_loose_python_files_folder(self):
        home = self.home()
        user = self.sign_in()
        self.write(f"{home}/CS/Python/hello.py", "print('hi')\n")
        result = self.app.save(f"{home}/CS/Python", user, home)
        self.assertIn("CS-Python", result["message"])
        self.assertEqual(self.remote_files("student1", "CS-Python"), [".gitignore", "hello.py"])

    def test_name_already_used_gets_a_number(self):
        home = self.home()
        user = self.sign_in()
        for folder in ("CS/Java/Game", "IdeaProjects/Game"):
            self.write(f"{home}/{folder}/Main.java", "class Main {}\n")
        self.app.save(f"{home}/CS/Java/Game", user, home)
        result = self.app.save(f"{home}/IdeaProjects/Game", user, home)
        self.assertIn("Game-2", result["message"])
        self.assertIn("already had a project", result["message"])

    def test_later_saves_and_the_note(self):
        home = self.home()
        user = self.sign_in()
        project = f"{home}/CS/Python/quiz"
        self.write(f"{project}/quiz.py", "print(1)\n")
        self.app.save(project, user, home)
        self.write(f"{project}/quiz.py", "print(2)\n")
        self.write(f"{project}/more.py", "print(3)\n")
        info = self.app.status(project)
        self.assertEqual((info["state"], info["changes"]), ("changes", 2))
        self.assertEqual(self.app.describe(info)[1], "Save to GitHub")
        result = self.app.save(project, user, home, note="Finished question 3")
        self.assertEqual(result["message"], "Saved on GitHub ✓")
        self.assertEqual(self.remote_show("student1", "quiz", "main:quiz.py"), "print(2)\n")
        self.assertIn("Finished question 3", self.remote_show("student1", "quiz", "--format=%B"))
        self.assertEqual(self.app.status(project)["state"], "saved")
        self.assertIsNone(self.app.describe(self.app.status(project))[1])

    def test_nothing_new_still_fine(self):
        home = self.home()
        user = self.sign_in()
        project = f"{home}/CS/Python/quiz"
        self.write(f"{project}/quiz.py", "print(1)\n")
        self.app.save(project, user, home)
        self.assertEqual(self.app.save(project, user, home)["message"], "Saved on GitHub ✓")

    def test_refused_folders(self):
        home = self.home()
        user = self.sign_in()
        with self.assertRaisesRegex(self.app.StudentError, "home folder"):
            self.app.save(home, user, home)
        with self.assertRaisesRegex(self.app.StudentError, "home folder"):
            self.app.save("/tmp", user, home)
        os.makedirs(f"{home}/CS/Java/Empty")
        with self.assertRaisesRegex(self.app.StudentError, "empty"):
            self.app.save(f"{home}/CS/Java/Empty", user, home)
        self.write(f"{home}/CS/Java/A/Main.java", "x")
        os.makedirs(f"{home}/CS/Java/A/.git")
        with self.assertRaisesRegex(self.app.StudentError, "one at a time"):
            self.app.save(f"{home}/CS/Java", user, home)
        self.assertFalse(os.path.exists(f"{home}/CS/Java/.git"))

    def test_big_files_are_left_out(self):
        home = self.home()
        user = self.sign_in()
        project = f"{home}/CS/Python/data"
        self.write(f"{project}/main.py", "print(1)\n")
        with open(f"{project}/huge.bin", "wb") as handle:
            handle.truncate(self.app.MAX_FILE_BYTES + 1)            # sparse: no real disk use
        result = self.app.save(project, user, home)
        self.assertIn("huge.bin", result["message"])
        self.assertEqual(self.remote_files("student1", "data"), [".gitignore", "main.py"])
        self.assertEqual(self.app.status(project)["state"], "saved")

    def test_offline(self):
        home = self.home()
        user = self.sign_in()
        project = f"{home}/CS/Python/quiz"
        self.write(f"{project}/quiz.py", "print(1)\n")
        open(os.path.join(self.state, "offline"), "w").close()
        with self.assertRaisesRegex(self.app.StudentError, "Wi-Fi"):
            self.app.save(project, user, home)
        with self.assertRaisesRegex(self.app.StudentError, "Wi-Fi"):
            self.app.github_user()


class TwoLaptops(Lab):
    """The same student on laptop 1 and laptop 2."""

    def setUp(self):
        super().setUp()
        self.one, self.two = self.home("laptop1"), self.home("laptop2")
        self.user = self.sign_in()
        self.project1 = f"{self.one}/CS/Python/story"
        self.write(f"{self.project1}/story.py", "line = 1\n")
        self.app.save(self.project1, self.user, self.one)
        listed = self.app.github_projects()
        self.assertEqual([p["full_name"] for p in listed], ["student1/story"])
        self.project2 = self.app.download(listed[0], self.two)

    def test_download_then_get_latest(self):
        self.assertEqual(self.project2, f"{self.two}/GitHub/story")
        self.assertIn(self.project2, self.app.find_projects(self.two))
        self.assertEqual(self.app.status(self.project2)["state"], "saved")
        self.write(f"{self.project2}/ending.py", "end = True\n")
        self.app.save(self.project2, self.user, self.two)
        # Back on laptop 1: after checking online it knows about the newer version.
        self.assertEqual(self.app.status(self.project1)["state"], "saved")
        self.app.check_online(self.project1)
        info = self.app.status(self.project1)
        self.assertEqual(info["state"], "behind")
        self.assertEqual(self.app.describe(info)[1], "Get latest")
        self.app.save(self.project1, self.user, self.one)
        self.assertTrue(os.path.exists(f"{self.project1}/ending.py"))
        self.assertEqual(self.app.status(self.project1)["state"], "saved")

    def test_second_download_gets_a_new_folder(self):
        again = self.app.download(self.app.github_projects()[0], self.two)
        self.assertEqual(again, f"{self.two}/GitHub/story-2")

    def test_changes_on_both_laptops_are_combined(self):
        self.write(f"{self.project2}/b.py", "b = 2\n")
        self.app.save(self.project2, self.user, self.two)
        self.write(f"{self.project1}/a.py", "a = 1\n")
        self.app.check_online(self.project1)
        self.assertEqual(self.app.status(self.project1)["state"], "both")
        self.assertEqual(self.app.save(self.project1, self.user, self.one)["message"], "Saved on GitHub ✓")
        self.assertEqual(self.remote_files("student1", "story"), [".gitignore", "a.py", "b.py", "story.py"])

    def test_clashing_versions_keep_both(self):
        self.write(f"{self.project2}/story.py", "line = 2  # laptop 2\n")
        self.app.save(self.project2, self.user, self.two)
        self.write(f"{self.project1}/story.py", "line = 3  # laptop 1\n")
        result = self.app.save(self.project1, self.user, self.one)
        self.assertIn("copy", result)
        self.assertIn("Nothing is lost", result["message"])
        self.assertEqual(self.remote_show("student1", "story", "main:story.py"), "line = 2  # laptop 2\n")
        self.assertEqual(self.remote_show("student1", "story", result["copy"] + ":story.py"),
                         "line = 3  # laptop 1\n")
        with open(f"{self.project1}/story.py") as handle:            # this laptop's work is untouched
            self.assertEqual(handle.read(), "line = 3  # laptop 1\n")
        self.assertFalse(os.path.exists(f"{self.project1}/.git/MERGE_HEAD"))

    def test_classroom_repos_are_listed(self):
        bare = os.path.join(self.state, "remotes", "mr-e-classroom", "assignment1-student1.git")
        subprocess.run(["git", "clone", "-q", "--bare", os.path.join(self.state, "remotes", "student1", "story.git"),
                        bare], check=True)
        names = [p["full_name"] for p in self.app.github_projects()]
        self.assertIn("mr-e-classroom/assignment1-student1", names)
        folder = self.app.download([p for p in self.app.github_projects()
                                    if p["name"] == "assignment1-student1"][0], self.two)
        self.write(f"{folder}/answer.py", "print(42)\n")
        self.assertEqual(self.app.save(folder, self.user, self.two)["message"], "Saved on GitHub ✓")
        self.assertEqual(self.remote_files("mr-e-classroom", "assignment1-student1"),
                         [".gitignore", "answer.py", "story.py"])


STARTER_GITIGNORE = os.path.join(HERE, "..", "updates", "0013-javafx-projects", "files", "usr", "local", "share",
                                 "lab-javafx", "JavaFXStarter", ".gitignore")


class IntelliJProjects(Lab):
    """JavaFX projects from "New JavaFX Project": the starter's own .gitignore
    doesn't list .idea/workspace.xml, which IntelliJ rewrites on every start."""

    def make_project(self, home):
        project = f"{home}/IdeaProjects/MyFxApp"
        shutil.copy(STARTER_GITIGNORE, self.ensure(f"{project}/.gitignore"))
        self.write(f"{project}/pom.xml", "<project/>\n")
        self.write(f"{project}/src/main/java/module-info.java", "module x {}\n")
        self.write(f"{project}/target/classes/X.class", "binary")
        self.write(f"{project}/.idea/misc.xml", "<project/>\n")
        self.write(f"{project}/.idea/workspace.xml", "<layout laptop='1'/>\n")
        self.write(f"{project}/.idea/shelf/x.patch", "patch\n")
        return project

    def ensure(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return path

    def test_layout_files_stay_on_the_laptop(self):
        home = self.home()
        user = self.sign_in()
        project = self.make_project(home)
        self.assertIn(project, self.app.find_projects(home))
        self.app.save(project, user, home)
        self.assertEqual(self.remote_files("student1", "MyFxApp"),
                         [".gitignore", ".idea/misc.xml", "pom.xml", "src/main/java/module-info.java"])
        self.write(f"{project}/.idea/workspace.xml", "<layout laptop='1' moved='yes'/>\n")
        self.assertEqual(self.app.status(project)["state"], "saved")       # IntelliJ's rewrite isn't a change

    def test_two_laptops_dont_clash_over_the_layout(self):
        one, two = self.home("laptop1"), self.home("laptop2")
        user = self.sign_in()
        project1 = self.make_project(one)
        self.app.save(project1, user, one)
        project2 = self.app.download(self.app.github_projects()[0], two)
        self.write(f"{project2}/.idea/workspace.xml", "<layout laptop='2'/>\n")
        self.write(f"{project2}/src/main/java/App.java", "class App {}\n")
        self.app.save(project2, user, two)
        self.write(f"{project1}/.idea/workspace.xml", "<layout laptop='1' again/>\n")
        result = self.app.save(project1, user, one)
        self.assertNotIn("copy", result)
        self.assertTrue(os.path.exists(f"{project1}/src/main/java/App.java"))

    def test_project_that_already_tracks_the_layout(self):
        home = self.home()
        user = self.sign_in()
        project = f"{home}/GitHub/assignment"
        self.write(f"{project}/Main.java", "class Main {}\n")
        self.write(f"{project}/.idea/workspace.xml", "<layout/>\n")
        bare = os.path.join(self.state, "remotes", "mr-e-classroom", "assignment.git")
        os.makedirs(os.path.dirname(bare))
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", bare], check=True)
        for args in (["init", "-q", "-b", "main"], ["add", "-A"],
                     ["-c", "user.name=T", "-c", "user.email=t@x", "commit", "-qm", "start"],
                     ["remote", "add", "origin", "https://github.com/mr-e-classroom/assignment.git"],
                     ["push", "-q", "-u", "origin", "main"]):
            subprocess.run(["git", "-C", project, *args], check=True)
        self.app.save(project, user, home)
        self.assertEqual(self.remote_files("mr-e-classroom", "assignment"), ["Main.java"])
        self.assertTrue(os.path.exists(f"{project}/.idea/workspace.xml"))     # still on the laptop


class InstallScript(unittest.TestCase):
    def test_install_script(self):
        with open(os.path.join(UPDATE, "install.sh")) as handle:
            script = handle.read()
        self.assertIn('source "$LAB_UPDATER_HELPERS"', script)
        self.assertIn("apt_install gh", script)
        for path in ("usr/local/lib/lab-github/save-to-github.py", "usr/local/share/applications/lab-save-to-github.desktop"):
            self.assertIn("files/" + path, script)
            self.assertTrue(os.path.exists(os.path.join(UPDATE, "files", path)))
        self.assertTrue(os.access(APP, os.X_OK))
        subprocess.run(["bash", "-n", os.path.join(UPDATE, "install.sh")], check=True)

    def test_menu_entry(self):
        with open(os.path.join(UPDATE, "files", "usr", "local", "share", "applications", "lab-save-to-github.desktop")) as h:
            entry = h.read()
        self.assertIn("Name=Save to GitHub", entry)
        self.assertIn("Exec=/usr/bin/python3 /usr/local/lib/lab-github/save-to-github.py", entry)
        if shutil.which("desktop-file-validate"):
            path = os.path.join(UPDATE, "files", "usr", "local", "share", "applications", "lab-save-to-github.desktop")
            subprocess.run(["desktop-file-validate", path], check=True)


@unittest.skipUnless(shutil.which("gtk4-broadwayd"), "needs gtk4-broadwayd for a private display")
class Window(Lab):
    """The real GTK window on a private Broadway display (never the user's screen)."""

    def setUp(self):
        super().setUp()
        self.display = f":{40 + os.getpid() % 50}"
        self.runtime = os.path.join(self.dir, "runtime")
        os.makedirs(self.runtime, mode=0o700)
        self.broadway = subprocess.Popen(["gtk4-broadwayd", self.display], stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL, env=dict(os.environ, XDG_RUNTIME_DIR=self.runtime))
        time.sleep(1)

    def tearDown(self):
        self.broadway.terminate()
        self.broadway.wait()
        super().tearDown()

    def show(self, home, what="1"):
        env = dict(os.environ, HOME=home, GDK_BACKEND="broadway", BROADWAY_DISPLAY=self.display,
                   XDG_RUNTIME_DIR=self.runtime, LAB_GITHUB_SELFTEST=what,
                   LAB_GITHUB_APP_ID=f"com.school.SaveToGitHubTest{os.getpid()}{int(time.time() * 1000) % 100000}")
        env.pop("WAYLAND_DISPLAY", None)
        env.pop("DISPLAY", None)
        out = subprocess.run([sys.executable, "-I", APP], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout.strip().splitlines()[-1])

    def test_signed_out_shows_the_steps(self):
        self.assertEqual(self.show(self.home())["page"], "signin")

    def test_signed_in_lists_projects(self):
        home = self.home()
        user = self.sign_in()
        self.write(f"{home}/CS/Python/hello.py", "print(1)\n")
        self.write(f"{home}/CS/Java/Game/Main.java", "class Main {}\n")
        self.app.save(f"{home}/CS/Java/Game", user, home)
        shown = self.show(home)
        self.assertEqual(shown["page"], "projects")
        self.assertEqual(shown["projects"], [
            {"name": "Game", "status": "Saved on GitHub ✓", "button": None},
            {"name": "Python", "status": "Not on GitHub yet", "button": "Save to GitHub"},
        ])

    def test_download_list(self):
        home = self.home()
        user = self.sign_in()
        self.write(f"{home}/CS/Java/Game/Main.java", "class Main {}\n")
        self.app.save(f"{home}/CS/Java/Game", user, home)
        subprocess.run(["git", "clone", "-q", "--bare", os.path.join(self.state, "remotes", "student1", "Game.git"),
                        os.path.join(self.state, "remotes", "mr-e-classroom", "assignment1-student1.git")], check=True)
        shown = self.show(home, "download")
        self.assertEqual(shown["page"], "download")
        self.assertEqual(shown["projects"], [
            {"name": "assignment1-student1  (from mr-e-classroom)", "button": "Download"},
            {"name": "Game", "button": None},
        ])


if __name__ == "__main__":
    unittest.main()
