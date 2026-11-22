# Author: Ching Kao
# Student ID: 85768427
"""Deterministic Google responses shared by API and browser workflow tests."""

import json

from google.genai import types


class ScriptedGemini:
    def __init__(self, block=False, second_feature=False):
        self.block = block
        self.implementations = 0
        self.spec = {
            "spec": "Export add(a,b) from add.cjs using CommonJS.",
            "features": [{"title": "Addition", "criteria": ["add(1,2) returns 3"]}],
        }

        self.revise_test = second_feature
        if second_feature:
            self.spec["features"].append({"title": "Adding zero", "criteria": ["add(5,0) returns 5"]})

    def __call__(self, *, contents, config, model):
        prompt = config.system_instruction
        last = contents[-1].parts[0]
        if "AI Coder Coordinator" in prompt:
            if last.function_response:
                part = types.Part(text=last.function_response.response["result"])
            elif last.text == "progress":
                part = self.tool("getRun", {})
            elif last.text == "Use integers":
                part = self.tool("resumeRun", {"clarification": last.text})
            else:
                part = self.tool("startRun", {"description": "Build an adder", "requirements": []})
        elif prompt.startswith("Coordinator report."):
            part = types.Part(text=json.loads(last.text)["summary"])
        elif prompt.startswith("Planner."):
            part = types.Part(text=json.dumps(self.spec))
        elif prompt.startswith("Architect environment."):
            part = types.Part(text=json.dumps({"reason": "Node built-ins cover this project.", "packages": {}}))
        elif prompt.startswith("Architect acceptance."):
            part = types.Part(text=json.dumps({"decision": "approve", "reason": "The requested behavior is covered by passing tests."}))
        elif prompt.startswith("Tester diagnosis"):
            task = json.loads(last.text)
            assert task["execution"]["id"] and task["execution"]["log"]
            if self.block:
                self.block = False
                decision, reason = "blocked", "Which numeric types are required?"
            elif self.revise_test:
                self.revise_test = False
                decision, reason = "test_invalid", "The test imports the wrong module."
            elif task["execution"]["outcome"] == "passed":
                decision, reason = (
                    "already_passing",
                    "The new zero case and earlier addition test both pass.",
                )
            elif "(Red)" in prompt:
                decision, reason = "expected_failure", "The required add module is missing."
            else:
                decision, reason = "implementation_defect", "Actual sum was 0 instead of 3."
            part = types.Part(text=json.dumps({"decision": decision, "reason": reason}))
        elif last.function_response:
            assert "Wrote " in last.function_response.response["result"]
            part = types.Part(text="File written.")
        elif prompt.startswith("Tester author."):
            zero = json.loads(last.text)["feature"]["title"] == "Adding zero"
            filename = "zero.test.js" if zero else "add.test.js"
            source = "typo.cjs" if self.revise_test else "add.cjs"
            args, expected = ("5,0", 5) if zero else ("1,2", 3)
            part = self.tool(
                "writeFile",
                {
                    "path": filename,
                    "content": (
                        "const test = require('node:test');\nconst assert = require('node:assert/strict');\n"
                        f"test('adds {args}', () => assert.equal(require('./{source}').add({args}), {expected}));\n"
                    ),
                },
            )
        elif prompt.startswith("Coder environment repair."):
            part = self.tool("writeFile", {"path": "package.json", "content": json.dumps({
                "name": "ai-coder-workspace", "version": "1.0.0", "private": True,
                "dependencies": {"jsdom": "^26.1.0"},
            })})
        elif prompt.startswith("Coder."):
            self.implementations += 1
            expression = "0" if self.implementations == 1 else "a + b"
            part = self.tool(
                "writeFile", {"path": "add.cjs", "content": f"exports.add = (a, b) => {expression};\n"}
            )
        else:
            raise AssertionError(prompt[:100])
        if part.function_call:
            assert part.function_call.name in [t.name for t in config.tools[0].function_declarations]
        return types.GenerateContentResponse(
            candidates=[types.Candidate(content=types.Content(role="model", parts=[part]))]
        )

    @staticmethod
    def tool(name, args):
        return types.Part(function_call=types.FunctionCall(name=name, args=args))
