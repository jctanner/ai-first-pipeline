import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import src.dashboard.openshell_orchestrator as openshell_module
from src.dashboard.openshell_orchestrator import OpenShellOrchestrator


class FakeWorkspaceClient:
    def get(self, _workspace):
        return object()

    def create(self, _workspace, labels=None):
        return None

    @classmethod
    def from_sandbox_client(cls, _client):
        return cls()


class FakeSandboxClient:
    def __init__(self, result):
        self.result = result
        self.deleted = []
        self.waited = []
        self.closed = False

    def create(self, **_kwargs):
        return SimpleNamespace(id="sandbox-id", name="bb-os-test")

    def wait_ready(self, *_args, **_kwargs):
        return None

    def exec(self, *_args, **_kwargs):
        return self.result

    def delete(self, name, *, workspace):
        self.deleted.append((name, workspace))
        return True

    def wait_deleted(self, name, *, workspace, timeout_seconds):
        self.waited.append((name, workspace, timeout_seconds))

    def close(self):
        self.closed = True


class OpenShellCleanupTests(unittest.TestCase):
    def _orchestrator(self, root: Path, name: str):
        orchestrator = OpenShellOrchestrator.__new__(OpenShellOrchestrator)
        orchestrator.ARTIFACTS_ROOT = root
        orchestrator._jobs = {name: {"name": name, "status": "pending"}}
        return orchestrator

    def test_delete_sandbox_waits_for_backing_resources(self):
        orchestrator = OpenShellOrchestrator.__new__(OpenShellOrchestrator)
        client = FakeSandboxClient(SimpleNamespace())

        self.assertTrue(orchestrator._delete_sandbox(client, "bb-os-test"))
        self.assertEqual(client.deleted, [("bb-os-test", orchestrator.WORKSPACE)])
        self.assertEqual(
            client.waited,
            [("bb-os-test", orchestrator.WORKSPACE, 60.0)],
        )

    def test_run_cleans_up_after_command_failure(self):
        name = "bb-os-test"
        result = SimpleNamespace(exit_code=17, stdout="stdout", stderr="stderr")
        client = FakeSandboxClient(result)

        with tempfile.TemporaryDirectory() as directory:
            orchestrator = self._orchestrator(Path(directory), name)
            with (
                mock.patch.object(openshell_module, "SandboxClient", return_value=client),
                mock.patch.object(openshell_module, "WorkspaceClient", FakeWorkspaceClient),
                mock.patch.object(orchestrator, "_spec", return_value=object()),
            ):
                orchestrator._run(name, ["/bin/true"], {"GOOGLE_APPLICATION_CREDENTIALS": "/missing"})

            self.assertEqual(orchestrator._jobs[name]["status"], "failed")
            self.assertEqual(client.deleted, [(name, orchestrator.WORKSPACE)])
            self.assertEqual(len(client.waited), 1)
            self.assertTrue(client.closed)

    def test_run_cleans_up_after_command_completion(self):
        name = "bb-os-test"
        client = FakeSandboxClient(
            SimpleNamespace(exit_code=0, stdout="stdout", stderr="")
        )

        with tempfile.TemporaryDirectory() as directory:
            orchestrator = self._orchestrator(Path(directory), name)
            with (
                mock.patch.object(openshell_module, "SandboxClient", return_value=client),
                mock.patch.object(openshell_module, "WorkspaceClient", FakeWorkspaceClient),
                mock.patch.object(orchestrator, "_spec", return_value=object()),
            ):
                orchestrator._run(name, ["/bin/true"], {"GOOGLE_APPLICATION_CREDENTIALS": "/missing"})

            self.assertEqual(orchestrator._jobs[name]["status"], "completed")
            self.assertEqual(client.deleted, [(name, orchestrator.WORKSPACE)])
            self.assertEqual(len(client.waited), 1)
            self.assertTrue(client.closed)

    def test_run_cleans_up_when_create_fails(self):
        name = "bb-os-test"
        client = FakeSandboxClient(SimpleNamespace(exit_code=0, stdout="", stderr=""))
        client.create = mock.Mock(side_effect=RuntimeError("create failed"))

        with tempfile.TemporaryDirectory() as directory:
            orchestrator = self._orchestrator(Path(directory), name)
            with (
                mock.patch.object(openshell_module, "SandboxClient", return_value=client),
                mock.patch.object(openshell_module, "WorkspaceClient", FakeWorkspaceClient),
                mock.patch.object(orchestrator, "_spec", return_value=object()),
            ):
                orchestrator._run(name, ["/bin/true"], {"GOOGLE_APPLICATION_CREDENTIALS": "/missing"})

            self.assertEqual(orchestrator._jobs[name]["status"], "failed")
            self.assertEqual(client.deleted, [(name, orchestrator.WORKSPACE)])
            self.assertTrue(client.closed)


if __name__ == "__main__":
    unittest.main()
