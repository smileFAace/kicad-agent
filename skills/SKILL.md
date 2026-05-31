---
name: kicad-agent
description: "AI-safe structural editing of KiCad schematic, PCB, symbol library, and footprint files via JSON operations. Use when editing any KiCad 10+ file (.kicad_sch, .kicad_pcb, .kicad_sym, .kicad_mod), analyzing component/net/footprint state, or running ERC/DRC validation. Invoked as /kicad-agent."
argument-hint: "[operation JSON | status | context | help]"
user_invocable: true
allowed-tools:
  - Read
  - Bash
  - Write
  - Edit
  - Grep
  - Glob
---

<objective>
Bridge between Claude and the kicad-agent Python backend for AI-safe KiCad file editing. Claude constructs JSON operations conforming to the Pydantic operation schema; the skill handler validates them against the schema and executes via the kicad-agent Python library. The LLM never touches raw S-expressions -- it emits structured intents, and the Python tool layer mutates the AST, serializes valid KiCad files, and validates via ERC/DRC gates.

Architecture: LLM -> intent JSON -> AST mutation -> validated KiCad file. Zero corruption, every time.
</objective>

<process>

## Step 0: Load prompt template

Read `prompt.md` from the same directory as this file. It contains the full operation reference with field descriptions, JSON examples, and constraints. Use it to construct valid operations.

## Step 1: Parse $ARGUMENTS

Determine the user's intent:

- **"help"** -- Print available operations from prompt.md. List all 71 operation types with brief descriptions.
- **"status"** -- Report current project context. Look for KiCad files in the working directory and summarize what was found (schematic, PCB, symbol libs, footprint libs).
- **"context"** -- Render a project summary. Parse any .kicad_pro file found, list schematics, PCBs, and libraries with component counts.
- **"analyze <path>"** -- Analyze a KiCad PCB/schematic using the fine-tuned spatial reasoning model. Runs best-of-N generation with reward model scoring and returns the highest-quality reasoning chain.
- **JSON operation** -- Treat as an operation to execute. Must conform to the operation schema documented in prompt.md.

## Step 2a: Handle analyze request

If the argument starts with "analyze ":

1. Extract the file path from the argument (after "analyze ")
2. Verify the file exists and has a valid KiCad extension (.kicad_pcb or .kicad_sch)
3. Run the analysis:

```bash
cd ~/apps/kicad-agent && python3 -c "
import json, sys
from kicad_agent.inference import generate_analysis

result = generate_analysis(sys.argv[1])
print(json.dumps({
    'chain_text': result.chain_text,
    'composite_score': result.composite_score,
    'format_score': result.format_score,
    'quality_score': result.quality_score,
    'accuracy_score': result.accuracy_score,
    'generation_time_s': result.generation_time_s,
}, indent=2))
" '<file_path>'
```

4. Present the analysis to the user:
   - Show the reasoning chain text
   - Show the quality scores (format, quality, accuracy, composite)
   - Note the generation time

Skip to Step 4 (do not proceed to Step 2/3 for JSON operations).

## Step 2: Validate the JSON operation

If the argument is a JSON operation, validate it against the Pydantic operation schema:

```bash
cd ~/apps/kicad-agent && python3 -c "
import json, sys
from kicad_agent.ops.schema import Operation
op = Operation.model_validate_json(sys.stdin.read())
print(json.dumps({'valid': True, 'op_type': op.root.op_type, 'target_file': op.root.target_file}))
" <<< '$OPERATION_JSON'
```

If validation fails, report the exact constraint violated and suggest corrections.

## Step 3: Execute the operation

Run the validated operation through the kicad-agent pipeline:

```bash
cd ~/apps/kicad-agent && python3 -c "
import json, sys
from kicad_agent.ops.schema import Operation
from kicad_agent.ops.executor import OperationExecutor
op = Operation.model_validate_json(sys.stdin.read())
executor = OperationExecutor(project_dir='.')
result = executor.execute(op)
print(json.dumps(result, indent=2))
" <<< '$OPERATION_JSON'
```

## Step 4: Format and display the result

Present the execution result to the user:
- Success: Confirm what changed, show the operation type and target file
- Failure: Show the error message with context about what constraint was violated
- Validation: If ERC/DRC was triggered, summarize pass/fail status

</process>

<tracking>
Every operation executed through this skill MUST be tracked in Beads:

1. **Before executing** — If no Bead exists for the current task, create one:
   ```
   mcp__beads__beads_create(title="KiCad: <operation summary>", labels="kicad")
   ```

2. **After executing** — Update the Bead with the result:
   ```
   mcp__beads__beads_update(id=<bead_id>, status="in_progress", notes="ERC passed / DRC: 2 violations found")
   ```

3. **Out-of-scope findings** — If you discover an issue unrelated to the current task:
   ```
   mcp__beads__beads_create(title="KiCad: <finding>", labels="out-of-scope,kicad", deps="<current_task_bead>")
   ```

4. **Validation failures** — Always create a Bead for ERC/DRC failures:
   ```
   mcp__beads__beads_create(title="DRC violation: <summary>", labels="drc,kicad", priority="high")
   ```

For GSD phase planning, use `/gsd-plan-phase` to structure KiCad work into phases (schematic → ERC → layout → DRC → export).
</tracking>

<context>
The full operation schema with field-level documentation, constraints, and JSON examples is in prompt.md in the same directory. Always consult it before constructing operations.

The project CLAUDE.md at `.claude/CLAUDE.md` contains the complete tool inventory (kicad-cli commands, Python packages, workflow stages). Agents should consult it for exact CLI syntax instead of asking humans to run things manually.

Supported file types: .kicad_sch (schematic), .kicad_pcb (PCB), .kicad_sym (symbol library), .kicad_mod (footprint library)
KiCad version: 10+ only
Position units: millimeters (mils not supported)
Operations are atomic: one mutation per operation, one target file per operation
