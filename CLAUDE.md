# Scholar Agent — Claude Code Project Rules

## Required System Dependencies

- **poppler** — Required for PDF page rendering (`brew install poppler` on macOS, `apt install poppler-utils` on Linux). Used by Claude Code to visually render PDF pages (diagrams, charts, formulas, layouts).
- **PyMuPDF** (`pip install PyMuPDF`) — Required for PDF text extraction. Listed in `pyproject.toml` under `[project.optional-dependencies] academic`.

## Paper Analysis Workflow

1. **Download PDF first**: Always `download_paper` before `analyze_paper` for best quality
2. **Render PDF pages visually**: Use poppler-based rendering to see figures, charts, and formulas in the paper
3. **Fill all placeholders**: When `analyze_paper` returns `pdf_text`, use it to fill ALL `<!-- LLM: -->` placeholders in the generated note. No placeholders should remain in the final output
4. **Sections must be distinct**: 方法概述 (method), 实验结果 (experiments), 深度分析 (analysis) must contain different content — method describes architecture, experiments has data tables, analysis evaluates strengths/weaknesses
5. **Quality self-check**: After writing the final note, verify `quality_check` in the response has no issues

## Restrictions

- Do NOT install additional system packages beyond poppler and PyMuPDF
- Do NOT batch-process multiple papers — analyze one paper at a time
- Do NOT leave `<!-- LLM: -->` placeholders in final notes
