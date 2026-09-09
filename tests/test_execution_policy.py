import unittest

from app.execution.policy import ExecutionPolicyError, PythonExecutionPolicy


class PythonExecutionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = PythonExecutionPolicy()

    def test_allows_basic_python(self):
        self.policy.validate("value = 2 + 2\nprint(value)")

    def test_blocks_process_module(self):
        with self.assertRaises(ExecutionPolicyError):
            self.policy.validate("import subprocess\nsubprocess.run(['echo', 'x'])")

    def test_blocks_network_module(self):
        with self.assertRaises(ExecutionPolicyError):
            self.policy.validate("import socket\nsocket.create_connection(('example.com', 80))")

    def test_blocks_dynamic_execution(self):
        with self.assertRaises(ExecutionPolicyError):
            self.policy.validate("eval('print(1)')")

    def test_blocks_attribute_escape(self):
        with self.assertRaises(ExecutionPolicyError):
            self.policy.validate("runner = object\nrunner.system('x')")

    def test_reports_syntax_errors(self):
        with self.assertRaises(ExecutionPolicyError):
            self.policy.validate("def broken(:\n    pass")


if __name__ == "__main__":
    unittest.main()
