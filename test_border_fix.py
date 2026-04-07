import sys

def patch_input_window():
    filepath = 'ui/input_window.py'
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Let's cleanly set background: transparent without WA_NoSystemBackground
    import re
    if 'self.setStyleSheet(' not in content.split('def _setup_window')[1][:500]:
        content = content.replace('self.setFixedWidth(_WIN_W)', 'self.setFixedWidth(_WIN_W)\n        self.setStyleSheet("background:transparent; border:none; outline:none;")')

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

patch_input_window()
