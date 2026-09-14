import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.name == 'nt', 'Windows installer and batch entry point')
class InstallationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = {**os.environ, 'PSModulePath': str(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/Modules')}

    def tearDown(self):
        self.temp.cleanup()

    def package(self, name, files):
        file = self.root/(name+'.zip')
        with ZipFile(file, 'w') as archive:
            for leaf, content in files.items():
                archive.writestr('humanize-kr/'+leaf, content)
        return file

    def install(self, archive):
        return subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
            str(ROOT/'scripts/install-humanize-skill.ps1'), '-HostName', 'Codex', '-Scope', 'Project',
            '-ProjectRoot', str(self.root), '-Archive', str(archive), '-Replace'],
            env=self.env, capture_output=True, encoding='utf-8', errors='replace', timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW)

    def test_replacement_is_exact_and_locked_failure_preserves_old_receipt(self):
        old = self.package('old', {'SKILL.md':'old', 'node/node.exe':'old runtime', 'obsolete.py':'retired'})
        new = self.package('new', {'SKILL.md':'new', 'node/node.exe':'new runtime'})
        self.assertEqual(self.install(old).returncode, 0)
        destination = self.root/'.agents/skills/humanize-kr'
        receipt = (destination/'.installed-archive.sha256').read_bytes()
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
        kernel.CreateFileW.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.CreateFileW(str(destination/'node/node.exe'), 0x80000000, 1, None, 3, 0, None)
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
        try:
            result = self.install(new)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((destination/'SKILL.md').read_text(), 'old')
            self.assertEqual((destination/'.installed-archive.sha256').read_bytes(), receipt)
        finally:
            kernel.CloseHandle(handle)
        self.assertEqual(self.install(new).returncode, 0)
        self.assertFalse((destination/'obsolete.py').exists())
        self.assertEqual((destination/'node/node.exe').read_text(), 'new runtime')
        self.assertEqual((destination/'.installed-archive.sha256').read_text().strip().lower(), hashlib.sha256(new.read_bytes()).hexdigest())

    def test_setup_returns_from_cmd_shim(self):
        shutil.copyfile(ROOT/'setup-portal.cmd', self.root/'setup-portal.cmd')
        for name in ('node', 'python', 'codex'):
            (self.root/(name+'.cmd')).write_text('@echo off\nexit /b 0\n')
        result = subprocess.run(['cmd.exe','/d','/c',str(self.root/'setup-portal.cmd'),'--check'],
            env={**self.env,'PATH':str(self.root)+';'+str(Path(os.environ['SystemRoot'])/'System32')},
            capture_output=True, text=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 0)
        self.assertIn('CHECK_OK', result.stdout)
