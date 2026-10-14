// School lab login screen (GDM greeter only):
//  * "Login to TDSB to create your account" panel at the top-left. A student
//    (9-digit ID) or staff member (6-digit ID) types their TDSB ID and
//    password; the root service checks them by joining TDSB-WIFI and, if
//    accepted, creates the account.
//  * Hides the "Not listed?" button under the user list.

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as LoginDialog from 'resource:///org/gnome/shell/gdm/loginDialog.js';
import St from 'gi://St';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

const LOGIN_ID_PATTERN = /^[A-Za-z0-9]{3,27}$/;
const CALL_TIMEOUT_MS = 120000;

let panel = null;
let originalShowUserList = null;

function hideNotListed(dialog) {
    dialog?._notListedButton?.hide();
}

export default class SchoolAccountExtension {
    enable() {
        // "Not listed?": the login dialog re-shows it whenever the user list
        // appears, so hide it right after that every time.
        originalShowUserList = LoginDialog.LoginDialog.prototype._showUserList;
        LoginDialog.LoginDialog.prototype._showUserList = function (...args) {
            originalShowUserList.apply(this, args);
            hideNotListed(this);
        };
        hideNotListed(Main.screenShield?._dialog);

        panel = new St.BoxLayout({
            vertical: true,
            style_class: 'school-account-panel'
        });

        let title = new St.Label({
            text: 'Login to TDSB to create your account'
        });

        let idEntry = new St.Entry({
            hint_text: 'Student or staff ID',
            style_class: 'school-account-entry'
        });

        let passwordEntry = new St.Entry({
            hint_text: 'Password',
            style_class: 'school-account-entry'
        });
        passwordEntry.clutter_text.set_password_char('•');

        let createButton = new St.Button({
            label: 'Create Account',
            style_class: 'button'
        });

        let status = new St.Label({
            text: ''
        });
        status.clutter_text.set_line_wrap(true);

        let busy = false;

        createButton.connect('clicked', () => {
            if (busy)
                return;

            let studentId = idEntry.get_text().trim();
            let password = passwordEntry.get_text();

            if (!LOGIN_ID_PATTERN.test(studentId)) {
                status.set_text('Your ID is 3 to 27 letters or numbers.');
                return;
            }

            if (!password) {
                status.set_text('Please enter your password.');
                return;
            }

            busy = true;
            createButton.reactive = false;
            status.set_text('Checking with TDSB-WIFI… this can take up to a minute.');

            try {
                let connection = Gio.bus_get_sync(Gio.BusType.SYSTEM, null);

                // The password travels through a pipe, never as a plain argument.
                let passwordProcess = Gio.Subprocess.new(
                    ['/usr/bin/printf', '%s', password + '\n'],
                    Gio.SubprocessFlags.STDOUT_PIPE
                );
                let passwordFd = passwordProcess.get_stdout_pipe().get_fd();

                let fdList = new Gio.UnixFDList();
                let fdIndex = fdList.append(passwordFd);

                connection.call_with_unix_fd_list(
                    'com.school.StudentAccount',
                    '/com/school/StudentAccount',
                    'com.school.StudentAccount',
                    'create_tdsb_account',
                    new GLib.Variant('(sh)', [studentId, fdIndex]),
                    new GLib.VariantType('(s)'),
                    Gio.DBusCallFlags.NONE,
                    CALL_TIMEOUT_MS,
                    fdList,
                    null,
                    (conn, result) => {
                        try {
                            let [reply] = conn.call_with_unix_fd_list_finish(result);
                            let [message] = reply.deep_unpack();

                            status.set_text(message);

                            if (message.startsWith('Account created')) {
                                idEntry.set_text('');
                                passwordEntry.set_text('');
                            }
                        } catch (error) {
                            status.set_text('ERROR: ' + error.message);
                        }

                        busy = false;
                        createButton.reactive = true;
                    }
                );
            } catch (error) {
                status.set_text('ERROR: ' + error.message);
                busy = false;
                createButton.reactive = true;
            }
        });

        panel.add_child(title);
        panel.add_child(idEntry);
        panel.add_child(passwordEntry);
        panel.add_child(createButton);
        panel.add_child(status);

        Main.layoutManager.addTopChrome(panel, {
            affectsStruts: false
        });

        panel.set_position(40, 40);
        panel.set_width(320);
    }

    disable() {
        if (originalShowUserList) {
            LoginDialog.LoginDialog.prototype._showUserList = originalShowUserList;
            originalShowUserList = null;
        }

        if (panel) {
            panel.destroy();
            panel = null;
        }
    }
}
