import socket
import subprocess
import sys

import pytest

from config import ROOT

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell startup checks")


def run_script(exe, model, *arguments):
    return subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "scripts/start_llm.ps1"),
                           "-ServerExe", str(exe), "-ModelPath", str(model), *arguments],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)


def test_missing_executable_and_model_fail_without_download(tmp_path):
    missing = run_script(tmp_path / "missing.exe", tmp_path / "missing.gguf")
    assert missing.returncode != 0 and "llama-server.exe not found" in missing.stderr
    exe = tmp_path / "placeholder.exe"
    exe.write_bytes(b"never executed")
    missing = run_script(exe, tmp_path / "missing.gguf")
    assert missing.returncode != 0 and "No model will be downloaded" in missing.stderr


def test_occupied_port_is_not_stopped_or_reused(tmp_path):
    exe, model = tmp_path / "placeholder.exe", tmp_path / "placeholder.gguf"
    exe.write_bytes(b"never executed")
    model.write_bytes(b"never loaded")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        result = run_script(exe, model, "-Port", str(listener.getsockname()[1]))
        assert result.returncode != 0 and "already used by another process" in result.stderr
        assert listener.getsockname()[0] == "127.0.0.1"
