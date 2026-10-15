#!/usr/bin/env python3
"""Tests for 0013-javafx-projects / 0014-javafx-libraries: the JavaFX helper
(latest version, from 0014) and "New JavaFX Project" (0013).
Temp folders only; no network, no root, no GUI.

    python3 -I update-repo/tests/test_0013_javafx_projects.py
"""

import importlib.machinery
import importlib.util
import os
import shutil
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
UPDATE = os.path.join(HERE, "..", "updates", "0013-javafx-projects", "files")
LIB = os.path.join(UPDATE, "usr", "local", "lib", "lab-javafx")
FIXER_0014 = os.path.join(HERE, "..", "updates", "0014-javafx-libraries", "files",
                          "usr", "local", "lib", "lab-javafx", "javafx-pom-fixer.py")
TEMPLATE = os.path.join(UPDATE, "usr", "local", "share", "lab-javafx", "JavaFXStarter")


def load(name, filename):
    loader = importlib.machinery.SourceFileLoader(name, filename if os.path.isabs(filename) else os.path.join(LIB, filename))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


fixer = load("fixer", os.path.abspath(FIXER_0014))
new_project = load("new_project", "new-javafx-project.py")

# What IntelliJ's JavaFX wizard writes on the lab laptops (2026-10-14).
WIZARD_POM = """<project>
    <dependencies>
        <dependency>
            <groupId>org.openjfx</groupId>
            <artifactId>javafx-controls</artifactId>
            <version>21.0.6</version>
        </dependency>
    </dependencies>
    <build>
        <plugins>
            <plugin>
                <groupId>org.apache.maven.plugins</groupId>
                <artifactId>maven-compiler-plugin</artifactId>
                <version>3.13.0</version>
                <configuration>
                    <source>8</source>
                    <target>8</target>
                </configuration>
            </plugin>
            <plugin>
                <groupId>org.openjfx</groupId>
                <artifactId>javafx-maven-plugin</artifactId>
                <version>0.0.8</version>
            </plugin>
        </plugins>
    </build>
</project>
"""

# Wizard pom with extra libraries ticked (their exclusions name org.openjfx too).
LIBS_POM = WIZARD_POM.replace("""    </dependencies>""", """        <dependency>
            <groupId>org.junit.jupiter</groupId>
            <artifactId>junit-jupiter-api</artifactId>
            <scope>test</scope>
        </dependency>
        <dependency>
            <groupId>org.kordamp.ikonli</groupId>
            <artifactId>ikonli-javafx</artifactId>
            <version>12.3.1</version>
        </dependency>
        <dependency>
            <groupId>eu.hansolo</groupId>
            <artifactId>tilesfx</artifactId>
            <version>21.0.9</version>
            <exclusions>
                <exclusion>
                    <groupId>org.openjfx</groupId>
                    <artifactId>*</artifactId>
                </exclusion>
            </exclusions>
        </dependency>
    </dependencies>""")

PLAIN_JAVA_POM = WIZARD_POM.replace("org.openjfx", "org.example").replace("javafx-maven-plugin", "other-plugin")


class Fixer(unittest.TestCase):

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.notified = []
        patches = [
            mock.patch.object(fixer, "HOME", self.home),
            mock.patch.object(fixer, "STATE_DIR", os.path.join(self.home, ".local/state/lab-javafx")),
            mock.patch.object(fixer, "FIXED_LIST", os.path.join(self.home, ".local/state/lab-javafx/fixed")),
            mock.patch.object(fixer, "LOG_FILE", os.path.join(self.home, ".local/state/lab-javafx/fixer.log")),
            mock.patch.object(fixer, "BACKUP_DIR", os.path.join(self.home, ".local/state/lab-javafx/module-info-backups")),
            mock.patch.object(fixer, "notify", lambda title, body: self.notified.append(body)),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def tearDown(self):
        shutil.rmtree(self.home)

    def project(self, relative, pom=WIZARD_POM, jdk=None):
        path = os.path.join(self.home, relative)
        os.makedirs(path)
        with open(os.path.join(path, "pom.xml"), "w") as pom_file:
            pom_file.write(pom)
        if jdk:
            os.makedirs(os.path.join(path, ".idea"))
            with open(os.path.join(path, ".idea", "misc.xml"), "w") as misc:
                misc.write(f'<component name="ProjectRootManager" languageLevel="JDK_{jdk}" project-jdk-name="{jdk}" />')
        return os.path.join(path, "pom.xml")

    def read(self, path):
        with open(path) as pom_file:
            return pom_file.read()

    def scan(self):
        fixer.scan_once(fixer.read_fixed(), {})

    def test_wizard_pom_becomes_java_25(self):
        pom = self.project("IdeaProjects/demo")
        self.scan()
        text = self.read(pom)
        self.assertIn("                    <release>25</release>\n", text)
        self.assertNotIn("<source>", text)
        self.assertNotIn("<target>", text)
        self.assertEqual(text, WIZARD_POM.replace(
            "<source>8</source>\n                    <target>8</target>\n", "<release>25</release>\n"))
        self.assertEqual(len(self.notified), 1)
        self.assertIn('"demo" now uses Java 25', self.notified[0])

    def test_uses_the_projects_jdk(self):
        pom = self.project("IdeaProjects/demo21", jdk="21")
        self.scan()
        self.assertIn("<release>21</release>", self.read(pom))

    def test_projects_in_cs_folder_are_found(self):
        pom = self.project("CS/JavaFX/MyGame")
        self.scan()
        self.assertIn("<release>25</release>", self.read(pom))

    def test_module_info_counts_as_javafx(self):
        pom = self.project("IdeaProjects/mods", pom=PLAIN_JAVA_POM)
        os.makedirs(os.path.join(self.home, "IdeaProjects/mods/src/main/java"))
        open(os.path.join(self.home, "IdeaProjects/mods/src/main/java/module-info.java"), "w").close()
        self.scan()
        self.assertIn("<release>25</release>", self.read(pom))

    def test_non_javafx_project_untouched(self):
        pom = self.project("IdeaProjects/plain", pom=PLAIN_JAVA_POM)
        self.scan()
        self.assertEqual(self.read(pom), PLAIN_JAVA_POM)
        self.assertEqual(self.notified, [])

    def test_good_pom_untouched(self):
        with open(os.path.join(TEMPLATE, "pom.xml")) as template_pom:
            good = template_pom.read()
        pom = self.project("IdeaProjects/good", pom=good)
        self.scan()
        self.assertEqual(self.read(pom), good)

    def test_fixed_only_once(self):
        pom = self.project("IdeaProjects/demo")
        self.scan()
        with open(pom, "w") as pom_file:
            pom_file.write(WIZARD_POM)     # the student puts 8 back on purpose
        self.scan()
        self.assertEqual(self.read(pom), WIZARD_POM)

    def test_properties_variant(self):
        pom_text = WIZARD_POM.replace("<project>", """<project>
    <properties>
        <maven.compiler.source>1.8</maven.compiler.source>
        <maven.compiler.target>1.8</maven.compiler.target>
    </properties>""")
        pom = self.project("IdeaProjects/props", pom=pom_text)
        self.scan()
        text = self.read(pom)
        self.assertIn("        <maven.compiler.release>25</maven.compiler.release>\n", text)
        self.assertNotIn("maven.compiler.target", text)

    def test_hidden_and_build_folders_skipped(self):
        hidden = self.project(".cache/x")
        target = self.project("IdeaProjects/demo/target/y")
        too_deep = self.project("a/b/c/d/e")
        self.scan()
        for pom in (hidden, target, too_deep):
            self.assertEqual(self.read(pom), WIZARD_POM)

    def test_keeps_file_mode(self):
        pom = self.project("IdeaProjects/demo")
        os.chmod(pom, 0o664)
        self.scan()
        self.assertEqual(os.stat(pom).st_mode & 0o777, 0o664)
        self.assertFalse(os.path.exists(pom + ".lab-fix.tmp"))


    # --- 0014: extra libraries -> module-info.java moved out ---

    def module_info(self, project, text="module x { requires javafx.controls; }"):
        path = os.path.join(self.home, project, "src/main/java/module-info.java")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as module_file:
            module_file.write(text)
        return path

    def test_extra_libraries_remove_module_info(self):
        self.project("IdeaProjects/libtest", pom=LIBS_POM)
        module_info = self.module_info("IdeaProjects/libtest", "module libtest { requires org.kordamp.ikonli.javafx; }")
        self.scan()
        self.assertFalse(os.path.exists(module_info))
        backups = os.listdir(fixer.BACKUP_DIR)
        self.assertEqual(len(backups), 1)
        self.assertTrue(backups[0].startswith("libtest-"))
        with open(os.path.join(fixer.BACKUP_DIR, backups[0])) as backup:
            self.assertIn("ikonli", backup.read())
        self.assertIn("<release>25</release>", self.read(os.path.join(self.home, "IdeaProjects/libtest/pom.xml")))

    def test_javafx_only_project_keeps_module_info(self):
        self.project("IdeaProjects/plainfx")             # only org.openjfx (+ junit)
        module_info = self.module_info("IdeaProjects/plainfx")
        self.scan()
        self.assertTrue(os.path.exists(module_info))

    def test_starter_template_keeps_module_info(self):
        destination = os.path.join(self.home, "IdeaProjects", "Starter")
        shutil.copytree(TEMPLATE, destination)
        self.scan()
        self.assertTrue(os.path.exists(os.path.join(destination, "src/main/java/module-info.java")))

    def test_module_info_written_after_pom_is_still_handled(self):
        self.project("IdeaProjects/late", pom=LIBS_POM)
        fixed, seen = fixer.read_fixed(), {}
        fixer.scan_once(fixed, seen)                    # pom fixed; no module-info yet
        module_info = self.module_info("IdeaProjects/late")
        fixer.scan_once(fixed, seen)
        self.assertFalse(os.path.exists(module_info))

    def test_recreated_module_info_is_left_alone(self):
        self.project("IdeaProjects/libtest", pom=LIBS_POM)
        self.module_info("IdeaProjects/libtest")
        self.scan()
        again = self.module_info("IdeaProjects/libtest")  # the student puts it back on purpose
        self.scan()
        self.assertTrue(os.path.exists(again))

    def test_extra_libraries_detection(self):
        self.assertEqual(fixer.extra_libraries(WIZARD_POM), set())
        self.assertEqual(fixer.extra_libraries(LIBS_POM), {"org.kordamp.ikonli", "eu.hansolo"})


class NewProject(unittest.TestCase):

    def setUp(self):
        self.projects = tempfile.mkdtemp()
        patch = mock.patch.object(new_project, "PROJECTS_DIR", self.projects)
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(new_project, "TEMPLATE", TEMPLATE)
        patch.start()
        self.addCleanup(patch.stop)

    def tearDown(self):
        shutil.rmtree(self.projects)

    def test_creates_renamed_copy(self):
        path = new_project.create_project("MyGame")
        self.assertEqual(path, os.path.join(self.projects, "MyGame"))
        with open(os.path.join(path, "pom.xml")) as pom:
            text = pom.read()
        self.assertIn("<artifactId>MyGame</artifactId>", text)
        self.assertIn("<name>MyGame</name>", text)
        self.assertIn("<release>25</release>", text)
        for relative in ("mvnw", "src/main/java/module-info.java",
                         "src/main/java/com/example/javafxstarter/Launcher.java",
                         "src/main/resources/com/example/javafxstarter/hello-view.fxml",
                         ".mvn/wrapper/maven-wrapper.properties"):
            self.assertTrue(os.path.exists(os.path.join(path, relative)), relative)
        self.assertFalse(os.path.exists(os.path.join(path, "target")))
        self.assertFalse(os.path.exists(os.path.join(path, ".idea")))

    def test_bad_names_rejected(self):
        for name in ("", "my game", "1game", "../evil", "a/b", "x" * 41):
            with self.assertRaises(ValueError, msg=name):
                new_project.create_project(name)
        self.assertEqual(os.listdir(self.projects), [])

    def test_existing_project_not_overwritten(self):
        new_project.create_project("Game")
        with self.assertRaises(ValueError):
            new_project.create_project("Game")

    def test_starter_is_a_valid_javafx_project(self):
        # Must never be "fixed" by the fixer, and must declare its module.
        with open(os.path.join(TEMPLATE, "pom.xml")) as pom:
            self.assertIsNone(fixer.fixed_text(pom.read(), "25"))
        with open(os.path.join(TEMPLATE, "src/main/java/module-info.java")) as module_info:
            self.assertIn("requires javafx.controls", module_info.read())


if __name__ == "__main__":
    unittest.main(verbosity=2)
