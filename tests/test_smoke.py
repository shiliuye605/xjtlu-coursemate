"""真实 HTTP 端到端回归；使用临时数据库和仓库内模拟 LLM，不发送外网请求。

运行：python -m unittest discover -s tests -p "test_*.py" -v
"""
import importlib.util
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import HTTPServer

import fitz
import requests

ROOT = Path(__file__).resolve().parent.parent


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class CourseMateSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="coursemate-test-")
        spec = importlib.util.spec_from_file_location("coursemate_mock", ROOT / "tests/mock_llm.py")
        mock = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mock)
        cls.mock = HTTPServer(("127.0.0.1", 0), mock.Handler)
        threading.Thread(target=cls.mock.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{free_port()}"
        cls.mock_base = f"http://127.0.0.1:{cls.mock.server_port}/v1"
        env = dict(os.environ, COURSEMATE_DATA_DIR=str(Path(cls.temp.name) / "data"))
        cls.server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
             "--port", cls.base.rsplit(":", 1)[1]], cwd=ROOT, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                if requests.get(cls.base + "/api/health", timeout=1).ok:
                    return
            except requests.RequestException:
                pass
            if cls.server.poll() is not None:
                raise RuntimeError("Backend failed to start")
            time.sleep(0.1)
        raise RuntimeError("Backend startup timed out")

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        cls.server.wait(timeout=10)
        cls.mock.shutdown()
        cls.mock.server_close()
        cls.temp.cleanup()

    def api(self, method, path, **kwargs):
        response = requests.request(method, self.base + "/api" + path, timeout=90, **kwargs)
        response.raise_for_status()
        return response

    def wait_document(self, doc_id):
        for _ in range(120):
            status = self.api("GET", f"/documents/{doc_id}").json()
            if status["status"] == "failed":
                self.fail(status["error"])
            if status["status"] == "done" and status["analysis_status"] == "done":
                return status
            time.sleep(0.5)
        self.fail("Translation or analysis timed out")

    def test_full_local_workflow(self):
        self.assertFalse(self.api("GET", "/settings").json()["ready"])
        cid = self.api("POST", "/courses", json={"name": "数据库与电子商务（模拟课程）", "code": "DEMO"}).json()["id"]
        bad = requests.post(self.base + f"/api/courses/{cid}/documents",
                            files={"file": ("bad.pdf", b"not a PDF", "application/pdf")}, timeout=10)
        self.assertEqual(bad.status_code, 400)
        self.api("POST", "/settings", json={"api_base": self.mock_base,
                 "api_key": "demo-only", "model": "mock-llm"})
        self.assertTrue(self.api("POST", "/settings/test", json={"api_base": self.mock_base,
                            "api_key": "demo-only", "model": "mock-llm"}).json()["ok"])
        docs = self.api("POST", f"/sample/{cid}").json()
        self.assertEqual(len(docs), 2)
        for item in docs:
            status = self.wait_document(item["id"])
            self.assertEqual(status["page_count"], 4)
            original = self.api("GET", f"/documents/{item['id']}/files/original").content
            translated = self.api("GET", f"/documents/{item['id']}/files/translated").content
            with fitz.open(stream=original, filetype="pdf") as source, fitz.open(stream=translated, filetype="pdf") as output:
                self.assertTrue(source[0].get_text().strip())
                self.assertEqual(source.page_count, output.page_count)
                self.assertEqual(source[0].rect, output[0].rect)
                self.assertIn("演示", "".join(page.get_text() for page in output))
                before = source[0].get_pixmap().pixel(10, 10)
                after = output[0].get_pixmap().pixel(10, 10)
                self.assertEqual(before, after, "Translation removed the original header background")
            analysis = self.api("GET", f"/documents/{item['id']}/analysis").json()
            self.assertIn("模拟演示", analysis["markdown"])
        summary = self.api("GET", f"/courses/{cid}/summary").json()
        self.assertEqual(summary["pending_count"], 2)
        self.api("POST", f"/courses/{cid}/summary/update")
        self.assertEqual(self.api("GET", f"/courses/{cid}/summary").json()["pending_count"], 0)
        with fitz.open(stream=self.api("GET", f"/courses/{cid}/summary.pdf").content, filetype="pdf") as pdf:
            self.assertGreater(pdf.page_count, 0)
            self.assertIn("课程总结", "".join(page.get_text() for page in pdf))
        sample = ROOT / "sample_data/Lecture_01_Database_Systems.pdf"
        with sample.open("rb") as stream:
            extra = self.api("POST", f"/courses/{cid}/documents",
                             files={"file": ("Revision_Demo.pdf", stream, "application/pdf")}).json()
        self.wait_document(extra["id"])
        self.assertEqual(self.api("GET", f"/courses/{cid}/summary").json()["pending_count"], 1)
        self.api("POST", f"/courses/{cid}/summary/update")
        self.assertEqual(len(self.api("GET", f"/courses/{cid}/summary/history").json()), 2)
        response = self.api("POST", "/chat", json={"course_id": cid, "document_id": docs[0]["id"],
                         "messages": [{"role": "user", "content": "什么是数据库事务？"}]})
        self.assertIn("离线演示", response.text)
        self.assertEqual(len(self.api("GET", f"/chat/history?course_id={cid}").json()), 2)
        self.api("DELETE", f"/courses/{cid}")
        self.assertEqual(self.api("GET", "/courses").json(), [])
        self.assertEqual(self.api("GET", f"/courses/{cid}/documents").json(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
