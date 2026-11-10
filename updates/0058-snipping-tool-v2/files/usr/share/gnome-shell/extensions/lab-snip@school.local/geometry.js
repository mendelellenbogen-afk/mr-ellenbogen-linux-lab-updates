// Geometry uses logical stage coordinates until toPixels().
export function clampRect(rect, bounds) {
    const x = Math.max(bounds.x, Math.min(rect.x, bounds.x + bounds.width));
    const y = Math.max(bounds.y, Math.min(rect.y, bounds.y + bounds.height));
    const right = Math.max(x, Math.min(rect.x + rect.width, bounds.x + bounds.width));
    const bottom = Math.max(y, Math.min(rect.y + rect.height, bounds.y + bounds.height));
    return {x, y, width: right - x, height: bottom - y};
}

export function contains(rect, x, y) {
    return x >= rect.x && y >= rect.y &&
        x < rect.x + rect.width && y < rect.y + rect.height;
}

// The pointer stops one pixel short of a screen's right/bottom edge, so a point on that
// last pixel (or beyond it) counts as the edge itself: dragging into a corner takes it all.
function snapToEdge(point, monitor) {
    const right = monitor.x + monitor.width;
    const bottom = monitor.y + monitor.height;
    return {x: point.x >= right - 1 ? right : point.x, y: point.y >= bottom - 1 ? bottom : point.y};
}

export function dragRect(start, end, monitor) {
    start = snapToEdge(start, monitor);
    end = snapToEdge(end, monitor);
    return clampRect({x: Math.min(start.x, end.x), y: Math.min(start.y, end.y),
        width: Math.abs(end.x - start.x), height: Math.abs(end.y - start.y)}, monitor);
}

export function padRect(rect, padding, monitor) {
    return clampRect({x: rect.x - padding, y: rect.y - padding,
        width: rect.width + padding * 2, height: rect.height + padding * 2}, monitor);
}

export function isClick(start, end) {
    return Math.hypot(end.x - start.x, end.y - start.y) <= 3;
}

export function windowAt(windows, x, y) {
    return windows.find(window => contains(window.rect, x, y)) ?? null;
}

export function toPixels(rect, scale, width, height, origin = {x: 0, y: 0}) {
    const x = Math.max(0, Math.min(width, Math.round((rect.x - origin.x) * scale)));
    const y = Math.max(0, Math.min(height, Math.round((rect.y - origin.y) * scale)));
    const right = Math.max(x, Math.min(width,
        Math.round((rect.x + rect.width - origin.x) * scale)));
    const bottom = Math.max(y, Math.min(height,
        Math.round((rect.y + rect.height - origin.y) * scale)));
    return {x, y, width: right - x, height: bottom - y};
}
