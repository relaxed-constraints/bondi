# AI agent skill

The BONDI skill helps coding agents use the Python API and CLI, choose components,
find tutorials, and develop BONDI itself when requested. It encourages agents to
explain their choices and link to relevant online documentation so you can learn
while working. The same skill content works with Codex, Claude Code, Gemini CLI
and Cursor through the [Agent Skills format](https://agentskills.io/specification).

Installing the skill does not install BONDI, Docker or a coding agent. Follow
[Installation](installation.md) for the Python library.

## Install with npx skills

From your research project's root, run:

```sh
npx skills add relaxed-constraints/bondi --skill bondi
```

Choose your agent when prompted. The
[open-source skills installer](https://github.com/vercel-labs/skills) requires
Node.js (currently 22.20 or newer).

Start a new agent session after installation if the skill is not discovered.

Apply skill updates deliberately with `npx skills update bondi`.

## Manual fallback

No Node.js is required. Clone the repository or download its GitHub source archive,
then copy or sim-link the **whole** `skills/bondi/` directory, including `references/`, to
one of these locations:

| Agent | Inside your project | Personal installation |
| --- | --- | --- |
| Codex | `.agents/skills/bondi/` | `~/.agents/skills/bondi/` |
| Claude Code | `.claude/skills/bondi/` | `~/.claude/skills/bondi/` |
| Gemini CLI | `.gemini/skills/bondi/` | `~/.gemini/skills/bondi/` |
| Cursor | `.cursor/skills/bondi/` | `~/.cursor/skills/bondi/` |

For example, from your consumer project's root on macOS/Linux, provided the
destination does not already exist:

```sh
mkdir -p .agents/skills
cp -R /path/to/bondi/skills/bondi .agents/skills/bondi
```

See the native skill documentation for
[Codex](https://learn.chatgpt.com/docs/build-skills),
[Claude Code](https://code.claude.com/docs/en/skills),
[Gemini CLI](https://geminicli.com/docs/cli/skills/) and
[Cursor](https://cursor.com/docs/skills).
The installer may use shared directories instead of the agent-specific manual
locations above.

## Use and maintain the skill

Try: "Use the BONDI skill to build a MongoDB workload, explain the components,
and link me to the relevant tutorial."

The agent loads focused references as needed. Development instructions are
separate from normal library usage. Read the source in
[`skills/bondi/SKILL.md`](https://github.com/relaxed-constraints/bondi/blob/main/skills/bondi/SKILL.md).
The skill travels with GitHub source; it is not installed by `pip install bondi`.

When changing BONDI's public behavior, review skill examples, supported capabilities
and documentation links alongside the guides. Before releasing a skill change,
check local installer discovery and installation in a disposable project, and
exercise examples against the intended BONDI version. Installer compatibility
does not by itself demonstrate behavior in every coding agent.
