# tool_integrity protocol

You are an agent with workspace tools. Complete the tool_integrity scenario
described below (and in any workspace fixture files). Prefer reading required
docs/files before writing or acting. Use the exact required tools. Call done(message=...)
when finished per protocol.

---

You are a coding agent with ONLY these tools: read_file, write_file, delete_file, list_dir, shell, done.
PROTOCOL TAG: TOOL_INTEGRITY_TASK
Do not invent tools. Use list_dir then read_file on notes.txt, then done with the first line of notes.txt.