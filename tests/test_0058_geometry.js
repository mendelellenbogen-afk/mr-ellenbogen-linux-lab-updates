// Geometry tests for the lab-snip add-on (0058). test_0058_snipping_tool_v2.py copies this file
// next to the add-on's geometry.js and runs it with gjs -m.
import {clampRect, contains, dragRect, padRect, isClick, windowAt, toPixels} from './geometry.js';

let failures = 0;
function check(name, actual, expected) {
    const pass = JSON.stringify(actual) === JSON.stringify(expected);
    print(`${pass ? 'PASS' : 'FAIL'} ${name}`);
    if (!pass) {
        print(`  got ${JSON.stringify(actual)}, expected ${JSON.stringify(expected)}`);
        failures++;
    }
}
const monitor = {x: 1920, y: 0, width: 1280, height: 1024};
check('reverse drag clamps to starting monitor',
    dragRect({x: 2000, y: 100}, {x: 1800, y: -50}, monitor),
    {x: 1920, y: 0, width: 80, height: 100});
check('pointer on the last pixel reaches the corner',
    dragRect({x: 3000, y: 900}, {x: 3199, y: 1023}, monitor),
    {x: 3000, y: 900, width: 200, height: 124});
check('pointer inside stays where it is',
    dragRect({x: 3000, y: 900}, {x: 3198, y: 1022}, monitor),
    {x: 3000, y: 900, width: 198, height: 122});
check('padding at monitor edge', padRect({x: 1920, y: 0, width: 100, height: 100}, 5, monitor),
    {x: 1920, y: 0, width: 105, height: 105});
check('outside rectangle has no area', clampRect({x: 4000, y: 2000, width: 20, height: 20}, monitor),
    {x: 3200, y: 1024, width: 0, height: 0});
check('monitor boundary is exclusive', contains(monitor, 3200, 100), false);
check('three pixels is a click', isClick({x: 0, y: 0}, {x: 3, y: 0}), true);
check('diagonal distance counts', isClick({x: 0, y: 0}, {x: 3, y: 3}), false);
const front = {rect: {x: 0, y: 0, width: 100, height: 100}, id: 'front'};
const back = {rect: {x: 0, y: 0, width: 200, height: 200}, id: 'back'};
check('topmost window wins', windowAt([front, back], 50, 50), front);
check('empty point', windowAt([front, back], 300, 300), null);
check('fractional scale on second monitor',
    toPixels({x: 1920, y: 10, width: 101, height: 51}, 1.25, 4000, 2000),
    {x: 2400, y: 13, width: 126, height: 63});
check('physical texture bounds',
    toPixels({x: -10, y: -10, width: 110, height: 110}, 2, 150, 150),
    {x: 0, y: 0, width: 150, height: 150});
check('explicit stage origin',
    toPixels({x: -100, y: 0, width: 20, height: 20}, 2, 400, 400, {x: -100, y: 0}),
    {x: 0, y: 0, width: 40, height: 40});
if (failures)
    throw new Error(`${failures} geometry tests failed`);
