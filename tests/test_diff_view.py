"""Patch navigation labels are display-only, including awkward Git filenames."""
from akira.ui.diff_view import sections


def test_hunk_lines_do_not_become_headers_or_sections():
    patch = ('stat header\n\ndiff --git a/app.py b/app.py\nindex old..new 100644\n'
             '--- a/app.py\n+++ b/app.py\n@@ -1,2 +1,3 @@\n-removed\n+added\n'
             '+diff --git a/fake b/fake\n+++ literal content\n context\n')
    found = sections(patch)
    assert len(found) == 1 and found[0]['label'] == 'app.py'
    assert found[0]['added'] == 3 and found[0]['removed'] == 1
    assert found[0]['text'] == patch[patch.index('diff --git'):]


def test_renames_unicode_binary_deletions_and_mode_only_patches():
    patch = ('diff --git a/old b/sub/new\nsimilarity index 100%\nrename from old\nrename to b/sub/new\n'
             'diff --git "a/caf\\303\\251.txt" "b/caf\\303\\251.txt"\nold mode 100644\nnew mode 100755\n'
             'diff --git a/image.png b/image.png\nBinary files a/image.png and b/image.png differ\n'
             'diff --git a/old.txt b/old.txt\ndeleted file mode 100644\n--- a/old.txt\n+++ /dev/null\n@@ -1 +0,0 @@\n-gone\n'
             'diff --git a/file with spaces b/file with spaces\nold mode 100644\nnew mode 100755\n')
    found = sections(patch)
    assert [r['label'] for r in found] == ['b/sub/new', 'café.txt', 'image.png', 'old.txt', 'file with spaces']
    assert [r['kind'] for r in found] == ['Renamed', 'Modified', 'Binary', 'Deleted', 'Modified']
    assert found[3]['removed'] == 1


def test_no_patch_and_unknown_headers_keep_raw_content_available():
    assert sections('No unstaged changes.') == []
    found = sections('diff --git unexpected header\nSomething new from Git\n')
    assert found[0]['label'] == 'Patch 1'
    assert 'Something new from Git' in found[0]['text']
