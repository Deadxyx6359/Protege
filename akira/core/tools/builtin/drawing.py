"""Drawing (E2): an agent draws in SVG, and Akira cleans it before it is seen or saved.

`save_drawing` writes a new file where the person allows writing
(`files.write`), as the SVG cleaned, or as a PNG of it. A drawing that cannot
be used is refused with the reason before anyone is asked, so the agent can fix
it and try again. Saving is irreversible, so the person sees the drawing
itself, rendered, before it is saved. See `akira.core.making.svg` for what
cleaning keeps. There is no tool that only checks a drawing: nothing is offered
without a grant, and checking needs none.
"""

from __future__ import annotations

from akira.core.making.svg import Drawing, DrawingError, clean, picture
from akira.security.paths import PathViolation, real

from ..schema import Asking, Parameter, Requirement, Tool, ToolContext, ToolError, ToolResult

#: A PNG is made this many pixels on its longer side.
PNG_SIZE = 1024

#: The picture the person is shown before saving.
PREVIEW_SIZE = 768


def _drawing(arguments: dict) -> Drawing:
    try:
        return clean(str(arguments["svg"]))
    except DrawingError as exc:
        raise ToolError(str(exc)) from None


def _left_out(drawing: Drawing) -> str:
    if not drawing.removed:
        return "Nothing was left out."
    return ("Left out, because a drawing may not run, fetch or embed anything: "
            + ", ".join(drawing.removed) + ".")


def _target(arguments: dict):
    """Where to save, and as what. Checked before the person is asked."""
    wanted = str(arguments["path"]).strip()
    suffix = wanted.lower().rsplit(".", 1)[-1] if "." in wanted else ""
    if suffix not in ("svg", "png"):
        raise ToolError("A drawing is saved as a .svg file, or as a picture in a .png file.")
    try:
        path = real(wanted)
    except (PathViolation, OSError, ValueError) as exc:
        raise ToolError(f"{wanted} cannot be written: {exc}") from None
    if path.exists():
        raise ToolError(f"{path} already exists; choose a new name.")
    if not path.parent.is_dir():
        raise ToolError(f"{path.parent} is not a folder.")
    return path, suffix


def _describe_save(arguments: dict, context: ToolContext) -> Asking:
    path, suffix = _target(arguments)
    drawing = _drawing(arguments)
    kind = "the drawing" if suffix == "svg" else f"a {PNG_SIZE}-pixel picture of the drawing"
    text = (f"Save {kind} as a new file:\n{path}\n\n"
            f"It is {drawing.width:g} by {drawing.height:g} units. {_left_out(drawing)}")
    preview = picture(drawing, PREVIEW_SIZE, "JPG")
    return Asking(text, preview or b"")


def _run_save(arguments: dict, context: ToolContext) -> ToolResult:
    path, suffix = _target(arguments)
    drawing = _drawing(arguments)
    if suffix == "svg":
        data = drawing.svg.encode("utf-8")
    else:
        data = picture(drawing, PNG_SIZE, "PNG")
        if data is None:
            raise ToolError("A picture can be made only while Akira's window is open. Save it "
                            "as .svg instead.")
    try:
        # "x": never over a file that appeared since it was checked.
        with path.open("xb") as stream:
            stream.write(data)
    except OSError as exc:
        raise ToolError(f"{path} could not be written: {exc}") from None
    return ToolResult.success(f"Saved the drawing to {path}. {_left_out(drawing)}",
                              data={"path": str(path), "removed": list(drawing.removed)})


save_drawing = Tool(
    name="save_drawing",
    summary=("Save an SVG drawing as a new file where the person allows writing: as .svg, or "
             "as a picture in a .png. It is cleaned first, so it cannot run or fetch anything, "
             "and the person sees it before it is saved."),
    parameters=(Parameter("path", "string", "Full path of the new .svg or .png file."),
                Parameter("svg", "string", "The whole SVG, from <svg> to </svg>.")),
    requires=(Requirement("files.write", scope_from="path"),),
    reversible=False,
    run=_run_save,
    describe=_describe_save,
)


ALL = (save_drawing,)
