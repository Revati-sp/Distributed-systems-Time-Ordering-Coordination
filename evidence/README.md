# Evidence

`terminal-output.txt` contains the real, unedited output of the demo, the test suite and a compile check, captured from a terminal run. No screenshots are included; terminal output is the evidence.

It was generated from the repository root with Python 3.9.6 on macOS. On that machine, only `python3` is available (there is no `python` command):

```bash
python3 run_demo.py
python3 -m unittest discover -s tests -v
python3 -m compileall .
```

All three commands exited with code `0`.

The `compileall` output prints "Compiling" only for `run_demo.py`. The demo and the tests had just imported the other modules, so Python had already cached them as up-to-date bytecode, and `compileall` skipped them. Any syntax error would still make the earlier commands fail.

The output is deterministic, so a new run produces the same text. The only exception is the test runtime shown on the `Ran 32 tests in ...s` line.
