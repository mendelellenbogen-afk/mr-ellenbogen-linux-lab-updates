// School lab login screen (GDM greeter only):
//  * "Login to TDSB to create your account" panel at the top-left. A student
//    (9-digit ID) or staff member (6-digit ID) types their TDSB ID and
//    password; the root service checks them by joining TDSB-WIFI and, if
//    accepted, creates the account.
//  * Hides the "Not listed?" button under the user list.
//  * "Admin: clear student accounts" (update 0050): with the administrator
//    password, deletes every account except administrator, StudentTest1 and
//    StudentTest2 (root service com.school.ClearAccounts). Logged-in
//    students are logged out first.

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as LoginDialog from 'resource:///org/gnome/shell/gdm/loginDialog.js';
import St from 'gi://St';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

const LOGIN_ID_PATTERN = /^[A-Za-z0-9]{3,27}$/;
const CALL_TIMEOUT_MS = 120000;
const CLEAR_TIMEOUT_MS = 600000;

let panel = null;
let originalShowUserList = null;

function hideNotListed(dialog) {
    dialog?._notListedButton?.hide();
}

function callClearAccounts(method, parameters, replyType, timeout, onReply) {
    let connection = Gio.bus_get_sync(Gio.BusType.SYSTEM, null);

    connection.call(
        'com.school.ClearAccounts',
        '/com/school/ClearAccounts',
        'com.school.ClearAccounts',
        method,
        parameters,
        new GLib.VariantType(replyType),
        Gio.DBusCallFlags.NONE,
        timeout,
        null,
        (conn, result) => {
            let reply = null;
            let failure = null;

            try {
                reply = conn.call_finish(result).deep_unpack();
            } catch (error) {
                failure = error;
            }

            onReply(reply, failure);
        }
    );
}

// Small button under the TDSB panel; opens the administrator password field,
// then shows how many accounts would go and a "Delete them" button.
function addClearAccounts(parent) {
    let toggle = new St.Button({
        label: 'Admin: clear student accounts',
        style_class: 'button',
        style: 'font-size: 10pt; padding: 2px 10px; margin-top: 12px;'
    });

    let box = new St.BoxLayout({ vertical: true, visible: false });

    let adminPassword = new St.PasswordEntry({
        hint_text: 'Administrator password',
        style_class: 'school-account-entry',
        show_peek_icon: true
    });

    let buttons = new St.BoxLayout({ vertical: false });
    let continueButton = new St.Button({ label: 'Continue', style_class: 'button' });
    let cancelButton = new St.Button({ label: 'Cancel', style_class: 'button' });
    buttons.add_child(continueButton);
    buttons.add_child(cancelButton);

    let deleteButton = new St.Button({
        label: 'Delete them',
        style_class: 'button',
        style: 'background-color: #c01c28; color: white;',
        visible: false
    });

    let adminStatus = new St.Label({ text: '' });
    adminStatus.clutter_text.set_line_wrap(true);

    box.add_child(adminPassword);
    box.add_child(buttons);
    box.add_child(adminStatus);
    box.add_child(deleteButton);
    parent.add_child(toggle);
    parent.add_child(box);

    let busy = false;
    let token = '';

    let setBusy = value => {
        busy = value;
        continueButton.reactive = !value;
        cancelButton.reactive = !value;
        deleteButton.reactive = !value;
        toggle.reactive = !value;
    };

    let reset = () => {
        token = '';
        adminPassword.set_text('');
        adminStatus.set_text('');
        deleteButton.hide();
    };

    toggle.connect('clicked', () => {
        if (busy)
            return;
        reset();
        box.visible = !box.visible;
        if (box.visible)
            adminPassword.grab_key_focus();
    });

    cancelButton.connect('clicked', () => {
        if (busy)
            return;
        reset();
        box.hide();
    });

    let check = () => {
        if (busy)
            return;

        let password = adminPassword.get_text();
        adminPassword.set_text('');
        token = '';
        deleteButton.hide();

        if (!password) {
            adminStatus.set_text('Please enter the administrator password.');
            return;
        }

        setBusy(true);
        adminStatus.set_text('Checking…');

        try {
            callClearAccounts('check_admin', new GLib.Variant('(s)', [password]),
                '(bssuu)', CALL_TIMEOUT_MS, (reply, failure) => {
                    setBusy(false);

                    if (failure) {
                        adminStatus.set_text('ERROR: ' + failure.message);
                        return;
                    }

                    let [ok, message, newToken, count, loggedIn] = reply;

                    if (!ok || !newToken) {
                        adminStatus.set_text(message);
                        return;
                    }

                    token = newToken;
                    let text = `This deletes ${count} account${count === 1 ? '' : 's'} ` +
                        'and all their files. It cannot be undone.';
                    if (loggedIn > 0)
                        text += ` ${loggedIn} ${loggedIn === 1 ? 'is' : 'are'} logged in ` +
                            'and will be logged out (unsaved work is lost).';
                    adminStatus.set_text(text);
                    deleteButton.show();
                });
        } catch (error) {
            setBusy(false);
            adminStatus.set_text('ERROR: ' + error.message);
        }
    };

    continueButton.connect('clicked', check);
    adminPassword.clutter_text.connect('activate', check);

    deleteButton.connect('clicked', () => {
        if (busy || !token)
            return;

        let useToken = token;
        token = '';
        deleteButton.hide();
        setBusy(true);
        adminStatus.set_text('Deleting the accounts… this can take a minute.');

        try {
            callClearAccounts('clear_accounts', new GLib.Variant('(s)', [useToken]),
                '(s)', CLEAR_TIMEOUT_MS, (reply, failure) => {
                    setBusy(false);
                    adminStatus.set_text(failure ? 'ERROR: ' + failure.message : reply[0]);
                });
        } catch (error) {
            setBusy(false);
            adminStatus.set_text('ERROR: ' + error.message);
        }
    });
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

        // Same password field as GNOME's own login: hidden text with an eye
        // button to show/hide what was typed.
        let passwordEntry = new St.PasswordEntry({
            hint_text: 'Password',
            style_class: 'school-account-entry',
            show_peek_icon: true
        });

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
        addClearAccounts(panel);

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
