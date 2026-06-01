"""Generate a demo GIF showing Scholar Agent knowledge flywheel in action."""

from PIL import Image, ImageDraw, ImageFont
import os

# --- Config ---
WIDTH = 720
HEIGHT = 420
BG_COLOR = (15, 23, 42)       # slate-900
BORDER_COLOR = (51, 65, 85)    # slate-600
TITLEBAR_COLOR = (30, 41, 59)  # slate-800
TEXT_COLOR = (148, 163, 184)   # slate-400
USER_COLOR = (96, 165, 250)    # blue-400
AI_COLOR = (52, 211, 153)      # emerald-400
HIGHLIGHT = (251, 191, 36)     # amber-400
ACCENT = (59, 130, 246)        # blue-500
SUCCESS = (34, 197, 94)        # green-500
DIM = (71, 85, 105)            # slate-500

FONT_SIZE = 13
LINE_HEIGHT = 20
MARGIN_LEFT = 16
MARGIN_TOP = 36
PADDING = 10

font_path = "/System/Library/Fonts/Menlo.ttc"
font = ImageFont.truetype(font_path, FONT_SIZE)
font_bold = ImageFont.truetype(font_path, FONT_SIZE)


def draw_terminal_base(draw):
    """Draw terminal window chrome."""
    # Border
    draw.rounded_rectangle([0, 0, WIDTH - 1, HEIGHT - 1], radius=10, outline=BORDER_COLOR, width=1)
    # Title bar
    draw.rectangle([1, 1, WIDTH - 2, 28], fill=TITLEBAR_COLOR)
    # Traffic lights
    for i, color in enumerate([(239, 68, 68), (234, 179, 8), (34, 197, 94)]):
        draw.ellipse([14 + i * 20, 9, 14 + i * 20 + 12, 9 + 12], fill=color)
    # Title
    draw.text((WIDTH // 2 - 60, 6), "Scholar Agent", fill=TEXT_COLOR, font=font)


def draw_cursor(draw, x, y, frame_in_step):
    """Draw blinking cursor."""
    if frame_in_step % 6 < 4:
        draw.rectangle([x, y + 2, x + 8, y + 14], fill=USER_COLOR)


def render_frame(lines, cursor_pos=None, cursor_line=None, step_frame=0):
    """Render a single frame with the given lines."""
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)
    draw_terminal_base(draw)

    y = MARGIN_TOP
    for i, (text, color) in enumerate(lines):
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

    if cursor_pos is not None and cursor_line is not None:
        y_cursor = MARGIN_TOP + cursor_line * LINE_HEIGHT
        x_cursor = MARGIN_LEFT + font.getbbox(lines[cursor_line][0] if isinstance(lines[cursor_line][0], str) else "")[2]
        draw_cursor(draw, x_cursor, y_cursor, step_frame)

    return img


def typewriter_text(base_lines, target_line_idx, target_text, target_color, frames_per_char=2):
    """Generate frames for typewriter effect on a line."""
    frames = []
    for char_count in range(0, len(target_text) + 1):
        partial = target_text[:char_count]
        lines = [l for l in base_lines]
        lines[target_line_idx] = (partial, target_color)
        frames.append(render_frame(lines, step_frame=char_count))
    return frames


def pause_frames(lines, count=15):
    """Generate pause frames."""
    return [render_frame(lines, step_frame=i) for i in range(count)]


# --- Build the demo script ---
def generate_demo():
    all_frames = []

    # ====== Scene 1: First question ======
    # Show user typing a question
    s1_lines = [
        ("", TEXT_COLOR),
    ]
    frames = typewriter_text(s1_lines, 0, "> What is mixture of experts in LLMs?", USER_COLOR, frames_per_char=1)
    all_frames.extend(frames)

    s1_lines = [
        ([("> ", USER_COLOR), ("What is mixture of experts in LLMs?", TEXT_COLOR)], TEXT_COLOR),
        ("", TEXT_COLOR),
    ]
    all_frames.extend(pause_frames(s1_lines, 10))

    # AI researching
    research_text = "  Searching web + arXiv + Semantic Scholar..."
    for i in range(len(research_text) + 1):
        lines = [
            ([("> ", USER_COLOR), ("What is mixture of experts in LLMs?", TEXT_COLOR)], TEXT_COLOR),
            ("", TEXT_COLOR),
            (research_text[:i], DIM),
        ]
        all_frames.append(render_frame(lines, step_frame=i))

    # Show research result
    s1_result = [
        ([("> ", USER_COLOR), ("What is mixture of experts in LLMs?", TEXT_COLOR)], TEXT_COLOR),
        ("", TEXT_COLOR),
        ("  Searching web + arXiv + Semantic Scholar...", DIM),
        ("", TEXT_COLOR),
        ([("  Saved knowledge card: ", SUCCESS), ("mixture-of-experts.md", HIGHLIGHT)], TEXT_COLOR),
        ([("  Sources: ", DIM), ("3 papers + 2 web articles", TEXT_COLOR)], TEXT_COLOR),
        ([("  Confidence: ", DIM), ("high", SUCCESS)], TEXT_COLOR),
    ]
    all_frames.extend(pause_frames(s1_result, 30))

    # ====== Scene 2: Second question (local hit) ======
    s2_base = [
        ([("> ", USER_COLOR), ("What is mixture of experts in LLMs?", TEXT_COLOR)], TEXT_COLOR),
        ("", TEXT_COLOR),
        ("  Searching web + arXiv + Semantic Scholar...", DIM),
        ("", TEXT_COLOR),
        ([("  Saved knowledge card: ", SUCCESS), ("mixture-of-experts.md", HIGHLIGHT)], TEXT_COLOR),
        ([("  Sources: ", DIM), ("3 papers + 2 web articles", TEXT_COLOR)], TEXT_COLOR),
        ([("  Confidence: ", DIM), ("high", SUCCESS)], TEXT_COLOR),
        ("", TEXT_COLOR),
        ("─" * 60, BORDER_COLOR),
        ("", TEXT_COLOR),
    ]

    # User types similar question
    q2 = "> How does MoE routing work?"
    s2_with_q = s2_base + [(q2[:i], USER_COLOR) for i in range(len(q2) + 1)]
    for i in range(len(q2) + 1):
        lines = s2_base + [("", TEXT_COLOR), (q2[:i], USER_COLOR)]
        all_frames.append(render_frame(lines, step_frame=i))

    # Brief pause
    lines = s2_base + [("", TEXT_COLOR), ([("> ", USER_COLOR), ("How does MoE routing work?", TEXT_COLOR)], TEXT_COLOR)]
    all_frames.extend(pause_frames(lines, 8))

    # Local hit!
    hit_text = "  Local knowledge hit! (BM25 score: 0.94)"
    for i in range(len(hit_text) + 1):
        lines_full = s2_base + [
            ("", TEXT_COLOR),
            ([("> ", USER_COLOR), ("How does MoE routing work?", TEXT_COLOR)], TEXT_COLOR),
            ("", TEXT_COLOR),
            (hit_text[:i], SUCCESS),
        ]
        all_frames.append(render_frame(lines_full, step_frame=i))

    # Show the result from local
    s2_final = s2_base + [
        ("", TEXT_COLOR),
        ([("> ", USER_COLOR), ("How does MoE routing work?", TEXT_COLOR)], TEXT_COLOR),
        ("", TEXT_COLOR),
        ([("  Local knowledge hit! ", SUCCESS), ("(BM25 score: 0.94)", DIM)], TEXT_COLOR),
        ([("  Retrieved from: ", DIM), ("mixture-of-experts.md", HIGHLIGHT)], TEXT_COLOR),
        ([("  Response time: ", DIM), ("<0.1s", SUCCESS), (" (vs ~5s web research)", DIM)], TEXT_COLOR),
        ("", TEXT_COLOR),
        ([("  Knowledge base: ", DIM), ("33 cards", ACCENT), (" | Growing every query", DIM)], TEXT_COLOR),
    ]
    all_frames.extend(pause_frames(s2_final, 40))

    # ====== Scene 3: Academic pipeline ======
    s3_base = [
        ("", TEXT_COLOR),
        ("─" * 60, BORDER_COLOR),
        ("", TEXT_COLOR),
    ]

    q3 = "> search_papers(\"mixture of experts\", top_n=5)"
    for i in range(len(q3) + 1):
        lines = s2_final + s3_base + [("", TEXT_COLOR), (q3[:i], USER_COLOR)]
        all_frames.append(render_frame(lines, step_frame=i))

    lines = s2_final + s3_base + [("", TEXT_COLOR), ([("> ", USER_COLOR), ("search_papers(\"mixture of experts\", top_n=5)", TEXT_COLOR)], TEXT_COLOR)]
    all_frames.extend(pause_frames(lines, 8))

    # Results
    s3_result = s2_final + s3_base + [
        ("", TEXT_COLOR),
        ([("> ", USER_COLOR), ("search_papers(\"mixture of experts\", top_n=5)", TEXT_COLOR)], TEXT_COLOR),
        ("", TEXT_COLOR),
        ([("  #1 ", HIGHLIGHT), ("Switch Transformers (Fedus et al., 2024)", TEXT_COLOR)], TEXT_COLOR),
        ([("      Score: ", DIM), ("0.92", SUCCESS), (" | ", DIM), ("NeurIPS", ACCENT), (" | ", DIM), ("2.1k citations", TEXT_COLOR)], TEXT_COLOR),
        ([("  #2 ", HIGHLIGHT), ("Expert Choice Routing (Zhou et al., 2022)", TEXT_COLOR)], TEXT_COLOR),
        ([("      Score: ", DIM), ("0.87", SUCCESS), (" | ", DIM), ("ICLR", ACCENT), (" | ", DIM), ("890 citations", TEXT_COLOR)], TEXT_COLOR),
        ([("  #3 ", HIGHLIGHT), ("Soft MoE (Puigcerver et al., 2024)", TEXT_COLOR)], TEXT_COLOR),
        ([("      Score: ", DIM), ("0.83", SUCCESS), (" | ", DIM), ("ICLR", ACCENT), (" | ", DIM), ("340 citations", TEXT_COLOR)], TEXT_COLOR),
        ("", TEXT_COLOR),
        ([("  → ", SUCCESS), ("Run ", TEXT_COLOR), ("analyze_paper()", HIGHLIGHT), (" for deep analysis", TEXT_COLOR)], TEXT_COLOR),
    ]
    all_frames.extend(pause_frames(s3_result, 50))

    # Save
    os.makedirs("assets", exist_ok=True)
    all_frames[0].save(
        "assets/demo.gif",
        save_all=True,
        append_images=all_frames[1:],
        duration=60,
        loop=0,
        optimize=True,
    )
    print(f"Generated {len(all_frames)} frames → assets/demo.gif")
    print(f"File size: {os.path.getsize('assets/demo.gif') / 1024:.0f} KB")


if __name__ == "__main__":
    generate_demo()
