# Skills

Playbooks the copilot loads on demand. Each folder is an
[Agent Skills](https://agentskills.io/specification) package: a `SKILL.md`
with YAML frontmatter, plus an optional `references/` directory.

Only each skill's `name` and `description` sit in the copilot's system prompt.
The body is fetched with a tool call when a request matches, so a long playbook
costs nothing on the turns that do not need it. That is the whole reason skills
exist here: the pipeline agents keep short, always-on prompts, and the one
open-ended agent gets depth it only pays for when it uses it.

| Skill | Fires on |
| --- | --- |
| `call-prep` | "prep me for the Acme call", "I'm talking to them in 20 minutes" |
| `objection-handling` | a forwarded objection, or a reply triage classified as one |
| `pipeline-review` | "what's stuck", "what did you do this week", Monday reviews |

## Adding one

```
skills/your-skill/
  SKILL.md              # required, frontmatter + body
  references/           # optional, loaded individually on request
    playbook.md
```

`SKILL.md` opens with frontmatter:

```markdown
---
name: your-skill
description: What it does, and the phrases that should trigger it. This is the only text the model sees before deciding to load the skill, so write it for that decision.
---
```

`name` must be lowercase, hyphenated, and identical to the folder name. Keep the
body procedural — steps and rules, not prose — and push detail into `references/`.

Validate without restarting the server:

```bash
.venv/bin/python -c "from app.skills import load_skills; print(load_skills().get_skill_names())"
```

A malformed folder raises `SkillsError` naming the file and the fix, and stops
the process, on the same principle as a broken `app/icp.yaml`.

## Two constraints

**Skills are read-only.** The Agent Skills spec allows a `scripts/` directory
that the agent may execute. RevCrew removes that tool, and a folder containing
`scripts/` refuses to load. The copilot reads prospect-authored text, and an
execution path that bypasses the write guard and the audit trail is not worth
the convenience. Logic that needs to *do* something belongs in `app/toolkits/`,
behind the guard.

**Skills cannot loosen the rules.** Safety behaviour — the untrusted-input
fencing, the approval gate, never sending on the agent's own initiative — lives
in `app/prompts/copilot.py` and applies whether or not a skill was loaded. A
skill adds procedure on top. It never has the last word on what the agent is
allowed to do.

## Your content, not ours

`objection-handling/references/proof-points.md` ships as an empty template with
`TODO` markers, and the skill is instructed not to cite it while those markers
remain. Fill it in with your own customers and positioning, the same way you
replace the shipped ICP rubric. Point `SKILLS_PATH` at a directory outside the
repo to keep your playbooks private, or set `SKILLS_ENABLED=false` to turn the
whole mechanism off.
