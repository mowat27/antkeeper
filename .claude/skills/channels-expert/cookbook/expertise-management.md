# Managing the Expertise File

Read this recipe whenever the workflow requires reading, updating, or validating MEMORY_FILE.

## Reading

1. Check if MEMORY_FILE exists
2. If missing, create an empty YAML file at that path (create parent directories if needed)
3. Read the file and return its contents

When answering questions, respond based **exclusively** on what is in MEMORY_FILE. Do not consult the broader codebase for answers - that is the self-improve flow's job.

## Updating

Apply only the changes identified by the self-improve flow. Follow these rules:

- **Structure** - define and maintain clean YAML sections; keep the file navigable
- **Line limit** - enforce MAX_LINES strictly (see Enforcement below)
- **Clarity** - write as a principal engineer: clear, concise, useful to future engineers and agents
- **Style** - never use em dashes; use single hyphens. Quote YAML strings containing operators (`+`, `<`, `|`)
- **Precision** - ensure file names, line numbers, and references are accurate
- **Priority** - favour actionable, high-value expertise over verbose documentation

## Line Limit Enforcement

After every write:

1. Run: `wc -l <MEMORY_FILE>`
2. If line count exceeds MAX_LINES:
   - Identify least critical sections: overly verbose descriptions, redundant examples, low-priority edge cases
   - Trim those sections
   - Re-run the line count check
   - Repeat until line count is within MAX_LINES
3. Document what was trimmed in the report

## YAML Validation

After every write, validate syntax:

```bash
python3 -c "import yaml; yaml.safe_load(open('<MEMORY_FILE>'))"
```

If errors occur, fix the YAML structure and re-validate.

## Update Report Format

When reporting an update, include:

- **Summary** - focus area, discrepancies found/remedied, final line count vs MAX_LINES
- **Discrepancies** - what was incorrect/missing/outdated, where correct info was found, how it was fixed
- **Updates made** - added, updated, and removed sections
- **Line limit** - initial and final line counts; trimming details if applicable
- **Validation** - confirm YAML syntax is valid; note areas needing future attention
- **References** - files validated against, with line numbers or IDs
