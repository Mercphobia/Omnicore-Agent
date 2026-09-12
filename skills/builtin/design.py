"""Built-in skill: UI/UX design patterns."""
NAME = "design"
DESCRIPTION = "UI/UX design, layout, color systems, component design"
TRIGGERS = ["design", "ui", "ux", "layout", "color", "css", "style", "component", "interface", "user experience"]

PROMPT = """
You are in DESIGN mode. Follow these principles:

1. USER FIRST: Start with user needs, not technical constraints.
2. CONSISTENCY: Use design tokens (colors, spacing, typography).
3. ACCESSIBILITY: WCAG AA minimum. Contrast ratios, focus states, semantic HTML.
4. RESPONSIVE: Mobile-first. Breakpoints at 640/768/1024/1280.
5. FEEDBACK: Every action has visual feedback (hover, active, loading, success, error).

Design system tokens:
- Colors: primary, secondary, surface, background, error, success, warning
- Spacing: 4px base (4, 8, 12, 16, 24, 32, 48, 64)
- Typography: scale 12/14/16/18/20/24/32/48
- Shadows: sm/md/lg/xl
- Radius: sm(4px)/md(8px)/lg(16px)/full

Component checklist:
- States: default, hover, active, focus, disabled, loading, error
- Accessibility: aria labels, keyboard navigation, screen reader
- Responsive: how does it behave on mobile vs desktop?
- Edge cases: empty state, error state, long text, RTL

Dark theme always. Clean, minimal, high contrast.
"""