"""Particle (josa) allomorph agreement for Super Sejong Engine v2 (DESIGN.md 3.7 step 4, 5.1).

The v1 API unchanged: check(text, lexicon=None, min_conf='likely'), gate(source, output, ...),
repair(text, findings), Lexicon.load(path=None), Finding. The implementation stays in
engine_runtime/super_sejong_josa.py for now and every name of it is re-bound here, so
`sejong.josa.X is super_sejong_josa.X`.

Why this direction (WP-8): DESIGN 4.3 makes super_sejong_josa.py a re-export of sejong.josa, but the
legacy restore step (python-engine.ts runs super_sejong_josa.py as a script) and workflow.py would then
import the v2 package, which the WP-0 contract forbids while legacy is the default engine
(test_sejong_contracts.NoRuntimeWiring; "the legacy path never imports this package" in __init__.py).
Flip the direction when the legacy engine is removed (WP-18): move the file here and leave a shim there.
"""
from __future__ import annotations

try:                                   # imported as engine_runtime.sejong.josa
    from .. import super_sejong_josa as _impl
except (ImportError, ValueError):      # imported as sejong.josa with engine_runtime/ on sys.path
    import super_sejong_josa as _impl  # type: ignore[no-redef]

globals().update({name: value for name, value in vars(_impl).items()
                  if not (name.startswith("__") and name.endswith("__"))})
