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
PROMPT_COLOR = (251, 191, 36)   # amber-400 (yellow/gold for Claude's ⚡)
USER_COLOR = (241, 245, 249)     # slate-50
HIGHLIGHT = (96, 165, 250)      # blue-400
SUCCESS = (52, 211, 153)        # emerald-400
ACCENT_COLOR = (129, 140, 248)  # indigo-400

FONT_SIZE = 12
LINE_HEIGHT = 19
MARGIN_LEFT = 16
MARGIN_TOP = 36

font_en_path = "/System/Library/Fonts/Menlo.ttc"
font_zh_path = "/System/Library/Fonts/STHeiti Medium.ttc"
font_en = ImageFont.truetype(font_en_path, FONT_SIZE)
font_zh = ImageFont.truetype(font_zh_path, FONT_SIZE)


def is_cjk(char):
    code = ord(char)
    # CJK Unified Ideographs
    if 0x4e00 <= code <= 0x9fff:
        return True
    # CJK Symbols and Punctuation
    if 0x3000 <= code <= 0x303f:
        return True
    # Fullwidth Forms (Chinese punctuation)
    if 0xff00 <= code <= 0xffef:
        return True
    # General punctuation like “”‘’
    if 0x2000 <= code <= 0x206f and char in '“”‘’':
        return True
    return False


def draw_text_mixed(draw, x, y, text, fill):
    for char in text:
        if is_cjk(char):
            draw.text((x, y), char, font=font_zh, fill=fill)
            x += font_zh.getlength(char)
        else:
            draw.text((x, y), char, font=font_en, fill=fill)
            x += font_en.getlength(char)
    return x


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
    draw_text_mixed(draw, WIDTH // 2 - 95, 6, "Claude Code — scholar-agent", DIM_COLOR)


class Terminal:
    def __init__(self):
        self.lines = []
        self.frames = []  # List of (Image, duration_in_ms)

    def add_line(self, line_data, color=TEXT_COLOR):
        self.lines.append((line_data, color))

    def update_last_line(self, line_data, color=TEXT_COLOR):
        if self.lines:
            self.lines[-1] = (line_data, color)
        else:
            self.lines.append((line_data, color))

    def render(self, show_cursor=False, cursor_frame=0, duration=60):
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
                    x = draw_text_mixed(draw, x, y, segment, seg_color)
            else:
                draw_text_mixed(draw, MARGIN_LEFT, y, text, color)
            y += LINE_HEIGHT

        # Draw cursor on the last visible line if typing
        if show_cursor:
            if cursor_frame % 6 < 4:
                last_line = visible_lines[-1][0]
                x_cursor = MARGIN_LEFT
                if isinstance(last_line, list):
                    for segment, _ in last_line:
                        for char in segment:
                            if is_cjk(char):
                                x_cursor += font_zh.getlength(char)
                            else:
                                x_cursor += font_en.getlength(char)
                else:
                    for char in last_line:
                        if is_cjk(char):
                            x_cursor += font_zh.getlength(char)
                        else:
                            x_cursor += font_en.getlength(char)
                
                y_cursor = MARGIN_TOP + (len(visible_lines) - 1) * LINE_HEIGHT
                draw.rectangle([x_cursor, y_cursor + 2, x_cursor + 8, y_cursor + 14], fill=USER_COLOR)

        self.frames.append((img, duration))


def type_text(terminal, prompt_prefix, text, color=TEXT_COLOR, pause_end_ms=1000):
    full_line = list(prompt_prefix) if isinstance(prompt_prefix, list) else [(prompt_prefix, TEXT_COLOR)]
    full_line.append(("", color))
    terminal.add_line(full_line)
    
    step = 1 if len(text) < 15 else 2
    for i in range(0, len(text) + 1, step):
        val = min(i, len(text))
        typed = text[:val]
        full_line[-1] = (typed, color)
        terminal.update_last_line(full_line)
        terminal.render(show_cursor=True, cursor_frame=val, duration=60)
        if val == len(text):
            break
            
    if pause_end_ms > 0:
        terminal.render(show_cursor=True, cursor_frame=len(text), duration=pause_end_ms)


def show_spinner(terminal, prefix, duration_frames=8, success_prefix="✓ ", success_text=None, success_color=SUCCESS, success_pause_ms=800):
    spinner_frames = ["/", "-", "\\", "|"]
    prefix_list = list(prefix) if isinstance(prefix, list) else [(prefix, TEXT_COLOR)]
    
    for f in range(duration_frames):
        char = spinner_frames[f % len(spinner_frames)]
        current_line = [(char + " ", HIGHLIGHT)] + prefix_list
        terminal.update_last_line(current_line)
        terminal.render(show_cursor=False, duration=80)
        
    if success_text is not None:
        final_line = [(success_prefix, success_color)] + (list(success_text) if isinstance(success_text, list) else [(success_text, TEXT_COLOR)])
        terminal.update_last_line(final_line)
        terminal.render(show_cursor=False, duration=success_pause_ms)


def generate_demo():
    terminal = Terminal()

    # ====== Startup ======
    terminal.add_line([("scholar-agent % ", DIM_COLOR)])
    type_text(terminal, [("scholar-agent % ", DIM_COLOR)], "claude", USER_COLOR, pause_end_ms=400)
    
    terminal.add_line("⚡ Claude Code v0.1.18", PROMPT_COLOR)
    terminal.add_line("Connected to MCP server: scholar-agent", DIM_COLOR)
    terminal.add_line("")
    
    # ====== Query 1 ======
    prompt = [("⚡ ", PROMPT_COLOR)]
    type_text(terminal, prompt, "我想学习MoE。用scholar-agent帮我找一些文章到本地并做笔记", USER_COLOR, pause_end_ms=1000)

    # Thinking process
    show_spinner(
        terminal,
        [("Thinking...", DIM_COLOR)],
        duration_frames=6,
        success_prefix="",
        success_text=[("I will search for papers on Mixture of Experts (MoE), download the SOTA paper, and analyze it.", TEXT_COLOR)],
        success_color=TEXT_COLOR,
        success_pause_ms=800
    )

    # Tool call 1: search_papers
    terminal.add_line("")
    show_spinner(
        terminal, 
        [("Calling tool: mcp__scholar-agent__search_papers", ACCENT_COLOR), ("(query=\"mixture of experts\", top_n=3)", DIM_COLOR)],
        duration_frames=8,
        success_prefix="✓ ",
        success_text=[("Tool output received (1.2s)", SUCCESS)],
        success_color=SUCCESS,
        success_pause_ms=800
    )

    # Display paper list
    terminal.add_line("Found 3 relevant papers on MoE:")
    terminal.add_line([("  1. \"Post Reasoning: Improving the Performance of Non-Thinking Models at No Cost\" (2605.06165)", TEXT_COLOR)])
    terminal.add_line([("  2. \"Switch Transformers: Scaling to Trillion Parameter Models\" (2101.03961)", TEXT_COLOR)])
    terminal.add_line([("  3. \"Outrageously Large Neural Networks: The Sparsely-Gated MoE Layer\" (1701.06538)", DIM_COLOR)])
    terminal.add_line("I will download and analyze the SOTA paper \"Post Reasoning\" as the canary target.", TEXT_COLOR)
    terminal.render(show_cursor=False, duration=1000)

    # Tool call 2: download_paper
    terminal.add_line("")
    show_spinner(
        terminal,
        [("Calling tool: mcp__scholar-agent__download_paper", ACCENT_COLOR), ("(paper_id=\"2605.06165\")", DIM_COLOR)],
        duration_frames=8,
        success_prefix="✓ ",
        success_text=[("Tool output received (0.8s)", SUCCESS)],
        success_color=SUCCESS,
        success_pause_ms=800
    )
    terminal.add_line("Paper PDF downloaded to: paper-notes/large-language-models/Post_Reasoning_Improving_...pdf", DIM_COLOR)
    terminal.render(show_cursor=False, duration=600)

    # Tool call 3: extract_paper_images
    terminal.add_line("")
    show_spinner(
        terminal,
        [("Calling tool: mcp__scholar-agent__extract_paper_images", ACCENT_COLOR), ("(paper_id=\"2605.06165\")", DIM_COLOR)],
        duration_frames=8,
        success_prefix="✓ ",
        success_text=[("Tool output received (1.0s)", SUCCESS)],
        success_color=SUCCESS,
        success_pause_ms=800
    )
    terminal.add_line("Extracted figures to: paper-notes/large-language-models/Post_Reasoning_Improving_.../images/", DIM_COLOR)
    terminal.render(show_cursor=False, duration=600)

    # Tool call 4: analyze_paper (Canary Staging)
    terminal.add_line("")
    show_spinner(
        terminal,
        [("Calling tool: mcp__scholar-agent__analyze_paper", ACCENT_COLOR), ("(paper_id=\"2605.06165\")", DIM_COLOR)],
        duration_frames=12,
        success_prefix="✓ ",
        success_text=[("Tool output received (3.5s)", SUCCESS)],
        success_color=SUCCESS,
        success_pause_ms=800
    )
    terminal.add_line("Generated draft analysis note at staging path: paper-notes/.staging/Post_Reasoning/note.md", DIM_COLOR)
    terminal.add_line("Now, I will run the validation CLI script to ensure the generated note conforms to the quality gates.", TEXT_COLOR)
    terminal.render(show_cursor=False, duration=1000)

    # Run validation CLI (validate_note)
    terminal.add_line("")
    terminal.add_line([("scholar-agent % ", DIM_COLOR)])
    type_text(terminal, [("scholar-agent % ", DIM_COLOR)], "python scripts/validate_note.py --note paper-notes/.staging/Post_Reasoning/note.md", USER_COLOR, pause_end_ms=600)
    
    # Validation stdout
    terminal.add_line("{", DIM_COLOR)
    terminal.add_line("  \"ok\": true,", SUCCESS)
    terminal.add_line("  \"note\": \"paper-notes/.staging/Post_Reasoning/note.md\",", DIM_COLOR)
    terminal.add_line("  \"paper_type\": \"generic\",", DIM_COLOR)
    terminal.add_line("  \"errors\": [],", DIM_COLOR)
    terminal.add_line("  \"warnings\": [\"dataset_fallback_used\"],", DIM_COLOR)
    terminal.add_line("  \"summary\": { \"has_frontmatter\": true, \"section_count\": 8, \"dataset_policy\": \"fallback\" }", DIM_COLOR)
    terminal.add_line("}", DIM_COLOR)
    terminal.add_line("Validation succeeded. I will now promote the note to its canonical location.", TEXT_COLOR)
    terminal.render(show_cursor=False, duration=1000)

    # Run promotion CLI (normalize_note_location)
    terminal.add_line("")
    terminal.add_line([("scholar-agent % ", DIM_COLOR)])
    
    promote_cmd = "python scripts/normalize_note_location.py --source paper-notes/.staging/Post_Reasoning/note.md --paper-notes-root paper-notes --domain large-language-models --paper-folder Post_Reasoning_Improving_the_Performance_of_Non-Thinking_Models_at_No_Cost --promote"
    
    type_text(terminal, [("scholar-agent % ", DIM_COLOR)], promote_cmd, USER_COLOR, pause_end_ms=600)
    
    # Promotion stdout
    terminal.add_line("{", DIM_COLOR)
    terminal.add_line("  \"ok\": true,", SUCCESS)
    terminal.add_line("  \"source\": \"paper-notes/.staging/Post_Reasoning/note.md\",", DIM_COLOR)
    terminal.add_line("  \"target\": \"paper-notes/large-language-models/Post_Reasoning_Improving_the_Performance_of_Non-Thinking_Models_at_No_Cost/Post_Reasoning_Improving_the_Performance_of_Non-Thinking_Models_at_No_Cost.md\"", SUCCESS)
    terminal.add_line("}", DIM_COLOR)
    terminal.add_line("Note promoted successfully! Re-indexing local knowledge base...", TEXT_COLOR)
    terminal.render(show_cursor=False, duration=1500)

    # Clear/Divider for Scene 2
    terminal.add_line("")
    terminal.add_line("─" * 68, DIM_COLOR)
    terminal.add_line("")

    # ====== Scene 2 ======
    # User asks next question
    type_text(terminal, prompt, "如何理解这篇 Post-Reasoning 论文的核心结论？", USER_COLOR, pause_end_ms=1000)

    show_spinner(
        terminal,
        [("Thinking...", DIM_COLOR)],
        duration_frames=6,
        success_prefix="",
        success_text=[("I will search the local knowledge base to retrieve the core findings of the paper.", TEXT_COLOR)],
        success_color=TEXT_COLOR,
        success_pause_ms=800
    )

    # Tool call 5: query_knowledge
    terminal.add_line("")
    show_spinner(
        terminal,
        [("Calling tool: mcp__scholar-agent__query_knowledge", ACCENT_COLOR), ("(query=\"Post-Reasoning 核心结论\", limit=3)", DIM_COLOR)],
        duration_frames=8,
        success_prefix="✓ ",
        success_text=[("Tool output received (0.2s)", SUCCESS)],
        success_color=SUCCESS,
        success_pause_ms=800
    )

    # Claude's response using the local note details
    terminal.add_line("根据本地文献库的记录，Post-Reasoning 的核心结论如下：", TEXT_COLOR)
    terminal.add_line([("  1. 后置推理有效性：", HIGHLIGHT), ("让模型先输出答案再生成论证，同样可以显著提升模型准确率。", TEXT_COLOR)], TEXT_COLOR)
    terminal.add_line([("  2. 零推理开销：", HIGHLIGHT), ("最终答案的生成无需等待中间 Reasoning Trace，可在首包中截断返回，省去 10x token 成本。", TEXT_COLOR)], TEXT_COLOR)
    terminal.add_line([("  3. 强跨域泛化：", HIGHLIGHT), ("通过掩码损失微调（PR SFT），纯数学数据训练的模型也能提升科学、逻辑推理性能。", TEXT_COLOR)], TEXT_COLOR)
    terminal.add_line("此回答完全基于本地索引检索（耗时 <0.05s），未调用外部模型或搜索引擎。", DIM_COLOR)

    # Final pause of 3 seconds
    terminal.render(show_cursor=False, duration=3000)

    # ====== Save GIF ======
    os.makedirs("assets", exist_ok=True)
    
    # Extract images and durations
    imgs = [f[0] for f in terminal.frames]
    durations = [f[1] for f in terminal.frames]
    
    imgs[0].save(
        "assets/demo.gif",
        save_all=True,
        append_images=imgs[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    print(f"Generated {len(imgs)} frames -> assets/demo.gif")
    print(f"File size: {os.path.getsize('assets/demo.gif') / 1024:.0f} KB")


if __name__ == "__main__":
    generate_demo()
