"""Display-only navigation and formatting for the existing bounded Git patch.

Section names are labels, never action paths. Nothing here reads a repository.
The source text remains unchanged and selectable as plain text.
"""
import re

from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat, QFont


def _unquote(value):
    value = value.rstrip('\t\r\n')
    if not (value.startswith('"') and value.endswith('"')):
        return value
    source = value[1:-1]
    out = bytearray()
    escapes = {'a': 7, 'b': 8, 'f': 12, 'n': 10, 'r': 13, 't': 9, 'v': 11, '"': 34, '\\': 92}
    i = 0
    while i < len(source):
        if source[i] == '\\' and i + 1 < len(source):
            match = re.match(r'[0-7]{1,3}', source[i + 1:])
            if match:
                out.append(int(match[0], 8) % 256); i += len(match[0]) + 1; continue
            if source[i + 1] in escapes:
                out.append(escapes[source[i + 1]]); i += 2; continue
        out.extend(source[i].encode('utf-8')); i += 1
    return out.decode('utf-8', errors='replace')


def sections(patch):
    starts = list(re.finditer(r'^diff --git ', patch, re.MULTILINE))
    result = []
    for i, start in enumerate(starts):
        text = patch[start.start():starts[i + 1].start() if i + 1 < len(starts) else len(patch)]
        lines = text.splitlines()
        name, old, category = '', '', 'Modified'
        prefixed = True
        added = removed = 0
        in_hunk = False
        for line in lines[1:]:
            if line.startswith('@@ '):
                in_hunk = True; continue
            if in_hunk:
                added += line.startswith('+')
                removed += line.startswith('-')
                continue
            if line.startswith('+++ '): name = _unquote(line[4:]); prefixed = True
            elif line.startswith('--- '): old = _unquote(line[4:])
            elif line.startswith('rename to '): name = _unquote(line[10:]); category = 'Renamed'; prefixed = False
            elif line.startswith('new file mode '): category = 'Added'
            elif line.startswith('deleted file mode '): category = 'Deleted'
            elif line.startswith('Binary files ') or line == 'GIT binary patch': category = 'Binary'
        if name == '/dev/null': name = old
        if not name:
            head = lines[0][11:]
            tokens = re.fullmatch(r'("(?:[^"\\]|\\.)*"|\S+) ("(?:[^"\\]|\\.)*"|\S+)', head)
            same = re.fullmatch(r'a/(.+) b/\1', head)
            if tokens and _unquote(tokens[1]).startswith('a/') and _unquote(tokens[2]).startswith('b/'):
                name = _unquote(tokens[2])
            elif same: name = 'b/' + same[1]
        if prefixed and name.startswith(('a/', 'b/')): name = name[2:]
        # Do not let control characters impersonate another navigator row.
        name = ''.join(c if c.isprintable() else ' ' for c in name).strip()
        result.append({'id': str(i), 'label': name or f'Patch {i + 1}', 'kind': category,
                       'added': added, 'removed': removed, 'text': text})
    return result


class DiffHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self.enabled = True
        self.formats = {}

    def configure(self, added, removed, heading, muted, enabled):
        self.enabled = enabled
        self.formats = {}
        for key, color in [('add', added), ('remove', removed), ('heading', heading), ('muted', muted)]:
            style = QTextCharFormat()
            style.setForeground(QColor(color))
            if key in ('add', 'remove'):
                tint = QColor(color); tint.setAlphaF(.085); style.setBackground(tint)
            if key == 'heading': style.setFontWeight(QFont.DemiBold)
            self.formats[key] = style
        self.rehighlight()

    def highlightBlock(self, text):
        if not self.enabled or not self.formats:
            self.setCurrentBlockState(0); return
        in_hunk = self.previousBlockState() == 1
        if text.startswith('diff --git '): in_hunk = False
        if text.startswith('@@ '): in_hunk = True
        self.setCurrentBlockState(1 if in_hunk else 0)
        key = None
        if text.startswith(('diff --git ', '@@ ')): key = 'heading'
        elif not in_hunk and text.startswith(('--- ', '+++ ', 'index ', 'new file mode ', 'deleted file mode ', 'rename ', 'similarity index ')): key = 'muted'
        elif text.startswith('+'): key = 'add'
        elif text.startswith('-'): key = 'remove'
        if key:
            # Qt indexes UTF-16 units; Python's len counts Unicode code points.
            self.setFormat(0, len(text.encode('utf-16-le')) // 2, self.formats[key])
