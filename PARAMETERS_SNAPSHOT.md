# Parameters Snapshot

Complete extraction of all tunable parameters, constants, thresholds, and formulas from the scholar-agent codebase. Each entry includes file path, line number, current value, and what it controls.

---

## 1. `scripts/academic/scoring.py`

### 1.1 Per-Dimension Ceiling

| Location | Parameter | Value | Controls |
|---|---|---|---|
| scoring.py:22 | `_CEILING` | `5.0` | Maximum score per dimension (fit, freshness, impact, rigor) |

### 1.2 Weight Profiles

| Location | Parameter | Value | Controls |
|---|---|---|---|
| scoring.py:25-30 | `_WEIGHTS_DEFAULT` | `{"fit": 0.34, "freshness": 0.14, "impact": 0.32, "rigor": 0.20}` | Default dimension weights for weighted recommendation score |
| scoring.py:31-36 | `_WEIGHTS_TRENDING` | `{"fit": 0.28, "freshness": 0.07, "impact": 0.45, "rigor": 0.20}` | Weights when ranking trending/hot papers |
| scoring.py:37-41 | `WEIGHTS_CONF` | `{"fit": 0.34, "impact": 0.38, "rigor": 0.28}` | Weights for conference papers (no freshness dimension) |

### 1.3 Relevance Scoring (Keyword Match Points)

| Location | Parameter | Value | Controls |
|---|---|---|---|
| scoring.py:44 | `_TITLE_PTS` | `1.0` | Points added when a domain keyword matches in the paper title |
| scoring.py:45 | `_ABSTRACT_PTS` | `0.3` | Points added when a domain keyword matches in the abstract |
| scoring.py:46 | `_CATEGORY_PTS` | `1.0` | Points added when the paper's arXiv category matches the domain config |

### 1.4 Quality Weighted Lexicon (Rigor Scoring)

| Location | Parameter | Value | Controls |
|---|---|---|---|
| scoring.py:50-88 | `_QUALITY_WEIGHTS` | See below | Weighted bag-of-words for rigor dimension. Sum all matching weights, cap at `_CEILING` (5.0) |

Full lexicon values:

```
# --- Theoretical rigor signals ---
"theorem": 0.50, "proof": 0.50, "proposition": 0.45, "lemma": 0.40,
"corollary": 0.40, "formal": 0.45, "formal verification": 0.50,
"axiomatic": 0.45, "derivation": 0.35, "rigorous": 0.40,
# --- Methodological depth ---
"principled": 0.45, "methodology": 0.40, "systematic": 0.35,
"theoretical analysis": 0.50, "theoretical framework": 0.45,
"complexity": 0.35, "convergence": 0.40, "bound": 0.35,
"optimal": 0.40, "optimality": 0.45, "guarantee": 0.40,
# --- Statistical / mathematical ---
"bayesian": 0.45, "calibration": 0.45, "likelihood": 0.40,
"probabilistic": 0.40, "estimation": 0.35, "variance": 0.30,
"bias": 0.30, "statistical": 0.40, "distribution": 0.30,
# --- Validation methodology ---
"validate": 0.40, "validation": 0.40, "verify": 0.40,
"verification": 0.45, "robustness": 0.40, "sensitivity analysis": 0.45,
"reproducib": 0.40, "fairness": 0.35,
# --- Technical depth (engineering) ---
"architecture": 0.30, "framework": 0.30, "algorithm": 0.30,
"module": 0.20, "pipeline": 0.25, "encoder": 0.25,
"decoder": 0.25, "backbone": 0.20, "attention mechanism": 0.35,
"training scheme": 0.20,
# --- Empirical rigor ---
"ablation": 0.40, "benchmark": 0.30, "baseline comparison": 0.35,
"statistical significance": 0.45, "cross-validation": 0.40,
"human evaluation": 0.45, "error analysis": 0.35,
# --- Novelty ---
"first": 0.30, "novel": 0.25, "new": 0.15, "unprecedented": 0.35,
"breakthrough": 0.40, "pioneering": 0.35, "innovative": 0.25,
"previously unexplored": 0.35,
# --- Performance claims ---
"state-of-the-art": 0.40, "sota": 0.40, "outperform": 0.35,
"surpass": 0.35, "superior": 0.30, "improves": 0.25,
"beats": 0.25, "significantly better": 0.35,
# --- Quantitative evidence ---
"accuracy": 0.20, "f1 score": 0.25, "bleu": 0.20, "rouge": 0.20,
"perplexity": 0.20, "auc": 0.20, "recall": 0.15, "precision": 0.15,
```

### 1.5 Normalization Formula

| Location | Parameter | Formula | Controls |
|---|---|---|---|
| scoring.py:172-177 | `_norm(v)` | `min(v / _CEILING * 10.0, 10.0)` | Linear mapping from raw dimension `[0, _CEILING]` to `[0, 10]` |

### 1.6 Fit Scoring: Keyword Deduplication

| Location | Parameter | Value | Controls |
|---|---|---|---|
| scoring.py:222-226 | Keyword dedup | `seen_words` set | Each unique keyword counted at most once per domain match |

### 1.7 Freshness Decay Formula

| Location | Parameter | Formula / Value | Controls |
|---|---|---|---|
| scoring.py:238 | Freshness cutoff | `age_days > 365` returns `0.0` | Papers older than 1 year get zero freshness |
| scoring.py:241 | Freshness decay | `3.0 * (1.0 - age_days / 365.0)` | Linear decay: 3.0 at day 0, ~1.0 at 180 days, ~0.0 at 365+ |

### 1.8 Impact Scoring

| Location | Parameter | Value / Formula | Controls |
|---|---|---|---|
| scoring.py:246 | Trending impact | `min(citations / 80.0, _CEILING)` | For trending mode, divide citations by 80, cap at 5.0 |
| scoring.py:250 | Impact, age <= 10 days | `2.2` | Flat impact for very new papers |
| scoring.py:252 | Impact, age <= 21 days | `1.6` | Flat impact for new papers |
| scoring.py:254 | Impact, age <= 45 days | `0.9` | Flat impact for recent papers |
| scoring.py:256 | Impact, default | `0.4` | Flat impact for all other papers |

---

## 2. `scripts/academic/arxiv_search.py`

### 2.1 API Endpoints and Field Specs

| Location | Parameter | Value | Controls |
|---|---|---|---|
| arxiv_search.py:40 | `_S2_SEARCH_URL` | `"https://api.semanticscholar.org/graph/v1/paper/search"` | Semantic Scholar search endpoint |
| arxiv_search.py:41-45 | `_S2_FIELDS` | `"externalIds,title,abstract,publicationDate,influentialCitationCount,citationCount,url,authors,authors.affiliations"` | Fields requested from S2 API |
| arxiv_search.py:47-50 | `_ATOM_NS` | `{"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}` | XML namespaces for arXiv Atom feed parsing |

### 2.2 Category-to-Query-Phrase Mapping

| Location | Parameter | Value | Controls |
|---|---|---|---|
| arxiv_search.py:53-61 | `_CATEGORY_PHRASES` | See below | Maps arXiv categories to descriptive phrases for S2 queries when no domain config keywords are available |

```
"cs.AI": "AI agent planning reasoning",
"cs.LG": "deep learning optimization generalization",
"cs.CL": "NLP language model text generation",
"cs.CV": "image recognition visual understanding",
"cs.MM": "multimodal audio video processing",
"cs.MA": "multi-agent coordination decentralised",
"cs.RO": "robot control perception navigation",
```

### 2.3 Throttling and Retry Constants

| Location | Parameter | Value | Controls |
|---|---|---|---|
| arxiv_search.py:63 | `_S2_BACKOFF` | `30` | Seconds to wait on S2 HTTP 429 (rate limit) |
| arxiv_search.py:64 | `_S2_INTER_QUERY_GAP` | `4` | Polite delay between S2 category queries (currently not directly used by the concurrent executor) |
| arxiv_search.py:107 | `max_tries` (default) | `3` | Retry attempts in `_with_retry` |
| arxiv_search.py:108 | `backoff_base` (default) | `2` | Exponential backoff base: wait = `backoff_base ^ (attempt + 1)` |

### 2.4 Date Window Constants

| Location | Parameter | Value | Controls |
|---|---|---|---|
| arxiv_search.py:140 | `recent_start` offset | `timedelta(days=30)` | arXiv search window start = target - 30 days |
| arxiv_search.py:141 | `recent_end` | `target` (now) | arXiv search window end = now |
| arxiv_search.py:142 | `year_start` offset | `timedelta(days=365)` | S2 hot-papers window start = target - 365 days |
| arxiv_search.py:143 | `year_end` offset | `timedelta(days=31)` | S2 hot-papers window end = target - 31 days |

### 2.5 Pipeline Parameters

| Location | Parameter | Value | Controls |
|---|---|---|---|
| arxiv_search.py:281 | `limit` (default) | `200` | Max arXiv results per query |
| arxiv_search.py:282 | `retries` (default) | `3` | Retry count for arXiv API |
| arxiv_search.py:383 | `limit` (S2) | `100` | S2 API per-query result limit |
| arxiv_search.py:376 | `top_k` (default) | `20` | Top-k S2 results to keep after normalization |
| arxiv_search.py:413 | `per_cat` (default) | `5` | S2 results per category in hot-paper sweep |
| arxiv_search.py:451 | `max_workers` | `min(len(unique), 4)` | ThreadPool concurrency cap for hot-paper queries |
| arxiv_search.py:501 | Default categories | `["cs.AI", "cs.LG", "cs.CL", "cs.CV"]` | Fallback arXiv categories when none specified |
| arxiv_search.py:526 | User query `top_k` | `10` | S2 results for user-provided query |

---

## 3. `scripts/academic/conf_search.py`

### 3.1 Conference Catalog

| Location | Parameter | Value | Controls |
|---|---|---|---|
| conf_search.py:46-57 | `_CONF_CATALOG` | See below | Maps venue names to DBLP specs (prefix, TOC format, label, arXiv categories) |

```
"CVPR":    dblp_prefix="conf/cvpr",   toc_fmt="cvpr{year}",    venue_label="CVPR",    arxiv_cats=("cs.CV",)
"ICCV":    dblp_prefix="conf/iccv",   toc_fmt="iccv{year}",    venue_label="ICCV",    arxiv_cats=("cs.CV",)
"ECCV":    dblp_prefix="conf/eccv",   toc_fmt=None,            venue_label="ECCV",    arxiv_cats=("cs.CV",)
"ICLR":    dblp_prefix="conf/iclr",   toc_fmt="iclr{year}",    venue_label="ICLR",    arxiv_cats=("cs.LG", "cs.AI")
"AAAI":    dblp_prefix="conf/aaai",   toc_fmt="aaai{year}",    venue_label="AAAI",    arxiv_cats=("cs.AI",)
"NeurIPS": dblp_prefix="conf/nips",   toc_fmt="neurips{year}", venue_label="NeurIPS", arxiv_cats=("cs.LG", "cs.AI", "cs.CL")
"ICML":    dblp_prefix="conf/icml",   toc_fmt="icml{year}",    venue_label="ICML",    arxiv_cats=("cs.LG",)
"MICCAI":  dblp_prefix="conf/miccai", toc_fmt=None,            venue_label="MICCAI",  arxiv_cats=("cs.CV", "eess.IV")
"ACL":     dblp_prefix="conf/acl",    toc_fmt="acl{year}",     venue_label="ACL",     arxiv_cats=("cs.CL",)
"EMNLP":   dblp_prefix="conf/emnlp",  toc_fmt=None,            venue_label="EMNLP",   arxiv_cats=("cs.CL",)
```

### 3.2 API Endpoints and Constants

| Location | Parameter | Value | Controls |
|---|---|---|---|
| conf_search.py:59 | `_S2_SEARCH_ENDPOINT` | `"https://api.semanticscholar.org/graph/v1/paper/search"` | S2 search endpoint for conference enrichment |
| conf_search.py:60 | `_S2_PAPER_FIELDS` | `"externalIds,title,abstract,influentialCitationCount,citationCount,url,authors,authors.affiliations"` | S2 fields for conference paper enrichment |
| conf_search.py:61 | `_S2_THROTTLE` | `30` | Seconds to wait on S2 rate limit (429) during conference enrichment |
| conf_search.py:64 | `_DBLP_API` | `"https://dblp.org/search/publ/api"` | DBLP search API endpoint |

### 3.3 Retry and Throttle Parameters

| Location | Parameter | Value | Controls |
|---|---|---|---|
| conf_search.py:104 | `max_retries` (default) | `3` | DBLP fetch retry count |
| conf_search.py:119 | Retry backoff formula | `int(1.5 ** attempt * 4)` | Wait time: attempt 0 = 4s, attempt 1 = 6s, attempt 2 = 9s |
| conf_search.py:196 | Inter-page delay | `1` second | Delay between DBLP pagination requests |
| conf_search.py:221 | Inter-venue delay | `1` second | Delay between venue searches |

### 3.4 Dedup and Matching Thresholds

| Location | Parameter | Value | Controls |
|---|---|---|---|
| conf_search.py:261 | S2 title similarity threshold | `0.55` | Dice coefficient minimum to accept S2 match |
| conf_search.py:233 | `per_query` (default) | `3` | Number of S2 results to request per title search |
| conf_search.py:248-249 | S2 enrichment retry count | `3` | Retries per title in batch search |

### 3.5 Pipeline Limits

| Location | Parameter | Value | Controls |
|---|---|---|---|
| conf_search.py:166 | `max_results` (default) | `1000` | Max DBLP papers to collect per venue |
| conf_search.py:172 | DBLP `batch_size` cap | `min(max_results, 1000)` | Max results per DBLP API page |
| conf_search.py:398 | S2 enrichment cap | `100` | Max papers sent for S2 enrichment in single-track mode |
| conf_search.py:418 | `max_enrich` (default) | `100` | Max papers sent for S2 enrichment in multi-year mode |
| conf_search.py:429 | Default multi-year venues | `["NeurIPS", "ICML", "ICLR", "CVPR", "ACL"]` | Venues searched in multi-year conference scan |
| conf_search.py:436 | `max_per_venue` (multi-year) | `200` | Max DBLP papers per venue in multi-year scan |
| conf_search.py:428 | Default year range | `2020 to current year` | Years scanned in multi-year search |

### 3.6 Impact Ranking Formula (Multi-Year)

| Location | Parameter | Formula | Controls |
|---|---|---|---|
| conf_search.py:472 | Impact score | `influentialCitationCount / (years_since + 1)` | Time-decayed impact ranking for multi-year conference papers |

---

## 4. `scripts/academic/image_extractor.py`

### 4.1 Image Format Constants

| Location | Parameter | Value | Controls |
|---|---|---|---|
| image_extractor.py:50 | `_IMAGE_EXTS` | `{".png", ".jpg", ".jpeg", ".pdf", ".eps", ".svg"}` | File extensions recognized as image files during source tarball extraction |
| image_extractor.py:51 | `_RASTER_EXTS` | `{".png", ".jpg", ".jpeg"}` | Extensions used for raster image discovery via glob |
| image_extractor.py:52 | `_NOISE_NAMES` | `{"logo", "icon", "badge", "banner", "watermark"}` | Filenames containing these words are filtered out as noise |

### 4.2 HTTP Constants

| Location | Parameter | Value | Controls |
|---|---|---|---|
| image_extractor.py:59 | `timeout` (default) | `60` seconds | HTTP request timeout for source tarball download |
| image_extractor.py:59 | `ua` (default) | `"scholar-agent/1.0 (research)"` | User-Agent header |
| image_extractor.py:130 | PDF download timeout | `120` seconds | HTTP timeout for PDF downloads |

### 4.3 PDF Extraction Parameters

| Location | Parameter | Value | Controls |
|---|---|---|---|
| image_extractor.py:146 | `max_chars` (default) | `80000` | Max characters extracted from PDF text (for BM25 indexing) |
| image_extractor.py:231 | `max_images` (default) | `20` | Maximum images to extract from PDF via embedded image extraction |
| image_extractor.py:232 | `min_bytes` (default) | `4000` | Minimum byte size for PDF-embedded images to be kept |

### 4.4 Fallback Threshold

| Location | Parameter | Value | Controls |
|---|---|---|---|
| image_extractor.py:331 | PDF fallback threshold | `< 2` | If source tarball yields fewer than 2 images, fall back to PDF extraction |

---

## 5. `scripts/academic/note_linker.py`

### 5.1 Related-Paper Discovery Parameters

| Location | Parameter | Value | Controls |
|---|---|---|---|
| note_linker.py:33 | `max_links` (default) | `5` | Maximum related-paper links returned by `discover_related_notes` |

### 5.2 Affinity Scoring Weights

| Location | Parameter | Value | Controls |
|---|---|---|---|
| note_linker.py:62 | Keyword overlap weight | `2.0` per shared keyword | Score added for each shared domain keyword |
| note_linker.py:66 | Domain match weight | `1.0` | Score added when papers share the same domain |
| note_linker.py:75 | Author overlap weight | `1.5` per shared author | Score added for each shared author |
| note_linker.py:83 | Title word overlap weight | `0.5` per overlapping word | Score added for each shared title word (minimum 2 overlap) |

### 5.3 Title Word Extraction

| Location | Parameter | Value | Controls |
|---|---|---|---|
| note_linker.py:48 | `_FILLER` words | `{"a", "an", "the", "of", "in", "for", "and", "with", "using"}` | English stop words excluded from title overlap computation |
| note_linker.py:45 | Author limit for overlap | `[:5]` | Only first 5 authors are considered for overlap |

### 5.4 Title Term Extraction Thresholds

| Location | Parameter | Value | Controls |
|---|---|---|---|
| note_linker.py:146 | Pre-colon segment max length | `30` chars | Pre-colon title segments longer than 30 chars are not extracted as terms |
| note_linker.py:148 | Hyphenated span min length | `4` | Capitalised hyphenated spans shorter than 4 chars are excluded |
| note_linker.py:152 | Excluded all-caps tokens | `{"AI", "ML", "NLP", "CV", "II", "III", "IV"}` | Acronyms excluded from keyword extraction |

### 5.5 KeywordIndex Stop Words

| Location | Parameter | Value | Controls |
|---|---|---|---|
| note_linker.py:171-176 | `STOP_WORDS` | `frozenset({"model", "learning", "network", "method", "approach", "based", "using", "system", "data", "training", "task", "paper", "results", "analysis", "performance", "problem", "framework", "algorithm", "feature", "input", "output", "layer", "attention", "deep", "neural", "representation"})` | Generic ML terms excluded from keyword indexing |

### 5.6 Keyword Index Filtering

| Location | Parameter | Value | Controls |
|---|---|---|---|
| note_linker.py:209 | Tag min length | `3` characters | Tags shorter than 3 chars are excluded from index |
| note_linker.py:215 | Term min length | `2` characters | Extracted terms shorter than 2 chars are excluded |
| note_linker.py:221 | Frequency filter | `len(stems) == 1` | Only keywords appearing in exactly one note are kept (unambiguous) |

---

## 6. `scripts/academic/paper_analyzer.py`

### 6.1 Filename Generation

| Location | Parameter | Value | Controls |
|---|---|---|---|
| paper_analyzer.py:26 | Max filename length | `120` characters | `slug[:120].rstrip('-')` -- title slug truncated to 120 chars |

### 6.2 Domain Tags Mapping (Chinese Notes)

| Location | Parameter | Value | Controls |
|---|---|---|---|
| paper_analyzer.py:540-546 | `domain_tags` (ZH) | See below | Maps domain names to YAML tags for Chinese notes |

```
"LLM与Agent": ["LLM", "Agent", "大模型"]
"运筹优化与库存规划": ["运筹优化", "库存规划", "供应链"]
"LLM": ["LLM", "Large-Language-Model"]
"多模态": ["多模态", "Multimodal", "VLM"]
"Agent": ["Agent", "Autonomous-Agent"]
```

### 6.3 Domain Tags Mapping (English Notes)

| Location | Parameter | Value | Controls |
|---|---|---|---|
| paper_analyzer.py:676-681 | `domain_tags` (EN) | See below | Maps domain names to YAML tags for English notes |

```
"LLM & Agents": ["LLM", "Autonomous-Agent"]
"LLM": ["LLM", "Large-Language-Model"]
"Multimodal": ["Multimodal", "VLM"]
"Agent": ["Agent", "Agentic-System"]
```

### 6.4 Frontmatter Field Order

| Location | Parameter | Value | Controls |
|---|---|---|---|
| paper_analyzer.py:578-591 | ZH frontmatter order | `title, paper_id, authors, domain, date, status, tags, related_papers, quality_score, created, updated` | YAML frontmatter field ordering for Chinese notes |
| paper_analyzer.py:713-726 | EN frontmatter order | Same as ZH | YAML frontmatter field ordering for English notes |

### 6.5 Other Constants

| Location | Parameter | Value | Controls |
|---|---|---|---|
| paper_analyzer.py:58 | Image embed width | `800` | `![[images/{fname}\|800]]` -- Obsidian image embed width |
| paper_analyzer.py:556 | Affiliation display limit | `3` | `affiliations[:3]` -- max affiliations shown in note |
| paper_analyzer.py:639 | Related papers link limit | `5` | `related_papers[:5]` -- max wikilinks in Related Papers section |
| paper_analyzer.py:821 | Author display limit | `5` | `authors[:5]` -- max authors shown in core info |

---

## 7. `mcp_server.py` -- Default Config Section

### 7.1 Fallback Research Domains (search_papers)

| Location | Parameter | Value | Controls |
|---|---|---|---|
| mcp_server.py:628-636 | Default config | See below | Hardcoded fallback when no config file and no `.scholar.json` found |

```python
config = {
    "research_domains": {
        "deep-learning": {
            "keywords": ["deep learning", "neural network", "representation learning"],
            "arxiv_categories": ["cs.LG", "cs.AI"],
            "priority": 3,
        },
    },
    "excluded_keywords": ["tutorial", "bibliography"],
}
```

### 7.2 Parameter Clamping Ranges

| Location | Parameter | Range | Controls |
|---|---|---|---|
| mcp_server.py:607 | `max_results` clamp | `[1, 500]` | Maximum arXiv results user can request |
| mcp_server.py:608 | `top_n` clamp | `[1, 50]` | Maximum top-N papers returned |
| mcp_server.py:654 | Summary truncation | `500` chars | Paper summaries truncated to 500 chars + "..." in API response |
| mcp_server.py:744 | Abstract truncation | `500` chars | Conference paper abstracts truncated to 500 chars + "..." |
| mcp_server.py:554 | Title sanitize max length | `120` chars | `_sanitize_title` truncation limit |
| mcp_server.py:1141 | `top_n` clamp (daily) | `[1, 50]` | Daily recommend top-N clamping |

### 7.3 Lock and Refresh Constants

| Location | Parameter | Value | Controls |
|---|---|---|---|
| mcp_server.py:142 | Lock wait deadline | `2.0` seconds | Max time to wait for another process's index refresh lock |
| mcp_server.py:147 | Lock poll interval | `0.05` seconds | Sleep between lock file existence checks |

### 7.4 Tool Default Parameters (MCP API)

| Location | Parameter | Default | Controls |
|---|---|---|---|
| mcp_server.py:581 | `categories` | `"cs.AI,cs.LG,cs.CL,cs.CV"` | Default arXiv categories for search_papers |
| mcp_server.py:582 | `max_results` | `200` | Default max arXiv results |
| mcp_server.py:583 | `top_n` | `10` | Default top-N papers returned |
| mcp_server.py:661 | `venues` | `"CVPR,ICLR,NeurIPS,ICML"` | Default conference venues |
| mcp_server.py:665 | `top_n` (conf) | `10` | Default top-N conference papers |
| mcp_server.py:1119 | `top_n` (daily) | `10` | Default top-N daily recommendations |
| mcp_server.py:1122 | `dual_track` | `True` | Default dual-track mode for daily recommendations |
| mcp_server.py:165 | `limit` (query_knowledge) | `5` | Default number of knowledge search results |
| mcp_server.py:175 | `limit` clamp | `[1, 50]` | Valid range for knowledge query limit |

---

## 8. `scripts/close_knowledge_loop.py` -- Quality Gate Constants

(Referenced by mcp_server.py via import)

| Location | Parameter | Value | Controls |
|---|---|---|---|
| close_knowledge_loop.py:198 | `QUALITY_THRESHOLD_SAVE_RESEARCH` | `0.30` | Minimum quality score for save_research |
| close_knowledge_loop.py:199 | `QUALITY_THRESHOLD_CAPTURE_ANSWER` | `0.20` | Minimum quality score for capture_answer |
| close_knowledge_loop.py:200 | `MIN_ANSWER_LENGTH_SAVE` | `200` chars | Hard minimum answer length for save_research |
| close_knowledge_loop.py:201 | `MIN_ANSWER_LENGTH_CAPTURE` | `150` chars | Hard minimum answer length for capture_answer |
| close_knowledge_loop.py:202 | `MIN_CLAIMS_SAVE` | `1` | Minimum supporting_claims for save_research |
| close_knowledge_loop.py:203 | `MIN_CLAIM_TEXT_LENGTH` | `20` chars | Minimum length of each claim text |

### Quality Scoring Formula

| Location | Component | Formula | Max Score |
|---|---|---|---|
| close_knowledge_loop.py:256 | `answer_length_score` | `min(answer_len / 500, 1.0) * 0.3` | 0.3 |
| close_knowledge_loop.py:257 | `claims_score` | `min(num_claims / 3, 1.0) * 0.3` | 0.3 |
| close_knowledge_loop.py:262 | `claim_depth_score` | `min(avg_claim_len / 50, 1.0) * 0.2` | 0.2 |
| close_knowledge_loop.py:270 | `structural_richness` | `filled_optional_fields * 0.05` (max 4 optional fields) | 0.2 |
| close_knowledge_loop.py:272-273 | **Total** | `answer_length_score + claims_score + claim_depth_score + structural_richness` | **1.0** |

Optional fields that contribute to structural richness: `inferences`, `uncertainty`, `missing_evidence`, `suggested_next_steps`
