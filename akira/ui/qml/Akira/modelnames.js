.pragma library

// Display-only filename cleanup. Exact names and paths remain in model details;
// route assignment always uses the original path, never this label.
function display(name) {
    if (!name || name === "—") return "Not assigned";
    var text = String(name).replace(/\.gguf$/i, "");
    text = text.replace(/[-_.](?:I?Q\d[^-]*|F16|BF16|FP16)$/i, "");
    return text.replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim() || name;
}

function detail(name, size) {
    var match = String(name || "").replace(/\.gguf$/i, "").match(/[-_.](I?Q\d[^-]*|F16|BF16|FP16)$/i);
    return (match ? match[1] + " · " : "") + (size || "");
}
