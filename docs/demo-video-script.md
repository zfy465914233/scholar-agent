# Demo Video Script — "The Knowledge Flywheel in 3 Minutes"

**Format:** Screen recording (terminal + Obsidian side-by-side)  
**Duration:** ~3 minutes  
**Tool:** Loom / QuickTime / OBS  
**Target audience:** Developers and researchers who use Claude Code or VS Code Copilot  

---

## Setup Before Recording

```
~/scholar/           ← already has ~40 knowledge cards from previous sessions
claude code open     ← MCP connected, scholar-agent running
obsidian open        ← vault = ~/scholar/, graph view ready
```

Split screen: **Left = Claude Code terminal**, **Right = Obsidian Graph**

---

## Scene 1 — The Problem (0:00–0:25)

**Narration (voiceover or on-screen text):**
> "Every AI conversation is stateless. You ask the same question tomorrow — it starts from zero.  
> What if every question made your AI smarter instead?"

**On screen:** Show a standard Claude conversation where the user asks about "Mixture of Experts" and gets a generic answer — no memory of previous research.

---

## Scene 2 — Scholar Agent in Action (0:25–1:30)

**Step 1 — Ask a new question (0:25)**

In Claude Code, type:
```
@scholar explain the key differences between Sparse MoE and Dense MoE in LLMs
```

**What the viewer sees:**
- Scholar Agent `query_knowledge("Sparse MoE Dense MoE")` fires
- Local BM25 index returns a partial hit: `mixture-of-experts.md` (from a previous session)
- Claude uses the existing card as context — answer is already accurate and specific

**Narration:** *"It found what we already researched. <0.1s, no API call."*

**Step 2 — Ask something new (0:55)**

```
@scholar what's the training instability problem in expert routing?
```

**What the viewer sees:**
- Local miss → fallback to Semantic Scholar + arXiv
- Scholar Agent synthesizes answer from 3 papers
- Saves a new knowledge card: `expert-routing-instability.md`
- **Obsidian graph on the right updates live** — new node appears, linked to `mixture-of-experts.md`

**Narration:** *"New knowledge — researched, cited, saved. Now part of the graph."*

---

## Scene 3 — The Graph After 40 Questions (1:30–2:15)

**Switch to Obsidian full-screen graph view**

Show a knowledge graph with ~40 nodes:
- Clusters visible: `LLM/`, `qpe/`, `model_quantization/`, `markov_chain/`
- Zoom into MoE cluster: 5-6 cards, all linked by `[[wiki-links]]`
- Click one card — show the frontmatter: `status: trusted`, `confidence: 0.87`, citations listed

**Narration:**  
> *"After 40 questions in the LLM space, this is what the flywheel looks like.  
> Every card has evidence. Every claim has a source. And your AI draws from this — instantly — on every future question."*

---

## Scene 4 — Knowledge Lifecycle (2:15–2:35)

Show CLI command:
```bash
scholar-agent doctor
```

Output shows:
- 42 knowledge cards, 38 indexed
- 3 cards marked `stale` (older than 90 days, needs review)
- 1 card promoted to `trusted` this week

**Narration:**  
> *"Cards aren't just saved and forgotten. They have a lifecycle — draft, reviewed, trusted, stale, deprecated.  
> Your knowledge base stays accurate over time."*

---

## Scene 5 — Setup (2:35–2:55)

**On screen — terminal:**
```bash
pip install py-scholar-agent
scholar-agent init
# → Created ~/scholar/
# → MCP registered with Claude Code ✓
```

**Narration:**  
> *"Two commands. That's the entire setup.  
> Open source, MIT license, fully local — your data, your files."*

---

## Scene 6 — Call to Action (2:55–3:00)

**On screen:**
```
github.com/zfy465914233/scholar-agent
pip install py-scholar-agent
```

**Narration:**  
> *"The more you use it, the smarter it gets. Give it 50 questions. Then check the graph."*

---

## Recording Tips

1. **Pre-populate the knowledge base** — Run 40+ real research queries beforehand so the Obsidian graph looks rich
2. **Use a clean terminal** — Large font (18pt+), dark theme (iTerm2 Dracula or similar)
3. **Obsidian graph settings** — Enable "Show tags", set zoom to show ~20 nodes at once
4. **Speed up API calls** — Pre-cache the arXiv response so the "fallback to web" demo is fast (3-4s, not 15s)
5. **Add captions** — Loom auto-generates captions; review them before sharing
6. **Music** — Light lo-fi background at -20dB keeps energy without distraction

---

## Alternative: Static GIF Version (for Twitter/README)

If you don't want to record a full video, create an annotated GIF that shows:
1. Frame 1: Empty knowledge base
2. Frame 2–5: 5 questions asked, 5 cards saved (timelapse)
3. Frame 6: Obsidian graph with 5 connected nodes

Use [Gifox](https://gifox.app/) or [Kap](https://getkap.co/) for recording on macOS.
