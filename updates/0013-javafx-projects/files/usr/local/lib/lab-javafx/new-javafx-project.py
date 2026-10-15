#!/usr/bin/env python3
""""New JavaFX Project" (lab update 0013): copies the school's working JavaFX
starter project into ~/IdeaProjects/<name> and opens it in IntelliJ.

The starter (Java 25, JavaFX 25, Launcher class, FXML + controller) lives in
/usr/local/share/lab-javafx/JavaFXStarter.
"""

import os
import re
import shutil
import subprocess
import sys

TEMPLATE = os.environ.get("LAB_JAVAFX_TEMPLATE", "/usr/local/share/lab-javafx/JavaFXStarter")
PROJECTS_DIR = os.environ.get("LAB_JAVAFX_PROJECTS", os.path.expanduser("~/IdeaProjects"))
INTELLIJ = "/opt/intellij/bin/idea"
TEMPLATE_NAME = "JavaFXStarter"

NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,39}$")


def create_project(name):
    """Copy the starter to PROJECTS_DIR/name. Returns its path; raises ValueError with a message."""
    if not NAME_PATTERN.fullmatch(name):
        raise ValueError("Use letters, numbers or _ only, starting with a letter (no spaces).")

    destination = os.path.join(PROJECTS_DIR, name)
    if os.path.exists(destination):
        raise ValueError(f"You already have a project called {name}. Pick another name.")

    os.makedirs(PROJECTS_DIR, exist_ok=True)
    shutil.copytree(TEMPLATE, destination, ignore=shutil.ignore_patterns("target", ".idea"))

    pom_path = os.path.join(destination, "pom.xml")
    with open(pom_path, "r", encoding="utf-8") as pom:
        text = pom.read()
    text = text.replace(f"<artifactId>{TEMPLATE_NAME}</artifactId>", f"<artifactId>{name}</artifactId>", 1)
    text = text.replace(f"<name>{TEMPLATE_NAME}</name>", f"<name>{name}</name>", 1)
    with open(pom_path, "w", encoding="utf-8") as pom:
        pom.write(text)

    return destination


def open_in_intellij(path):
    subprocess.Popen([INTELLIJ, path], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_gui():
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk

    def activate(app):
        window = Gtk.ApplicationWindow(application=app, title="New JavaFX Project")
        window.set_default_size(440, -1)
        window.set_resizable(False)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for side in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{side}")(24)

        heading = Gtk.Label()
        heading.set_markup("<span size='x-large' weight='bold'>New JavaFX Project</span>")
        box.append(heading)

        info = Gtk.Label(label="Creates a ready-to-run JavaFX project in IdeaProjects\n"
                               "and opens it in IntelliJ. Run it with the Launcher class.")
        info.set_justify(Gtk.Justification.CENTER)
        info.set_wrap(True)
        box.append(info)

        entry = Gtk.Entry()
        entry.set_placeholder_text("Project name, e.g. MyGame")
        box.append(entry)

        message = Gtk.Label()
        message.set_wrap(True)
        box.append(message)

        button = Gtk.Button(label="Create and open in IntelliJ")
        button.add_css_class("suggested-action")
        box.append(button)

        def create(_widget):
            try:
                path = create_project(entry.get_text().strip())
            except ValueError as error:
                message.set_text(str(error))
                return
            except OSError as error:
                message.set_text(f"Could not create the project: {error.strerror}")
                return
            open_in_intellij(path)
            window.close()

        button.connect("clicked", create)
        entry.connect("activate", create)

        window.set_child(box)
        window.present()

    app = Gtk.Application(application_id="com.school.NewJavaFXProject")
    app.connect("activate", activate)
    return app.run([])


if __name__ == "__main__":
    sys.exit(run_gui())
