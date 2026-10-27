import { readFile } from "node:fs/promises";
import { parseDocument } from "yaml";

export interface AgentSpec {
  metadata: Record<string, unknown>;
  name?: string;
  description: string;
  instructions: string;
  examples: string[];
}

export class AgentSpecParseError extends Error {
  constructor(message: string, readonly sourcePath = "<memory>") {
    super(`${sourcePath}: ${message}`);
    this.name = "AgentSpecParseError";
  }
}

function extractFrontMatter(markdown: string, sourcePath: string): {
  yaml: string;
  body: string;
} {
  const normalized = markdown.replace(/^\uFEFF/, "").replace(/\r\n?/g, "\n");
  const match = /^---[ \t]*\n([\s\S]*?)\n---[ \t]*(?:\n|$)/.exec(normalized);
  if (!match) {
    throw new AgentSpecParseError(
      "expected YAML front matter delimited by '---' at the start of the file.",
      sourcePath,
    );
  }
  return {
    yaml: match[1],
    body: normalized.slice(match[0].length),
  };
}

function parseMetadata(yaml: string, sourcePath: string): Record<string, unknown> {
  const document = parseDocument(yaml, {
    prettyErrors: true,
    uniqueKeys: true,
  });
  if (document.errors.length > 0) {
    const details = document.errors.map((error) => error.message).join("; ");
    throw new AgentSpecParseError(`invalid YAML front matter: ${details}`, sourcePath);
  }

  let value: unknown;
  try {
    value = document.toJS({ mapAsMap: false });
  } catch (error) {
    const details = error instanceof Error ? error.message : String(error);
    throw new AgentSpecParseError(`could not read YAML front matter: ${details}`, sourcePath);
  }

  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new AgentSpecParseError(
      "YAML front matter must be a mapping of metadata keys to values.",
      sourcePath,
    );
  }
  return value as Record<string, unknown>;
}

function validateMetadata(
  metadata: Record<string, unknown>,
  sourcePath: string,
): asserts metadata is Record<string, unknown> & { description: string } {
  if (typeof metadata.description !== "string" || metadata.description.trim() === "") {
    throw new AgentSpecParseError(
      "required metadata 'description' must be a non-empty string.",
      sourcePath,
    );
  }
  if (metadata.name !== undefined
      && (typeof metadata.name !== "string" || metadata.name.trim() === "")) {
    throw new AgentSpecParseError("'name' must be a non-empty string when provided.", sourcePath);
  }
  for (const key of ["tools", "agents"] as const) {
    const value = metadata[key];
    if (value !== undefined
        && (!Array.isArray(value) || value.some((entry) => typeof entry !== "string"))) {
      throw new AgentSpecParseError(`'${key}' must be a list of strings when provided.`, sourcePath);
    }
  }
  for (const key of ["user-invocable", "disable-model-invocation"] as const) {
    const value = metadata[key];
    if (value !== undefined && typeof value !== "boolean") {
      throw new AgentSpecParseError(`'${key}' must be a boolean when provided.`, sourcePath);
    }
  }
}

function extractExamples(body: string, sourcePath: string): {
  instructions: string;
  examples: string[];
} {
  let open = false;
  for (const match of body.matchAll(/<\/?example(?:\s[^>]*)?>/gi)) {
    if (match[0].startsWith("</")) {
      if (!open) {
        throw new AgentSpecParseError(
          "example tags are unbalanced; each </example> must follow an <example>.",
          sourcePath,
        );
      }
      open = false;
    } else {
      if (open) {
        throw new AgentSpecParseError(
          "nested <example> blocks are not supported.",
          sourcePath,
        );
      }
      open = true;
    }
  }
  if (open) {
    throw new AgentSpecParseError(
      "example tags are unbalanced; each <example> must have a matching </example>.",
      sourcePath,
    );
  }

  const examples = [
    ...body.matchAll(/<example(?:\s[^>]*)?>([\s\S]*?)<\/example\s*>/gi),
  ].map((match) => match[1].trim());
  const instructions = body
    .replace(/<example(?:\s[^>]*)?>[\s\S]*?<\/example\s*>/gi, "")
    .trim();
  return { instructions, examples };
}

export function parseAgentSpec(markdown: string, sourcePath = "<memory>"): AgentSpec {
  const { yaml, body } = extractFrontMatter(markdown, sourcePath);
  const metadata = parseMetadata(yaml, sourcePath);
  validateMetadata(metadata, sourcePath);
  const { instructions, examples } = extractExamples(body, sourcePath);

  return {
    metadata,
    ...(typeof metadata.name === "string" ? { name: metadata.name } : {}),
    description: metadata.description,
    instructions,
    examples,
  };
}

export async function readAgentSpec(path: string | URL): Promise<AgentSpec> {
  const sourcePath = path instanceof URL ? path.href : path;
  try {
    return parseAgentSpec(await readFile(path, "utf8"), sourcePath);
  } catch (error) {
    if (error instanceof AgentSpecParseError) {
      throw error;
    }
    const details = error instanceof Error ? error.message : String(error);
    throw new AgentSpecParseError(`could not read agent definition: ${details}`, sourcePath);
  }
}
