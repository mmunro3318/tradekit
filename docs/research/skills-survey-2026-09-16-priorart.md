# Skills / Agent-Tooling Prior-Art Survey — 2026-09-16

Scope: answer whether Mike's "script bank" idea, and adjacent token-saving skill
patterns, have prior art outside his own tk-stack setup. Research only — no code,
no other files touched, no commits.

---

## VERDICT ON THE SCRIPT BANK

Prior art partially supports the *mechanism* (Anthropic's own Skills architecture is
built around bundled, executable utility scripts as a first-class, token-cheap
pattern) but does not support Mike's proposal in its literal form — a single
committed index of ad-hoc project scripts that agents "must look up first." No
report of exactly this pattern ("committed script bank indexed by name/params,
mandatory lookup") turned up, successful or failed, in either Anthropic's docs or
practitioner writing. What *does* have direct, well-evidenced prior art is the
closely-related and more general claim underneath it — that growing an index of
reusable capabilities for an agent to search has a well-documented failure mode
(the agent picks the wrong entry more often as the index grows, "skill shadowing"),
and that unmanaged/uncurated indexes actively make agents worse on a meaningful
fraction of tasks, not just neutral.

Evidence:

- Anthropic's own architecture treats **scripts-as-skills** as the recommended
  fix for exactly the failure Mike describes (agent regenerates equivalent code
  each time, burning tokens, less reliably than a canned script). Official
  guidance: "Provide utility scripts... Even if Claude could write a script,
  pre-made scripts offer advantages: More reliable than generated code, save
  tokens (no need to include code in context), save time (no code generation
  required), ensure consistency across uses." — [Skill authoring best
  practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)
  [official]. This is architecturally identical to what Mike wants (an indexed,
  reusable, looked-up-before-writing script store) — Anthropic just ships it as
  "a skill with a scripts/ folder" rather than a bare project convention, which
  gets him the free discovery layer (name+description pre-loaded at ~100 tokens,
  full script never enters context, only its stdout does).
- The generalized version of "build an index of reusable capabilities and have
  the agent consult it first" has a name and a measured failure curve in the
  literature: **skill shadowing**. "More Skills, Worse Agents? Skill Shadowing
  Degrades Performance When Expanding Skill Libraries" (arXiv 2605.24050,
  2026-05-21) found performance degrades **up to 21%** scaling from a small
  curated set to a 202-skill library, and decomposed why: "the skill shadowing
  effect grows with library size and significantly contributes to the
  performance degradation, whereas the context overhead effect remains small and
  indistinguishable from zero" — i.e., the problem is the agent choosing the
  wrong entry from a crowded index, not context bloat from having the index
  loaded. [https://arxiv.org/abs/2605.24050] [official — arXiv preprint, not
  Anthropic, but this is the primary research source, treated as authoritative
  for this claim].
- A second, independent practitioner synthesis (citing further research)
  documents **library drift** and **negative skills**: "a curated agent skill
  library will, on a meaningful fraction of tasks, make your agent worse,"
  citing a controlled study where "the gap between an unmanaged library and a
  hygiene-managed one over a hundred rounds was 0.26 vs. 0.58 pass@1," and
  SkillsBench-style data showing curated skills hurt performance on roughly 19%
  of tasks, with some causing "-39.3 pp" drops. — Tezan Sahu, "Your Agent Skill
  Library Is Quietly Rotting," Low-Pass Filter, 2026-07-04.
  [https://lowpassfilter.substack.com/p/your-agent-skill-library-is-quietly]
  [practitioner, synthesizing primary research — treat the underlying numbers as
  secondhand].
- Academic precedent for "growing library of reusable executable skills that an
  agent must retrieve and reuse before writing new code" is **Voyager** (2023,
  Minecraft LLM agent): "an ever-growing skill library of executable code for
  storing and retrieving complex behaviors... retrieves relevant skills from the
  library based on semantic similarity to aid in generating new code." This is
  the closest true ancestor of Mike's idea and it worked *in that domain*, but
  Voyager's retrieval was semantic-embedding-based and automated, not a
  name/param index an agent manually greps — a structurally different (and
  more failure-prone per the 2026 papers above) lookup mechanism.
  [https://arxiv.org/abs/2305.16291] — dated 2023, predates the current
  Skills-specific failure-mode literature, cite with that caveat.
- No prior art found for the specific complaint Mike is trying to solve at the
  root — "agents fail once or twice on quoting/piping, then rewrite from
  scratch in a later session" — being fixed *by an index* anywhere in the
  practitioner literature searched. What practitioners report fixing that
  specific problem is not an index but **hooks that block the failure-prone
  invocation shape** (see FAILURE MODES below, PowerShell case) — i.e., prevent
  the bad pattern at the tool layer rather than hoping the agent consults a
  library instead of improvising.

**Bottom line for Mike:** the "provide the script, let the agent run it instead
of regenerating it" half of his idea is exactly what Anthropic recommends and
architects for (put it in a skill's `scripts/` folder, reference it from
SKILL.md, mark clearly whether to execute or read-as-reference). The "index of
many ad-hoc scripts the agent must search before acting" half is the part with
a real, named, measured failure mode once the index grows past a small curated
set — and the size where it starts hurting is much lower than one might expect
(degradation was already detectable well before 202 skills; the "19% of tasks
hurt" number was for *curated* libraries, not raw script dumps).

---

## OFFICIAL GUIDANCE

**Progressive disclosure — the load-bearing architectural idea.** Skills are
filesystem directories loaded in three stages: "Level 1: Metadata (always
loaded)... Level 2: Instructions (loaded when triggered)... Level 3: Resources
and code (loaded as needed)." "This lightweight approach means you can install
many Skills without context penalty: until a Skill is triggered, only its name
and description occupy context." — [Agent Skills
overview](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)
[official]. Cost table given verbatim: Level 1 metadata ≈100 tokens/skill always
loaded; Level 2 instructions <5k tokens when triggered; Level 3+ resources: zero
tokens until accessed, and "scripts run through bash, and only their output
enters context." Same page: "the script's code never loads into the context
window. Only its output... consumes tokens, which makes scripts far more
efficient than having Claude generate equivalent code on the fly."

**Description field is the single most expensive always-on cost.** "The most
expensive token in your entire plugin is the always-on one — every skill's YAML
description field gets loaded into the system prompt of every Claude Code
session, whether or not the user ever invokes that skill" (practitioner
paraphrase, corroborated by official cost table above). Official: "description
must include both what the Skill does and when Claude should use it," max 1024
chars, "Always write in third person," "Be specific and include key terms." —
[Skill authoring best
practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)
[official].

**Size discipline, stated as hard numbers.** "Keep SKILL.md body under 500 lines
for optimal performance," "For reference files longer than 100 lines, include a
table of contents," "Keep references one level deep from SKILL.md" (Claude
"might use commands like `head -100` to preview content rather than reading
entire files" if references nest, causing silent partial reads). — same page,
[official].

**When a skill is the right container vs. alternatives — Anthropic's own
comparison, quoted directly:**

| Compared to | Official line | Source |
|---|---|---|
| Prompts / one-off instructions | "Choose Skills when you need Claude to perform specialized tasks consistently and efficiently"; use prompts "for one-off requests, conversational refinement... ad-hoc instructions." "If you find yourself typing the same prompt repeatedly across multiple conversations, it's time to create a Skill." | [Skills explained](https://claude.com/blog/skills-explained) [official] |
| Projects | "Projects say 'here's what you need to know.' Skills say 'here's how to do things.'... Skills provide capabilities that work everywhere." | same [official] |
| MCP servers | "MCP connects Claude to data; Skills teach Claude what to do with that data." Build an MCP server for reach/connectivity; write a Skill for "explaining how to use a tool or follow procedures." | same [official]; also platform.claude.com/best-practices: "If your Skill uses MCP tools, always use fully qualified tool names (`ServerName:tool_name`)" |
| Subagents | "Use Skills when you want capabilities that any Claude instance can load and use. Use subagents when you need complete, self-contained agents designed for specific purposes." Combine them: "subagents with specialized expertise." | same [official] |
| CLAUDE.md (Claude Code specific) | "Create a skill when you keep pasting the same instructions, checklist, or multi-step procedure into chat, or when a section of CLAUDE.md has grown into a procedure rather than a fact." "Unlike CLAUDE.md content, a skill's body loads only when it's used." | [Use Skills in Claude Code](https://code.claude.com/docs/en/skills) [official] |
| Hooks | Not compared directly by Anthropic in the pages fetched; the practitioner synthesis states the boundary cleanly: "Use hooks for anything that should happen deterministically... making them suitable for guardrails and automation," vs. skills for model-judgment-driven procedures. | [Steering Claude Code](https://claude.com/blog/steering-claude-code-skills-hooks-rules-subagents-and-more) [official — Anthropic's own blog] |
| Slash commands | "Custom commands have been merged into skills. A file at `.claude/commands/deploy.md` and a skill at `.claude/skills/deploy/SKILL.md` both create `/deploy` and work the same way... Skills add optional features: a directory for supporting files, frontmatter to control whether you or Claude invokes them." | [Use Skills in Claude Code](https://code.claude.com/docs/en/skills) [official] |

**Degrees of freedom — match specificity to fragility.** Official three-tier
guidance: high freedom (text instructions) when "multiple approaches are valid";
medium freedom (pseudocode/parameterized scripts) when "a preferred pattern
exists"; low freedom (exact scripts, no parameters) when "operations are
fragile and error-prone... a specific sequence must be followed" — explicitly
including the database-migration case, which is structurally the same class of
risk as Mike's money-path scripts. — [Skill authoring best
practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)
[official].

**Build evaluations before writing the skill.** "Create evaluations BEFORE
writing extensive documentation... Run Claude on representative tasks without a
Skill. Document specific failures." Anthropic explicitly frames this as
avoiding "documenting imagined problems." — same page [official]. This maps
directly onto Mike's own tk-spec/tk-tdd discipline (tests-first, verifiable
success criteria) — it is Anthropic's skill-specific restatement of the same
principle already in his CLAUDE.md.

---

## FAILURE MODES TO DESIGN AROUND

- **Skill shadowing at scale.** Agent picks the wrong skill/script more often
  as the index grows; measured up to 21% task-performance loss scaling to 202
  skills, with context-window overhead ruled out as the cause. — arXiv
  2605.24050, "More Skills, Worse Agents?" (2026-05-21)
  [https://arxiv.org/abs/2605.24050] [official/primary research].
- **Library drift / negative skills.** Uncurated growth degrades retrieval
  precision and injects stale guidance; curated skills still hurt ~19% of
  tasks tested in one benchmark, with individual regressions as steep as
  -39.3pp; unmanaged vs. hygiene-managed libraries measured at 0.26 vs. 0.58
  pass@1 over 100 rounds. — Tezan Sahu, Low-Pass Filter (2026-07-04)
  [https://lowpassfilter.substack.com/p/your-agent-skill-library-is-quietly]
  [practitioner, citing primary research].
- **Context rot from bloated/too-numerous skill files** — "Most Claude Code
  users install too many skills and cram everything into one file... Every MCP
  server you install adds tool definitions to Claude's context, which can
  degrade performance." — MindStudio, "context rot claude code skills bloated
  files" [https://www.mindstudio.ai/blog/context-rot-claude-code-skills-bloated-files]
  [practitioner].
- **Deeply nested references cause silent partial reads.** Anthropic's own
  warning: when a reference file points to another reference file, "Claude
  might use commands like `head -100` to preview content rather than reading
  entire files, resulting in incomplete information." — [Skill authoring best
  practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)
  [official]. Directly relevant if a script-bank index links out to per-script
  docs which link out further.
- **Time-sensitive content silently goes stale inside a skill** and produces
  "output that is slightly worse or follows a path that was accurate weeks ago
  but no longer reflects the current state of the codebase" without throwing
  any error — "the context engineering equivalent of silent data corruption."
  Anthropic's own mitigation is structural: never write "before/after date X,"
  push deprecated info into a collapsed "old patterns" section instead. —
  official best-practices page + Low-Pass Filter synthesis [official +
  practitioner].
- **Windows shell-tool blind spot in hooks (directly relevant to Mike's
  environment, which runs both Bash and PowerShell tools).** A hook `matcher`
  set to `"Bash"` only never fires for a command run through the `PowerShell`
  tool; a reported real incident had `az ad group delete` execute "with no
  approval prompt and no logged record" because the guard only watched Bash.
  Fix is trivial but must be applied deliberately: `"matcher": "Bash|PowerShell"`.
  — GitHub gist documenting issue #69397
  [https://gist.github.com/yurukusa/efaaad17986bf18773ab114389219665/00495d63644b137e296e78deabce3e8a1594658b]
  [practitioner]; corroborated by anthropics/claude-code issue #59225 ("model is
  told Shell=PowerShell while hooks execute under bash — cross-shell foot-gun
  for hook authors") [https://github.com/anthropics/claude-code/issues/59225]
  [official repo, practitioner-filed issue].
- **Bash pre-expands PowerShell variables before PowerShell ever sees them.**
  When Claude Code runs inline PowerShell through Git Bash, `$_`, `$env:...`
  etc. get expanded (usually to empty) by bash first: `Where-Object {
  $_.Name }` becomes `Where-Object { .Name }`. Documented root cause of
  recurring "trivial PowerShell command fails for no visible reason" reports.
  — GitHub issue #331, puritysb/AgentDeck
  [https://github.com/puritysb/AgentDeck/issues/331] [practitioner]; also
  anthropics/claude-code #55727, #51430, #25414, #16225, #15471 (multiple
  independent Windows quoting/escaping bug reports)
  [https://github.com/anthropics/claude-code/issues/55727] and sibling issues
  [official repo].
- **The working fix practitioners report is a hook that blocks the
  failure-prone invocation shape, not better prompting.** Chrissy LeMaire
  (netnerds.net, 2026-02-07) added a `PreToolUse` hook that outright blocks
  `powershell.exe` and inline `pwsh -Command`/`-c`, forcing the pattern "write a
  `.ps1` file and run: `pwsh -NoProfile -File <script.ps1>`" — reported "zero
  failures" after. — [https://blog.netnerds.net/2026/02/claude-code-powershell-hooks/]
  [practitioner]. This is a concrete, reproducible mitigation Mike doesn't yet
  have codified as a hook (his RTK proxy rewrites commands but a
  PreToolUse block on raw inline PowerShell is a different, complementary
  layer).
- **HN sentiment data point (opinion, not measurement):** at least one
  practitioner comment states they "ignore all Skills, MCPs... viewing them as
  distractions that consume context and lead to worse performance" — labeled
  here as opinion, not a benchmark. [https://news.ycombinator.com/item?id=46994369]
  [practitioner/opinion].

---

## PATTERNS WORTH STEALING

| pattern | what it does | why it saves | source URL |
|---|---|---|---|
| Scripts-as-skill-content (execute, don't inline) | Bundle deterministic operations as real scripts inside a skill's `scripts/` dir; Claude runs them via bash and only the *output* enters context — the script body never does | Turns "agent regenerates near-identical script every session" into a zero-marginal-cost bash call; official guidance frames this as strictly better than generated code for reliability *and* tokens | [platform.claude.com best-practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices) [official] |
| "Lean SKILL.md, fat reference/" with domain-sharded reference files | Keep the always-loaded body under 500 lines; split by domain (e.g. `reference/finance.md`, `reference/sales.md`) so an unrelated query never pulls in irrelevant material | Claude reads only the one reference file a task needs; the rest cost zero tokens until touched — directly transferable to a tradekit skill like tk-data-health that could shard by venue/stream instead of one monolith | [platform.claude.com best-practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices) [official] |
| Plan-validate-execute pattern for batch/destructive ops | Agent first writes a structured plan file (e.g. `changes.json`), a script validates it, only then does the agent execute, then a script verifies | Catches errors before they touch real state — machine-verifiable checkpoint instead of trusting the agent's judgment on a batch of changes; a natural fit for tradekit's money-path / broker changes given the existing "review round before commit" red line | [platform.claude.com best-practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices) [official] |
| Evaluation-driven skill authoring (write 3 evals before writing the skill body) | Baseline Claude's behavior *without* the skill on representative tasks first, write minimal instructions to close the observed gap, iterate against the evals | Prevents "documenting imagined problems" — stops a skill (or Mike's proposed script-bank index) from growing past what real failures justify, which is exactly the growth pattern that causes skill shadowing | [platform.claude.com best-practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices) [official] |
| `context: fork` skills that dispatch to a subagent with model/effort override, directly from a skill's frontmatter | A skill can declare `context: fork` + `agent: <type>` and Claude Code starts an isolated subagent with the skill body as its whole prompt, no conversation history leakage | Gives skills a built-in escape hatch to the isolation Mike currently gets only via manual spawn-mvm dispatch — could collapse some of that boilerplate for skills that are always meant to run in the background/isolated | [code.claude.com/docs/en/skills](https://code.claude.com/docs/en/skills) [official] |
| `disable-model-invocation: true` + `allowed-tools` scoping on task-only skills | Marks a skill as user-invoked-only (never auto-triggered) and pre-approves an exact, narrow tool/command allowlist (e.g. `Bash(git add *) Bash(git commit *)`) | Removes both the "wrong skill auto-fires" risk (shadowing) and the permission-prompt friction for a known-safe, narrow command shape — a real alternative to a general script-bank for the specific "commit," "deploy," "run migration" scripts Mike keeps rewriting | [code.claude.com/docs/en/skills](https://code.claude.com/docs/en/skills) [official] |
| PreToolUse hook that blocks a failure-prone invocation *shape* rather than trying to prompt around it | Hard-block `powershell.exe` / inline `pwsh -Command` at the hook layer; the block message redirects the agent to the working `.ps1`-file pattern | Converts a recurring quoting/escaping failure into a zero-occurrence one, deterministically, instead of relying on the model remembering not to do it — directly answers Mike's "understanding what shell you run in" theory with a working fix rather than a documentation fix | [blog.netnerds.net](https://blog.netnerds.net/2026/02/claude-code-powershell-hooks/) [practitioner] |
| Hook matcher covering both shells (`"Bash|PowerShell"`) wherever a guard exists | Any safety/gate hook written for one shell tool silently doesn't apply to the other on a dual-shell Windows box | Closes a real, reported security/data-loss gap that is structurally identical to the one Mike's environment has (Bash tool primary, PowerShell tool also available) — worth an audit of tk-gate's own hooks for this exact gap | [GitHub gist, issue #69397](https://gist.github.com/yurukusa/efaaad17986bf18773ab114389219665/00495d63644b137e296e78deabce3e8a1594658b) [practitioner] |
| Skill-optimizer tooling (`skillit`) that scores and trims skills across a whole collection in one pass | Spins up parallel scorer agents against every installed skill, reports per-skill token cost and a rubric grade, and mechanically moves implementation detail out of the always-loaded body into `references/` | Turns "is my skill pipeline bloated" from a manual audit into a repeatable automated pass — complementary to RTK (which optimizes command *output*, not skill *definitions*) since it targets a cost RTK doesn't touch | [quintonwall.com](https://www.quintonwall.com/writing/using-skillit-to-optimize-claude-code-skills-at-scale) [practitioner] |

---

## SOURCE LIST

- https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview [official]
- https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices [official]
- https://claude.com/blog/skills-explained [official]
- https://claude.com/blog/steering-claude-code-skills-hooks-rules-subagents-and-more [official]
- https://code.claude.com/docs/en/skills [official]
- https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills [official]
- https://arxiv.org/abs/2605.24050 ("More Skills, Worse Agents? Skill Shadowing Degrades Performance When Expanding Skill Libraries") [official/primary research]
- https://arxiv.org/abs/2305.16291 (Voyager) [official/primary research]
- https://lowpassfilter.substack.com/p/your-agent-skill-library-is-quietly [practitioner]
- https://www.mindstudio.ai/blog/context-rot-claude-code-skills-bloated-files [practitioner]
- https://github.com/AgentTooligans/Agent-Tools [practitioner]
- https://blog.netnerds.net/2026/02/claude-code-powershell-hooks/ [practitioner]
- https://gist.github.com/yurukusa/efaaad17986bf18773ab114389219665/00495d63644b137e296e78deabce3e8a1594658b [practitioner]
- https://github.com/anthropics/claude-code/issues/59225 [official repo / practitioner-filed]
- https://github.com/anthropics/claude-code/issues/55727 [official repo / practitioner-filed]
- https://github.com/puritysb/AgentDeck/issues/331 [practitioner]
- https://www.quintonwall.com/writing/using-skillit-to-optimize-claude-code-skills-at-scale [practitioner]
- https://news.ycombinator.com/item?id=46994369 [practitioner/opinion]

Searched but not fetched in full (used only as discovery, not cited as evidence
above unless separately fetched): anthropics/claude-code issues #51430, #25414,
#16225, #15471 (additional Windows shell bug reports, same class as #55727,
not individually verified by fetch); arXiv 2608.02880 and 2608.06196 (skill
retrieval-architecture papers, not fetched, mentioned only as adjacent
literature); reddit r/ClaudeAI / r/ClaudeCode — **no prior-art thread found**
matching "agents keep rewriting throwaway scripts" specifically; searches
returned only generic blog coverage, not primary practitioner threads. Treat
the Reddit angle of the brief as **no prior art found**, not absence of
opinion — it may exist and simply wasn't surfaced by the queries run.

---

## FLAGS

- **Reddit/HN primary-source gap.** The brief asked specifically for r/ClaudeAI,
  r/ClaudeCode, and Hacker News threads on script-bank prior art and skill
  failure modes. Web search surfaced only secondary blog aggregations of HN/
  Reddit sentiment, not fetchable primary threads with real user reports. I did
  not find a way to search Reddit/HN directly with the tools available in this
  session (WebSearch is a general engine, not Reddit's or HN's own search).
  This means the "practitioner failure mode" evidence above leans on
  Substack/dev-blog writeups and GitHub issues rather than raw forum threads —
  still practitioner-sourced and dated 2026, but one hop more curated than the
  brief asked for.
- **"Skill shadowing" and "library drift" papers are both very recent
  preprints (May and earlier 2026), not peer-reviewed venues** — treated here
  as the best available primary evidence per the brief's instruction to prefer
  2025-2026 sources, but flagging that arXiv preprint status means the specific
  percentages (21%, 19%, -39.3pp, 0.26 vs 0.58 pass@1) have not gone through
  peer review.
- **No prior art found, and none invented, for the literal claim in Mike's
  proposal that a mandatory agent-facing index actually gets ignored/goes stale
  in the specific "committed script bank" shape he describes.** The closest
  analogues (skill-shadowing, library-drift papers) are about *skill*
  libraries specifically, which have a discovery mechanism Anthropic controls
  (description matching at startup). A hand-rolled script-bank index that
  Mike's own agents would have to `grep`/read via a CLAUDE.md instruction is a
  different retrieval mechanism than either Voyager's semantic retrieval or
  Anthropic's Skills metadata-matching, and no source examined here tested that
  specific shape. This gap is reported rather than filled.
- **rtk / RTK positioning:** I did not find independent (non-Mike) coverage of
  a tool literally named "rtk" for Claude Code token savings; the tools found
  in the same category (skillit, Headroom, Caveman, Agent-Tools) operate at a
  different layer (skill-definition trimming, tool-output compression,
  MCP-description compression) than what CLAUDE.md describes RTK doing
  (command-output filtering via a hook-rewritten CLI proxy). Treating these as
  adjacent, not overlapping — flagging in case Mike wants to confirm RTK's
  approach isn't already superseded by one of these.
