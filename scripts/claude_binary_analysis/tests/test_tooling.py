from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


TOOLS = Path(__file__).resolve().parents[1]


class BinaryToolingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_cmd(
        self,
        *args: str | Path,
        check: bool = True,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(arg) for arg in args],
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=check,
        )

    def test_index_classifies_serialized_duplicate_and_primary_bundle(self) -> None:
        anchor = b"has conflicting manifests"
        serialized = b"\x00\x00\x10\x00" + anchor + b"\x00" * 32
        application = (
            b"// @bun @bytecode @bun-cjs\n(function(){const a='"
            + anchor
            + b"';const b='installed_plugins.json';const c='enabledPlugins';return {a,b,c};})();\n"
        )
        payload = self.root / "payload.bin"
        payload.write_bytes(serialized + application + b"Bun! ----")
        output = self.root / "index"
        self.run_cmd(
            TOOLS / "index_payload.py",
            payload,
            output,
            "--long-run",
            "64",
        )
        representations = json.loads((output / "representations.json").read_text())
        self.assertEqual(
            representations["classification_status"],
            "primary-application-representation-identified",
        )
        conflict = next(
            group
            for group in representations["distinctive_anchor_groups"]
            if group["anchor"] == anchor.decode()
        )
        self.assertEqual(
            [item["classification"] for item in conflict["occurrences"]],
            ["serialized-runtime-or-heap-data", "executable-minified-bundle-candidate"],
        )

    def test_carve_is_offset_preserving_and_immutable(self) -> None:
        payload = self.root / "payload.bin"
        payload.write_bytes(b"prefix-TARGET-suffix")
        output = self.root / "segment.js"
        self.run_cmd(
            TOOLS / "carve_segment.py",
            payload,
            output,
            "--start",
            "7",
            "--end",
            "13",
            "--topic",
            "fixture",
        )
        self.assertEqual(output.read_bytes(), b"TARGET")
        sidecar = json.loads((self.root / "segment.js.json").read_text())
        self.assertEqual(sidecar["segment"]["start"], 7)
        self.assertEqual(sidecar["segment"]["end_exclusive"], 13)
        output.write_bytes(b"changed")
        result = self.run_cmd(
            TOOLS / "carve_segment.py",
            payload,
            output,
            "--start",
            "7",
            "--end",
            "13",
            "--topic",
            "fixture",
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_extracts_injected_bun_section_from_local_elf_fixture(self) -> None:
        cc = shutil.which("cc")
        objcopy = shutil.which("objcopy")
        if not cc or not objcopy:
            self.skipTest("C compiler and objcopy are required")
        source = self.root / "fixture.c"
        source.write_text(
            '#include <string.h>\n#include <stdio.h>\nint main(int n,char **v){puts(n>1 && strcmp(v[1],"--version")==0 ? "fixture 1" : "ok");}\n'
        )
        executable = self.root / "fixture"
        self.run_cmd(cc, source, "-o", executable)
        section = self.root / "section.bin"
        section.write_bytes(b"// @bun fixture\nconsole.log('fixture')\nBun! ----")
        with_section = self.root / "fixture-with-section"
        self.run_cmd(
            objcopy,
            "--add-section",
            f".bun={section}",
            "--set-section-flags",
            ".bun=alloc,load,data",
            executable,
            with_section,
        )
        with_section.chmod(0o755)
        source_hash = hashlib.sha256(with_section.read_bytes()).hexdigest()
        analysis = self.root / "analysis"
        self.run_cmd(TOOLS / "inspect_binary.sh", with_section, analysis)
        self.run_cmd(TOOLS / "extract_bun_section.sh", analysis)
        self.assertEqual(
            hashlib.sha256((analysis / "input" / "claude").read_bytes()).hexdigest(),
            source_hash,
        )
        # A second extraction must be an idempotent hash check, not a rewrite.
        self.run_cmd(TOOLS / "extract_bun_section.sh", analysis)
        extracted = analysis / "payload" / "bun-section.bin"
        self.assertEqual(extracted.read_bytes(), section.read_bytes())
        manifest = json.loads((analysis / "manifest" / "binary.json").read_text())
        self.assertEqual(
            manifest["bun_section"]["sha256"],
            hashlib.sha256(section.read_bytes()).hexdigest(),
        )

    def test_locally_compiled_bun_standalone_when_bun_is_available(self) -> None:
        bun = os.environ.get("BUN_BIN") or shutil.which("bun")
        if not bun:
            self.skipTest("set BUN_BIN to exercise a locally installed Bun compiler")
        fixture = Path(__file__).parent / "fixtures" / "tiny-plugin.js"
        executable = self.root / "tiny-bun"
        self.run_cmd(
            bun,
            "build",
            str(fixture),
            "--compile",
            "--outfile",
            executable,
            cwd=self.root,
        )
        analysis = self.root / "bun-analysis"
        self.run_cmd(TOOLS / "inspect_binary.sh", executable, analysis)
        self.run_cmd(TOOLS / "extract_bun_section.sh", analysis)
        manifest = json.loads((analysis / "manifest" / "binary.json").read_text())
        self.assertGreater(manifest["bun_section"]["size"], 0)

    def test_formatter_requires_pinned_version_and_preserves_output(self) -> None:
        formatter = self.root / "prettier-fixture"
        formatter.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = --version ]; then echo 3.6.2; exit 0; fi\n"
            "for last; do :; done\n"
            "cat \"$last\"\n"
        )
        formatter.chmod(0o755)
        source = self.root / "segment.js"
        source.write_text("function fixture(){return true;}\n")
        output = self.root / "formatted.js"
        self.run_cmd(TOOLS / "format_segment.sh", source, output, formatter)
        self.assertEqual(output.read_text(), source.read_text())
        bad = self.root / "wrong-version"
        bad.write_text("#!/bin/sh\necho 3.6.1\n")
        bad.chmod(0o755)
        result = self.run_cmd(
            TOOLS / "format_segment.sh",
            source,
            self.root / "bad.js",
            bad,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_claim_validator_enforces_runtime_evidence(self) -> None:
        ledger = self.root / "claims.json"
        ledger.write_text(
            json.dumps(
                {
                    "claims": [
                        {
                            "id": "missing-runtime",
                            "claim": "fixture claim",
                            "binary": {"version": "1", "sha256": "abc"},
                            "bundle": {"offsets": [1], "anchors": ["a"]},
                            "old_source": {"files": ["x.ts"]},
                            "runtime": {"runs": []},
                            "verdict": "runtime-confirmed",
                        }
                    ]
                }
            )
        )
        result = self.run_cmd(TOOLS / "validate_claims.py", ledger, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires runtime runs", result.stderr)

    def test_commit_safety_rejects_raw_analysis_path(self) -> None:
        result = self.run_cmd(
            TOOLS / "check_commit_safety.py",
            "--root",
            self.root,
            "tmp/claude-code-binary-analysis/2.1.214/payload/bun-section.bin",
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("raw analysis workspace", result.stderr)


if __name__ == "__main__":
    unittest.main()
