import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import St from 'gi://St';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import {contains, dragRect, padRect, isClick, windowAt, toPixels} from './geometry.js';

Gio._promisify(Shell.Screenshot.prototype, 'screenshot_stage_to_content');
Gio._promisify(Shell.Screenshot, 'composite_to_stream');

const INTERFACE = `<node><interface name="org.school.LabSnip">
<method name="Start"/></interface></node>`;

class Overlay {
    constructor(done) {
        this.done = done;
        this.closed = false;
        this.monitors = Main.layoutManager.monitors.map(m =>
            ({x: m.x, y: m.y, width: m.width, height: m.height}));
    }

    async open() {
        try {
            const workspace = global.workspace_manager.get_active_workspace();
            this.windows = global.display.sort_windows_by_stacking(workspace.list_windows())
                .reverse().filter(w => w.get_window_type() === Meta.WindowType.NORMAL &&
                    !w.skip_taskbar && !w.minimized && w.showing_on_its_workspace())
                .map(w => {
                    const r = w.get_frame_rect();
                    return {rect: {x: r.x, y: r.y, width: r.width, height: r.height},
                        monitor: this.monitors[w.get_monitor()]};
                });
            this.shooter = new Shell.Screenshot();
            const [content, scale] = await this.shooter.screenshot_stage_to_content();
            if (this.closed)
                return;
            this.content = content;
            this.scale = scale;
            this.actor = new St.Widget({reactive: true, can_focus: true,
                width: global.stage.width, height: global.stage.height});
            this.picture = new Clutter.Actor({content,
                width: global.stage.width, height: global.stage.height});
            this.actor.add_child(this.picture);
            // Four dimming panels leave the selected area completely clear.
            this.shades = Array.from({length: 4}, () => this.box('background-color: rgba(0,0,0,0.4);'));
            this.highlight = this.box('background-color: rgba(53,132,228,0.3); border: 2px solid rgb(53,132,228);');
            this.border = this.box('border: 1px solid white;');
            this.handles = Array.from({length: 4}, () => this.box('background-color: white;'));
            this.horizontal = this.box('background-color: rgba(255,255,255,0.8);');
            this.vertical = this.box('background-color: rgba(255,255,255,0.8);');
            this.actor.connect('event', (_actor, event) => {
                try {
                    return this.event(event);
                } catch (error) {
                    this.fail(error);
                    return Clutter.EVENT_STOP;
                }
            });
            this.monitorSignal = Main.layoutManager.connect('monitors-changed', () => this.close());
            Main.layoutManager.emit('system-modal-opened');
            const group = Main.layoutManager.screenshotUIGroup;
            group.get_parent().set_child_above_sibling(group, null);
            group.add_child(this.actor);
            this.grab = Main.pushModal(this.actor, {actionMode: Shell.ActionMode.SCREENSHOT});
            this.actor.set_cursor_type(Clutter.CursorType.CROSSHAIR);
            this.actor.grab_key_focus();
            const [x, y] = global.get_pointer();
            this.draw(null, x, y);
        } catch (error) {
            this.fail(error);
        }
    }

    box(style) {
        const actor = new St.Widget({style, reactive: false});
        this.actor.add_child(actor);
        return actor;
    }

    place(actor, rect) {
        actor.set_position(rect.x, rect.y);
        actor.set_size(rect.width, rect.height);
        actor.visible = rect.width > 0 && rect.height > 0;
    }

    draw(rect, x, y) {
        const w = this.actor.width;
        const h = this.actor.height;
        const r = rect ?? {x: 0, y: 0, width: 0, height: 0};
        const right = r.x + r.width;
        const bottom = r.y + r.height;
        const panels = [
            {x: 0, y: 0, width: w, height: r.y},
            {x: 0, y: bottom, width: w, height: h - bottom},
            {x: 0, y: r.y, width: r.x, height: r.height},
            {x: right, y: r.y, width: w - right, height: r.height},
        ];
        panels.forEach((panel, i) => this.place(this.shades[i], panel));
        this.place(this.border, r);
        [[r.x, r.y], [right, r.y], [r.x, bottom], [right, bottom]].forEach(([hx, hy], i) => {
            this.place(this.handles[i], {x: hx - 2, y: hy - 2, width: 4, height: 4});
            this.handles[i].visible = Boolean(rect);
        });
        this.place(this.horizontal, {x: 0, y, width: w, height: 1});
        this.place(this.vertical, {x, y: 0, width: 1, height: h});
        this.horizontal.visible = !this.start;
        this.vertical.visible = !this.start;
        const hovered = this.start ? null : windowAt(this.windows, x, y);
        this.highlight.visible = Boolean(hovered);
        if (hovered)
            this.place(this.highlight, hovered.rect);
    }

    event(event) {
        if (this.closed)    // late events (e.g. pointer leaving) after the overlay closed
            return Clutter.EVENT_PROPAGATE;
        const type = event.type();
        if (type === Clutter.EventType.KEY_PRESS && event.get_key_symbol() === Clutter.KEY_Escape) {
            this.close();
            return Clutter.EVENT_STOP;
        }
        const [x, y] = event.get_coords();
        const point = {x, y};
        if (type === Clutter.EventType.BUTTON_PRESS && [1, 3].includes(event.get_button()) && !this.start) {
            this.monitor = this.monitors.find(m => contains(m, x, y));
            if (this.monitor) {
                this.start = point;
                this.clickedWindow = windowAt(this.windows, x, y);
                this.moved = false;
            }
        }
        if (type === Clutter.EventType.MOTION && this.start)
            this.moved ||= !isClick(this.start, point);
        if (type === Clutter.EventType.BUTTON_RELEASE && this.start && [1, 3].includes(event.get_button())) {
            this.moved ||= !isClick(this.start, point);
            let rect = dragRect(this.start, point, this.monitor);
            if (!this.moved) {
                const win = this.clickedWindow;
                rect = win ? padRect(win.rect, 5, win.monitor ?? this.monitor) : null;
            }
            this.start = null;
            if (rect && rect.width >= 4 && rect.height >= 4) {
                const content = this.content;
                const scale = this.scale;
                const button = event.get_button();
                this.close();
                this.capture(content, scale, rect, button).catch(error => console.error(error));
                return Clutter.EVENT_STOP;
            }
        }
        this.draw(this.start ? dragRect(this.start, point, this.monitor) : null, x, y);
        return Clutter.EVENT_STOP;
    }

    async capture(content, scale, rect, button) {
        const texture = content.get_texture();
        const crop = toPixels(rect, scale, texture.get_width(), texture.get_height());
        const stream = Gio.MemoryOutputStream.new_resizable();
        try {
            await Shell.Screenshot.composite_to_stream(texture,
                crop.x, crop.y, crop.width, crop.height, scale, null, 0, 0, 1, stream);
        } finally {
            stream.close(null);
        }
        const bytes = stream.steal_as_bytes();
        if (this.disabled)
            return;
        if (button === 3) {
            St.Clipboard.get_default().set_content(St.ClipboardType.CLIPBOARD, 'image/png', bytes);
            return;
        }
        const runtime = GLib.getenv('XDG_RUNTIME_DIR');
        if (!runtime)
            throw new Error('XDG_RUNTIME_DIR is unavailable');
        const directory = GLib.build_filenamev([runtime, 'lab-snip']);
        if (GLib.mkdir_with_parents(directory, 0o700) !== 0)
            throw new Error('Cannot create screenshot directory');
        const dir = Gio.File.new_for_path(directory);
        const info = dir.query_info('standard::type,unix::uid', Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, null);
        if (info.get_file_type() !== Gio.FileType.DIRECTORY || info.get_attribute_uint32('unix::uid') !== new Gio.Credentials().get_unix_user())
            throw new Error('Unsafe screenshot directory');
        dir.set_attribute_uint32('unix::mode', 0o700, Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, null);
        const path = GLib.build_filenamev([directory, `snip-${Date.now()}.png`]);
        const file = Gio.File.new_for_path(path);
        const output = file.create(Gio.FileCreateFlags.PRIVATE, null);
        try {
            output.write_all(bytes.get_data(), null);
            output.close(null);
            Gio.Subprocess.new(['/usr/local/bin/lab-snip', '--edit', path], Gio.SubprocessFlags.NONE);
        } catch (error) {
            if (!output.is_closed())
                output.close(null);
            file.delete(null);
            throw error;
        }
    }

    fail(error) {
        this.close();
        console.error(error);
    }

    close() {
        if (this.closed)
            return;
        this.closed = true;
        try {
            if (this.monitorSignal)
                Main.layoutManager.disconnect(this.monitorSignal);
            if (this.grab)
                Main.popModal(this.grab);
            this.grab = null;
            this.picture?.set_content(null);
            this.picture = null;
            this.actor?.destroy();
        } catch (error) {
            console.error(error);
        } finally {
            // Always let go, so a failure can never leave the screen grabbed.
            this.shades = [];
            this.handles = [];
            this.highlight = null;
            this.border = null;
            this.horizontal = null;
            this.vertical = null;
            this.actor = null;
            this.content = null;
            this.shooter = null;
            this.windows = [];
            this.done();
        }
    }
}

export default class LabSnip extends Extension {
    enable() {
        this._dbus = Gio.DBusExportedObject.wrapJSObject(INTERFACE, {
            Start: () => {
                if (this._overlay)
                    return;
                const overlay = new Overlay(() => {
                    if (this._overlay === overlay)
                        this._overlay = null;
                });
                this._overlay = overlay;
                overlay.open();
            },
        });
        this._dbus.export(Gio.DBus.session, '/org/school/LabSnip');
    }

    disable() {
        this._dbus?.unexport();
        this._dbus = null;
        if (this._overlay) {
            this._overlay.disabled = true;
            this._overlay.close();
        }
        this._overlay = null;
    }
}
