.pragma library

/*!
    Split a reply into prose and code blocks.

    Code cannot be rendered by the same element as prose. Markdown text needs
    wrapping, proportional type and a reading measure; code needs none of those
    and is actively damaged by all three — a wrapped line of Python is harder to
    read than one that scrolls.

    Handles the streaming case: a fence that has been opened but not yet closed
    is treated as an open code block, so a snippet arriving token by token
    renders as code from its first line rather than flickering out of prose the
    moment the closing fence lands.
*/

var FENCE = "```";

/*!
    Parse \a text into an array of blocks.

    Each block is \c {{ type: "text"|"code", content: string, lang: string,
    open: bool }}. \c open marks a code block whose closing fence has not
    arrived — the view uses it to suppress the copy button on something still
    being written.
*/
function parse(text) {
    if (!text)
        return [];

    var blocks = [];
    var lines = text.split("\n");

    var inCode = false;
    var lang = "";
    var buffer = [];

    function flush(type, isOpen) {
        // A trailing blank line before a fence is an artefact of the fence, not
        // content; keeping it leaves a visible gap above every code block.
        while (buffer.length && buffer[buffer.length - 1].trim() === "")
            buffer.pop();
        if (type === "text")
            while (buffer.length && buffer[0].trim() === "")
                buffer.shift();

        if (buffer.length === 0) {
            buffer = [];
            return;
        }
        blocks.push({
            type: type,
            content: buffer.join("\n"),
            lang: type === "code" ? lang : "",
            open: !!isOpen
        });
        buffer = [];
    }

    for (var i = 0; i < lines.length; i++) {
        var line = lines[i];
        var trimmed = line.trim();

        if (trimmed.indexOf(FENCE) === 0) {
            if (inCode) {
                flush("code", false);
                inCode = false;
                lang = "";
            } else {
                flush("text", false);
                inCode = true;
                // ```python -> "python". Anything after the fence on the same
                // line is the language tag.
                lang = trimmed.substring(FENCE.length).trim().split(/\s+/)[0] || "";
            }
            continue;
        }

        buffer.push(line);
    }

    // Whatever is left. Still inside a fence means the block is unfinished.
    flush(inCode ? "code" : "text", inCode);

    return blocks;
}

/*! A human label for a fence tag. Empty tags are common and get no label. */
function languageLabel(lang) {
    if (!lang)
        return "";
    var known = {
        py: "Python", python: "Python",
        js: "JavaScript", javascript: "JavaScript",
        ts: "TypeScript", typescript: "TypeScript",
        qml: "QML", json: "JSON", yaml: "YAML", yml: "YAML",
        sh: "Shell", bash: "Shell", zsh: "Shell", powershell: "PowerShell",
        ps1: "PowerShell", sql: "SQL", html: "HTML", css: "CSS",
        cpp: "C++", c: "C", rs: "Rust", rust: "Rust", go: "Go",
        java: "Java", cs: "C#", rb: "Ruby", php: "PHP", md: "Markdown",
        diff: "Diff", xml: "XML", toml: "TOML", ini: "INI", text: ""
    };
    var key = lang.toLowerCase();
    if (known.hasOwnProperty(key))
        return known[key];
    return lang;
}
