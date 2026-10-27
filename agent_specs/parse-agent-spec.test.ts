import assert from "node:assert/strict";
import { mkdtemp, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  AgentSpecParseError,
  parseAgentSpec,
  readAgentSpec,
} from "./parse-agent-spec.js";

test("parses metadata, instructions, and examples with Unix newlines", () => {
  const spec = parseAgentSpec(`---
name: Demo Agent
description: Helps with browser tests
tools:
  - read
  - search
user-invocable: false
---
Follow project conventions.

<example>
Input: create a smoke test
Output: propose a focused test
</example>
`);

  assert.equal(spec.name, "Demo Agent");
  assert.equal(spec.description, "Helps with browser tests");
  assert.deepEqual(spec.metadata.tools, ["read", "search"]);
  assert.equal(spec.metadata["user-invocable"], false);
  assert.equal(spec.instructions, "Follow project conventions.");
  assert.deepEqual(spec.examples, ["Input: create a smoke test\nOutput: propose a focused test"]);
});

test("normalizes Windows line endings and accepts optional metadata", () => {
  const spec = parseAgentSpec(
    "---\r\ndescription: Valid agent\r\n---\r\nInstructions here.\r\n",
  );
  assert.equal(spec.name, undefined);
  assert.equal(spec.instructions, "Instructions here.");
});

test("validates the required description", () => {
  assert.throws(
    () => parseAgentSpec("---\nname: Missing description\n---\nBody"),
    (error: unknown) => error instanceof AgentSpecParseError
      && error.message.includes("required metadata 'description'"),
  );
});

test("rejects malformed or duplicate YAML keys with source context", () => {
  assert.throws(
    () => parseAgentSpec(
      "---\ndescription: First\ndescription: Second\n---\nBody",
      "planner.agent.md",
    ),
    (error: unknown) => error instanceof AgentSpecParseError
      && error.message.includes("planner.agent.md")
      && error.message.includes("invalid YAML"),
  );
});

test("validates known metadata types", () => {
  assert.throws(
    () => parseAgentSpec("---\ndescription: Agent\ntools: execute\n---\nBody"),
    /'tools' must be a list of strings/,
  );
  assert.throws(
    () => parseAgentSpec("---\ndescription: Agent\nuser-invocable: yes please\n---\nBody"),
    /'user-invocable' must be a boolean/,
  );
});

test("reports unbalanced example tags", () => {
  assert.throws(
    () => parseAgentSpec("---\ndescription: Agent\n---\n<example>missing close"),
    /example tags are unbalanced/,
  );
  assert.throws(
    () => parseAgentSpec("---\ndescription: Agent\n---\n</example><example>value</example>"),
    /example tags are unbalanced/,
  );
  assert.throws(
    () => parseAgentSpec(
      "---\ndescription: Agent\n---\n<example><example>nested</example></example>",
    ),
    /nested <example> blocks/,
  );
});

test("reads an agent definition from disk", async () => {
  const directory = await mkdtemp(join(tmpdir(), "agent-spec-"));
  const path = join(directory, "agent.agent.md");
  try {
    await writeFile(path, "---\ndescription: Read from disk\n---\nInstructions", "utf8");
    const spec = await readAgentSpec(path);
    assert.equal(spec.description, "Read from disk");
    assert.equal(spec.instructions, "Instructions");
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("reports unreadable agent paths", async () => {
  await assert.rejects(
    readAgentSpec(join(tmpdir(), "missing-agent-spec.agent.md")),
    /could not read agent definition/,
  );
});

test("all workspace Copilot agents have valid definitions", async () => {
  const directory = join(process.cwd(), ".github", "agents");
  const files = (await readdir(directory)).filter((file) => file.endsWith(".agent.md"));
  const specs = await Promise.all(files.map((file) => readAgentSpec(join(directory, file))));

  assert.equal(files.length, 4);
  assert.deepEqual(
    new Set(specs.map((spec) => spec.name)),
    new Set(["Selenium Automation Orchestrator", "test-planner", "test-generator", "test-healer"]),
  );
  assert.ok(specs.every((spec) => spec.instructions.length > 0));
});
