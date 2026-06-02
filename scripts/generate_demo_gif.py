"""Generate a highly realistic demo GIF representing a real Claude Code session with Scholar Agent."""

from PIL import Image, ImageDraw, ImageFont
import os

# --- Config ---
WIDTH = 720
HEIGHT = 520
MAX_LINES = 23

BG_COLOR = (15, 23, 42)        # slate-900
BORDER_COLOR = (51, 65, 85)     # slate-600
TITLEBAR_COLOR = (30, 41, 59)   # slate-800
TEXT_COLOR = (226, 232, 240)    # slate-200
DIM_COLOR = (100, 116, 139)     # slate-500
PROMPT_COLOR = (96, 165, 250)   # blue-400
USER_COLOR = (241, 245, 249)     # slate-50
HIGHLIGHT = (251, 191, 36)      # amber-400
SUCCESS = (52, 211, 153)        # emerald-400
ACCENT_COLOR = (129, 140, 248)  # indigo-400

FONT_SIZE = 12
LINE_HEIGHT = 19
MARGIN_LEFT = 16
MARGIN_TOP = 36

font_path = "/System/Library/Fonts/Menlo.ttc"
font = ImageFont.truetype(font_path, FONT_SIZE)


def draw_terminal_base(draw):
    """Draw terminal window chrome."""
    # Border
    draw.rounded_rectangle([0, 0, WIDTH - 1, HEIGHT - 1], radius=10, outline=BORDER_COLOR, width=1)
    # Title bar
    draw.rectangle([1, 1, WIDTH - 2, 28], fill=TITLEBAR_COLOR)
    # Window buttons
    for i, color in enumerate([(239, 68, 68), (234, 179, 8), (34, 197, 94)]):
        draw.ellipse([14 + i * 20, 9, 14 + i * 20 + 12, 9 + 12], fill=color)
    # Title
    draw.text((WIDTH // 2 - 95, 6), "Claude Code — scholar-agent", fill=DIM_COLOR, font=font)


class Terminal:
    def __init__(self):
        self.lines = []
        self.frames = []

    def add_line(self, line_data, color=TEXT_COLOR):
        self.lines.append((line_data, color))

    def update_last_line(self, line_data, color=TEXT_COLOR):
        if self.lines:
            self.lines[-1] = (line_data, color)
        else:
            self.lines.append((line_data, color))

    def render(self, show_cursor=False, cursor_frame=0):
        img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
        draw = ImageDraw.Draw(img)
        draw_terminal_base(draw)

        # Slice visible lines
        visible_lines = self.lines[-MAX_LINES:] if len(self.lines) > MAX_LINES else self.lines

        y = MARGIN_TOP
        for text, color in visible_lines:
            if text == "":
                y += LINE_HEIGHT // 2
                continue
            if isinstance(text, list):
                # Mixed color line
                x = MARGIN_LEFT
                for segment, seg_color in text:
                    draw.text((x, y), segment, fill=seg_color, font=font)
                    bbox = font.getbbox(segment)
                    x += bbox[2] - bbox[0]
            else:
                draw.text((MARGIN_LEFT, y), text, fill=color, font=font)
            y += LINE_HEIGHT

        # Draw cursor on the last visible line if typing
        if show_cursor:
            if cursor_frame % 6 < 4:
                last_line = visible_lines[-1][0]
                x_cursor = MARGIN_LEFT
                if isinstance(last_line, list):
                    for segment, _ in last_line:
                        bbox = font.getbbox(segment)
                        x_cursor += bbox[2] - bbox[0]
                else:
                    bbox = font.getbbox(last_line)
                    x_cursor += bbox[2] - bbox[0]
                
                y_cursor = MARGIN_TOP + (len(visible_lines) - 1) * LINE_HEIGHT
                draw.rectangle([x_cursor, y_cursor + 2, x_cursor + 8, y_cursor + 14], fill=USER_COLOR)

        self.frames.append(img)


def type_text(terminal, prompt_prefix, text, color=TEXT_COLOR, pause_end=5):
    full_line = list(prompt_prefix) if isinstance(prompt_prefix, list) else [(prompt_prefix, TEXT_COLOR)]
    full_line.append(("", color))
    terminal.add_line(full_line)
    
    for i in range(len(text) + 1):
        typed = text[:i]
        full_line[-1] = (typed, color)
        terminal.update_last_line(full_line)
        terminal.render(show_cursor=True, cursor_frame=i)
        
    for p in range(pause_end):
        terminal.render(show_cursor=True, cursor_frame=len(text) + p)


def show_spinner(terminal, prefix, duration_frames=12, success_prefix="✓ ", success_text=None, success_color=SUCCESS):
    spinner_frames = ["/", "-", "\\", "|"]
    prefix_list = list(prefix) if isinstance(prefix, list) else [(prefix, TEXT_COLOR)]
    
    for f in range(duration_frames):
        char = spinner_frames[f % len(spinner_frames)]
        current_line = [(char + " ", HIGHLIGHT)] + prefix_list
        terminal.update_last_line(current_line)
        terminal.render(show_cursor=False)
        
    if success_text is not None:
        final_line = [(success_prefix, success_color)] + (list(success_text) if isinstance(success_text, list) else [(success_text, TEXT_COLOR)])
        terminal.update_last_line(final_line)
        terminal.render(show_cursor=False)


def generate_demo():
    terminal = Terminal()

    # ====== Startup ======
    terminal.add_line([("scholar-agent $ ", DIM_COLOR)])
    type_text(terminal, [("scholar-agent $ ", DIM_COLOR)], "claude", USER_COLOR, pause_end=4)
    
    terminal.add_line("Claude Code v0.1.18", TEXT_COLOR)
    terminal.add_line("Connected to MCP server: scholar-agent (SKILL: scholar-agent)", DIM_COLOR)
    terminal.add_line("")
    
    # ====== Query 1 ======
    prompt = [("scholar-agent > ", PROMPT_COLOR)]
    type_text(terminal, prompt, "我想学习MoE。用scholar-agent帮我找一些文章到本地并做笔记", USER_COLOR, pause_end=8)

    terminal.add_line("I will execute the research workflow following the scholar-agent SKILL contract:", TEXT_COLOR)
    terminal.add_line("1. Inventory  2. Metadata Gate  3. Canary (Staging)  4. Validation  5. Promotion", DIM_COLOR)
    terminal.render(show_cursor=False)

    # Tool call 1: search_papers
    terminal.add_line("")
    show_spinner(
        terminal, 
        [("Call: scholar-agent:search_papers", ACCENT_COLOR), ("(query=\"mixture of experts\", top_n=3)", DIM_COLOR)],
        duration_frames=12,
        success_prefix="✓ ",
        success_text=[("search_papers", ACCENT_COLOR), (" returned 3 candidate papers on MoE", SUCCESS)],
        success_color=SUCCESS
    )

    # Display paper list (Inventory)
    terminal.add_line([("  → #1: ", HIGHLIGHT), ("Post Reasoning: Improving performance at no cost (2605.06165)", TEXT_COLOR)], TEXT_COLOR)
    terminal.add_line([("  → #2: ", HIGHLIGHT), ("Switch Transformers: Scaling to Trillion Parameters (2101.03961)", TEXT_COLOR)], TEXT_COLOR)
    terminal.render(show_cursor=False)

    # Tool call 2: download_paper
    terminal.add_line("Selected paper #1 (Post Reasoning) as canary target. Downloading PDF...", TEXT_COLOR)
    terminal.add_line("")
    show_spinner(
        terminal,
        [("Call: scholar-agent:download_paper", ACCENT_COLOR), ("(paper_id=\"2605.06165\")", DIM_COLOR)],
        duration_frames=10,
        success_prefix="✓ ",
        success_text=[("download_paper", ACCENT_COLOR), (" returned: { \"status\": \"ok\", \"path\": \"paper-notes/2605.pdf\" }", SUCCESS)],
        success_color=SUCCESS
    )

    # Tool call 3: extract_paper_images
    terminal.add_line("")
    show_spinner(
        terminal,
        [("Call: scholar-agent:extract_paper_images", ACCENT_COLOR), ("(paper_id=\"2605.06165\")", DIM_COLOR)],
        duration_frames=10,
        success_prefix="✓ ",
        success_text=[("extract_paper_images", ACCENT_COLOR), (" extracted 13 figures into images/", SUCCESS)],
        success_color=SUCCESS
    )

    # Tool call 4: analyze_paper (Canary Staging)
    terminal.add_line("Generating structured note in staging directory...", TEXT_COLOR)
    terminal.add_line("")
    show_spinner(
        terminal,
        [("Call: scholar-agent:analyze_paper", ACCENT_COLOR), ("(paper_id=\"2605.06165\")", DIM_COLOR)],
        duration_frames=18,
        success_prefix="✓ ",
        success_text=[("analyze_paper", ACCENT_COLOR), (" note written to paper-notes/.staging/Post_Reasoning/note.md", SUCCESS)],
        success_color=SUCCESS
    )

    # Run validation CLI (validate_note)
    terminal.add_line([("scholar-agent $ ", DIM_COLOR)])
    type_text(terminal, [("scholar-agent $ ", DIM_COLOR)], "python scripts/validate_note.py --note paper-notes/.staging/Post_Reasoning/note.md", USER_COLOR, pause_end=6)
    
    # Validation stdout
    terminal.add_line("{", DIM_COLOR)
    terminal.add_line("  \"ok\": true,", SUCCESS)
    terminal.add_line("  \"note\": \"/Users/zhoufangyi/scholar/paper-notes/.staging/Post_Reasoning/note.md\",", DIM_COLOR)
    terminal.add_line("  \"errors\": [], \"warnings\": [\"dataset_fallback_used\"]", DIM_COLOR)
    terminal.add_line("}", DIM_COLOR)
    terminal.render(show_cursor=False)

    # Run promotion CLI (normalize_note_location)
    terminal.add_line([("scholar-agent $ ", DIM_COLOR)])
    type_text(terminal, [("scholar-agent $ ", DIM_COLOR)], "python scripts/normalize_note_location.py --source paper-notes/.staging/Post_Reasoning/note.md --promote", USER_COLOR, pause_end=6)
    
    # Promotion stdout
    terminal.add_line("{", DIM_COLOR)
    terminal.add_line("  \"ok\": true,", SUCCESS)
    terminal.add_line("  \"target\": \"/Users/zhoufangyi/scholar/paper-notes/large-language-models/Post_Reasoning/...md\"", SUCCESS)
    terminal.add_line("}", DIM_COLOR)
    terminal.render(show_cursor=False)

    # Pause at the end of Scene 1
    for _ in range(25):
        terminal.render(show_cursor=False)

    # Separator
    terminal.add_line("─" * 68, DIM_COLOR)
    terminal.add_line("")

    # ====== Scene 2 ======
    # User asks next question
    type_text(terminal, prompt, "如何理解这篇 Post-Reasoning 论文的核心结论？", USER_COLOR, pause_end=8)

    terminal.add_line("Checking local knowledge index first to retrieve the card we just saved...", TEXT_COLOR)
    terminal.render(show_cursor=False)

    # Tool call 5: query_knowledge
    terminal.add_line("")
    show_spinner(
        terminal,
        [("Call: scholar-agent:query_knowledge", ACCENT_COLOR), ("(query=\"Post Reasoning 核心结论\")", DIM_COLOR)],
        duration_frames=12,
        success_prefix="✓ ",
        success_text=[("query_knowledge", ACCENT_COLOR), (" returned local hit in large-language-models/Post_Reasoning/...", SUCCESS)],
        success_color=SUCCESS
    )

    # Claude's response using the local note details
    terminal.add_line("根据本地文献库的记录，Post-Reasoning 的核心结论如下：", TEXT_COLOR)
    terminal.add_line([("  1. 后置推理有效性：", HIGHLIGHT), ("让模型先输出答案再生成论证，同样可以显著提升模型准确率。", TEXT_COLOR)], TEXT_COLOR)
    terminal.add_line([("  2. 零推理开销：", HIGHLIGHT), ("最终答案的生成无需等待中间 Reasoning Trace，可在首包中截断返回，省去 10x token 成本。", TEXT_COLOR)], TEXT_COLOR)
    terminal.add_line([("  3. 强跨域泛化：", HIGHLIGHT), ("通过掩码损失微调（PR SFT），纯数学数据训练的模型也能提升科学、逻辑推理性能。", TEXT_COLOR)], TEXT_COLOR)
    terminal.add_line("此回答完全基于本地索引检索（耗时 <0.05s），未调用外部模型或搜索引擎。", DIM_COLOR)

    # Final pause
    for _ in range(60):
        terminal.render(show_cursor=False)

    # ====== Save GIF ======
    os.makedirs("assets", exist_ok=True)
    terminal.frames[0].save(
        "assets/demo.gif",
        save_all=True,
        append_images=terminal.frames[1:],
        duration=65,
        loop=0,
        optimize=True,
    )
    print(f"Generated {len(terminal.frames)} frames -> assets/demo.gif")
    print(f"File size: {os.path.getsize('assets/demo.gif') / 1024:.0f} KB")


if __name__ == "__main__":
    generate_demo()
