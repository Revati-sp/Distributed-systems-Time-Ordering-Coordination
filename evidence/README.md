# Evidence

`terminal-output.txt` contains the real, unedited output of the demo, the test suite and a compile check, captured from a terminal run. No screenshots are included; terminal output is the evidence.

It was generated from the repository root with Python 3.9.6 on macOS, using the commands from the main README:

```bash
python3 run_demo.py
python3 -m unittest discover -s tests -v
python3 -m compileall .
```

All three commands exited with code `0`. The demo printed `[PASS]` for every check, and all 38 tests passed.

About the `compileall` output:

- It also lists the `.git` directories, because the command scans the whole repository folder.
- It prints "Compiling" only for `run_demo.py`. The demo and the tests had just imported every other module, so Python had already cached them as up-to-date bytecode, and `compileall` skipped them.

The output is deterministic, so a new run produces the same text. The only exceptions are the test runtime on the `Ran 38 tests in ...s` line and the `.git` object folders listed by `compileall`.
