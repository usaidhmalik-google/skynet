import os
import unittest
import importlib.util
import sys
from pydantic import BaseModel

class TestAgentEvaluation(unittest.TestCase):
    """Automated evaluation suite for dynamically generated Google ADK agents."""

    @property
    def file_path(self):
        return os.path.join(os.getcwd(), "generated_agent.py")

    def test_file_exists(self):
        """Verify that the generated agent file exists on disk."""
        self.assertTrue(os.path.exists(self.file_path), "generated_agent.py does not exist.")

    def test_syntax_and_compilation(self):
        """Verify that the generated agent code compiles successfully without syntax errors."""
        try:
            with open(self.file_path, "r") as f:
                code = f.read()
            compile(code, self.file_path, "exec")
        except Exception as e:
            self.fail(f"Syntax/compilation error in generated agent: {e}")

    def test_required_contracts(self):
        """Verify that the generated agent exports the required entrypoint functions."""
        spec = importlib.util.spec_from_file_location("generated_agent", self.file_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules["generated_agent"] = module
        
        try:
            spec.loader.exec_module(module)
        except Exception as e:
            self.fail(f"Failed to load generated agent module: {e}")

        # Check create_agent contract
        self.assertTrue(hasattr(module, "create_agent"), "Missing required function: create_agent()")
        self.assertTrue(callable(module.create_agent), "create_agent is not callable")

        # Check get_runner contract
        self.assertTrue(hasattr(module, "get_runner"), "Missing required function: get_runner()")
        self.assertTrue(callable(module.get_runner), "get_runner is not callable")

    def test_schema_conformance(self):
        """Verify that custom models defined inside the generated agent use valid Pydantic BaseModels."""
        spec = importlib.util.spec_from_file_location("generated_agent", self.file_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules["generated_agent"] = module
        
        try:
            spec.loader.exec_module(module)
        except Exception as e:
            self.fail(f"Failed to load generated agent module: {e}")

        # Check only the models defined locally inside generated_agent.py
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (isinstance(attr, type) and 
                issubclass(attr, BaseModel) and 
                attr is not BaseModel and 
                attr.__module__ == module.__name__):
                # Validate that Pydantic schema builds properly
                try:
                    schema = attr.model_json_schema()
                    self.assertIsInstance(schema, dict, "Pydantic schema must build a valid dictionary.")
                    self.assertEqual(schema.get("type"), "object", "Pydantic schema must represent an object type.")
                except Exception as e:
                    self.fail(f"Failed to generate JSON schema for Pydantic model '{attr_name}': {e}")

if __name__ == "__main__":
    unittest.main()
