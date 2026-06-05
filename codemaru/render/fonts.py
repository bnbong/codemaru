"""Card font stacks. Space Grotesk / JetBrains Mono are preferred (loaded as
webfonts on the generator page); the system stack is the fallback. GitHub's
README image sandbox won't load webfonts, so the card degrades to the system
stack there — the family lists make that graceful."""

# Single-quoted family names: these strings are placed inside double-quoted SVG
# attributes (font-family="..."), so inner quotes must be single to stay valid XML.
CARD_SANS = "'Space Grotesk', 'Segoe UI', Helvetica, Arial, sans-serif"
CARD_MONO = "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace"
