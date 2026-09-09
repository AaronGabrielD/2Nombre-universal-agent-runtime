# M23 — Execution Admission Policy

M23 adds a static Python admission policy to the Colab execution service as defense-in-depth.

The default `RUNTIME_PYTHON_POLICY=restricted` mode parses submitted Python with the standard-library `ast` module and blocks common process-spawn, network, dynamic-code, and low-level escape primitives such as `subprocess`, `socket`, `os`, `ctypes`, `eval`, `exec`, and `__import__`.

The service still executes inside the Colab VM with `shell=False`, a reduced environment, a bounded subprocess timeout, bounded output, and the existing network admission flag. None of these controls should be interpreted as a strong sandbox against adversarial Python. A future isolation milestone should use a stronger OS/container boundary where available.

`RUNTIME_PYTHON_POLICY=unsafe` exists only as an explicit compatibility escape hatch for trusted development environments and should not be used for exposed production services.
