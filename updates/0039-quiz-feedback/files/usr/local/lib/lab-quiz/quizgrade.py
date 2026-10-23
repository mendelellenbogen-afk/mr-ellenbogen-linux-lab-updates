#!/usr/bin/env python3
"""Grading on the laptop (update 0039-quiz-feedback), used by lab-quiz-agent.py
for quizzes the teacher gave with feedback (the practice quiz, 2026-10-23:
"after handing it in students would continue in the exam mode and get
feedback directly overlayed over their quiz answers").

The functions from JAVA_LITERAL to grade_part are exact copies of
tools/labquiz/quizlib.py on the teacher's computer (a test there checks they
stay identical), so a laptop gives the same marks the teacher's grader would.
Only run_java differs: the agent runs as root, so the student's code runs as
the user nobody, without a network (unshare --net), in an empty folder, with
a 20 s limit. The answer key never reaches the student's code: the harness
holds only each test's inputs; the expected answers are compared here.

Testing aid: LAB_QUIZ_GRADE_SANDBOX=0 runs java directly (no root needed).
"""

import json
import os
import re
import shutil
import subprocess
import tempfile

JAVA = os.environ.get("LAB_QUIZ_JAVA", "/usr/bin/java")
SANDBOX = os.environ.get("LAB_QUIZ_GRADE_SANDBOX", "1") != "0"
RUN_SECONDS = 20
NOBODY = 65534


def run_java(source, seconds=RUN_SECONDS):
    """Run a Main.java as nobody, offline. Returns (exit code, stdout, stderr)."""
    work = tempfile.mkdtemp(prefix="lab-quiz-grade-")
    try:
        os.chmod(work, 0o755)
        path = os.path.join(work, "Main.java")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(source)
        os.chmod(path, 0o644)
        java = [JAVA, "-Xmx256m", "-XX:TieredStopAtLevel=1", "Main.java"]
        if SANDBOX:
            command = ["/usr/bin/unshare", "--net", "--", "/usr/bin/setpriv", f"--reuid={NOBODY}",
                       f"--regid={NOBODY}", "--clear-groups", "--inh-caps=-all", "--",
                       "/usr/bin/env", "-i", "HOME=/tmp", "PATH=/usr/bin:/bin", "LANG=C.UTF-8", *java]
        else:
            command = java
        try:
            done = subprocess.run(command, cwd=work, capture_output=True, text=True, timeout=seconds,
                                  stdin=subprocess.DEVNULL)
            return done.returncode, done.stdout, done.stderr
        except subprocess.TimeoutExpired:
            return 124, "", f"Stopped after {seconds} s (endless loop?)"
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------- copied from quizlib.py (keep identical)

JAVA_LITERAL = {"int": lambda v: str(int(v)), "double": lambda v: repr(float(v)),
                "boolean": lambda v: "true" if v else "false"}


def clean_condition(text):
    """Accept `if (cond) {`, `cond;`, `(cond)`: return the bare expression."""
    text = text.strip()
    text = re.sub(r"^if\s*", "", text)
    text = re.sub(r"[{;\s]+$", "", text)
    return text or "false"


def clean_statements(text, inputs, output):
    """Drop the student's re-declarations of the given variables (`int age = 30;`)
    and the `int price;` declaration (the harness declares it); keep
    `int price = 0;` as `price = 0;`."""
    for _type, name in inputs:
        text = re.sub(rf"\b(?:int|double|boolean|var)\s+{name}\s*(?:=[^;]*)?;", "", text)
    if output:
        name = output[1]
        text = re.sub(rf"\b(?:int|double|boolean|var)\s+{name}\s*;", "", text)
        text = re.sub(rf"\b(?:int|double|boolean|var)\s+{name}\s*=", f"{name} =", text)
    return text


def harness(grader, answer):
    """A Main.java that runs the answer on every case and prints one line each."""
    if grader["kind"] == "condition":
        params = ", ".join(f"{t} {n}" for t, n in grader["params"])
        body = f"        return ({clean_condition(answer)});\n"
        signature = f"static boolean check({params})"
        call = lambda inputs: "String.valueOf(check(" + ", ".join(
            JAVA_LITERAL[t](v) for (t, _n), v in zip(grader["params"], inputs)) + "))"
        method = f"    {signature} {{\n{body}    }}\n"
    else:
        params = ", ".join(f"{t} {n}" for t, n in grader["inputs"])
        out_type, out_name = grader["output"]
        printing = (f"        System.out.print(\"\\u0001\" + {grader['print']});\n" if grader.get("print") else "")
        method = (f"    static void body({params}) {{\n"
                  f"        {out_type} {out_name};\n"
                  f"// ---- student code\n{clean_statements(main_body(answer), grader['inputs'], grader['output'])}\n"
                  f"// ---- end\n{printing}"
                  f"    }}\n"
                  f"    static String check({params}) {{\n"
                  f"        java.io.PrintStream old = System.out;\n"
                  f"        java.io.ByteArrayOutputStream buffer = new java.io.ByteArrayOutputStream();\n"
                  f"        System.setOut(new java.io.PrintStream(buffer, true));\n"
                  f"        try {{ body({', '.join(n for _t, n in grader['inputs'])}); }}\n"
                  f"        catch (Throwable problem) {{ System.out.print(\"\\u0002\" + problem); }}\n"
                  f"        finally {{ System.setOut(old); }}\n"
                  f"        return buffer.toString();\n"
                  f"    }}\n")
        call = lambda inputs: "check(" + ", ".join(
            JAVA_LITERAL[t](v) for (t, _n), v in zip(grader["inputs"], inputs)) + ")"
    lines = "".join(f"        report({index}, {call(case['inputs'])});\n" for index, case in enumerate(grader["cases"]))
    return ("public class Main {\n" + method +
            "    static void report(int index, String result) {\n"
            "        System.out.println(\"\\u0003\" + index + \"\\u0004\" + result.replace(\"\\n\", \"\\\\n\"));\n"
            "    }\n"
            "    public static void main(String[] args) {\n" + lines + "    }\n}\n")


def program_harness(grader, answer):
    """A Main.java whose first class runs the student's whole program once per
    case, with that case's text as the keyboard input, and prints one line each."""
    lines = answer.splitlines()
    head = []
    while lines and re.match(r"\s*(import\s+[\w.*\s]+;|package\s+[\w.]+;|//.*)?\s*$", lines[0]):
        line = lines.pop(0)
        if not line.strip().startswith("package"):
            head.append(line)
    rest = "\n".join(lines)
    if not re.search(r"\bclass\s+\w+", rest):                   # just the inside of main
        rest = f"class Main {{\n    public static void main(String[] args) {{\n{rest}\n    }}\n}}\n"
        head.append("import java.util.*;")
    rest = re.sub(r"\bpublic\s+((?:final\s+|abstract\s+)?class\b)", r"\1", rest)
    name = re.search(r"\bclass\s+(\w+)", rest).group(1)
    inputs = ", ".join(json.dumps(case["stdin"] + "\n") for case in grader["cases"])
    runner = ("class LabQuizRunner {\n"
              "    public static void main(String[] args) {\n"
              f"        String[] inputs = {{{inputs}}};\n"
              "        java.io.PrintStream old = System.out;\n"
              "        for (int i = 0; i < inputs.length; i++) {\n"
              "            java.io.ByteArrayOutputStream buffer = new java.io.ByteArrayOutputStream();\n"
              "            System.setOut(new java.io.PrintStream(buffer, true));\n"
              "            System.setIn(new java.io.ByteArrayInputStream(inputs[i].getBytes()));\n"
              f"            try {{ {name}.main(new String[0]); }}\n"
              "            catch (Throwable problem) { System.out.print(\"\\u0002\" + problem); }\n"
              "            finally { System.setOut(old); }\n"
              "            old.println(\"\\u0003\" + i + \"\\u0004\" + buffer.toString().replace(\"\\n\", \"\\\\n\"));\n"
              "        }\n"
              "    }\n"
              "}\n")
    return "\n".join(head) + "\n" + runner + rest + "\n"


def main_body(program):
    """The inside of main() if the answer is a whole program, else the answer."""
    match = re.search(r"static\s+void\s+main\s*\([^)]*\)\s*(?:throws[^{]*)?\{", program)
    if not match:
        return program
    depth, start = 1, match.end()
    for index in range(start, len(program)):
        if program[index] == "{":
            depth += 1
        elif program[index] == "}":
            depth -= 1
            if depth == 0:
                return program[start:index]
    return program[start:]


def compile_error(stderr):
    """The javac-style lines from `java Main.java`, with harness line numbers removed."""
    lines = [line for line in stderr.splitlines() if "error:" in line or line.strip().startswith("^")]
    return re.sub(r"Main\.java:\d+: ", "", "\n".join(lines[:6])) or stderr.strip()[:400]


def suggested_marks(marks, passed, total):
    if total == 0:
        return 0
    share = passed / total
    if share == 1:
        return marks
    if share >= 0.75:
        return max(0, marks - 1)
    if share >= 0.5 and marks >= 3:
        return marks - 2
    return 0


def same_number(got, want):
    try:
        return abs(float(got) - float(want)) < 1e-9
    except ValueError:
        return got == want


def grade_part(part, answer):
    """{"suggested": marks or None (manual), "summary": text, "details": [...]}"""
    grader = part.get("grader")
    answer = answer or ""
    if not grader:
        return {"suggested": None, "summary": "Mark by hand.", "details": []}
    if not answer.strip():
        return {"suggested": 0, "summary": "No answer.", "details": []}
    if grader["kind"] == "choice":
        chosen = answer.strip().lower()
        if chosen == grader["answer"].lower():
            return {"suggested": part["marks"], "summary": "Right.", "details": []}
        return {"suggested": 0, "summary": f"Wrong (chose {answer.strip()}, key {grader['answer']}).", "details": []}
    if grader["kind"] == "output":
        want = grader["expect"].strip().splitlines()
        got = [line.rstrip() for line in answer.strip().splitlines()]
        right = sum(1 for index, line in enumerate(want) if index < len(got) and got[index].strip() == line.strip())
        extra = max(0, len(got) - len(want))
        marks = min(part["marks"], right) if not extra else max(0, min(part["marks"], right) - 1)
        return {"suggested": marks, "summary": f"{right} of {len(want)} lines exactly right"
                + (f", {extra} extra line(s)" if extra else ""), "details": []}

    source = program_harness(grader, answer) if grader["kind"] == "program" else harness(grader, answer)
    code, out, err = run_java(source)
    results = {}
    for line in out.splitlines():
        if line.startswith("\u0003") and "\u0004" in line:
            index, value = line[1:].split("\u0004", 1)
            results[int(index)] = value.replace("\\n", "\n")
    if not results:
        problem = compile_error(err) if err else "It printed nothing."
        return {"suggested": 0, "summary": "Doesn't compile or run.", "details": [problem]}
    passed, failures = 0, []
    for index, case in enumerate(grader["cases"]):
        got = results.get(index, "")
        if "\u0002" in got:
            value = "error: " + got.split("\u0002", 1)[1]
        elif grader.get("expect_number"):
            numbers = re.findall(r"-?\d+(?:\.\d+)?", got)
            value = numbers[-1] if numbers else "(no number printed)"
            if value.endswith(".0"):
                value = value[:-2]
        elif "\u0001" in got:
            value = got.split("\u0001")[-1].strip()
        else:
            value = got.strip()
        if value == case["expect"] or (grader.get("expect_number") and same_number(value, case["expect"])):
            passed += 1
        else:
            if grader["kind"] == "program":
                shown = f"input {case['stdin']}"
            else:
                names = grader.get("params") or grader.get("inputs")
                shown = ", ".join(f"{n}={JAVA_LITERAL[t](v)}" for (t, n), v in zip(names, case["inputs"]))
            failures.append(f"{shown}: expected {case['expect']}, got {value}")
    total = len(grader["cases"])
    return {"suggested": suggested_marks(part["marks"], passed, total),
            "summary": f"Passed {passed} of {total} tests", "details": failures[:5]}
