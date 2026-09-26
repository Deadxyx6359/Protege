"""Making a picture (E1) and saving it where the person allows writing.

`make_image` makes the picture before the person is asked, so what they
approve is the picture itself, shown in the question; the one they saw is the
one saved. It writes a new PNG only, under `files.write` for its place, and
the picture is made on this computer's graphics card (see
`akira.core.making.images`). Nothing is kept but the file.
"""

from __future__ import annotations

import threading

from akira.core.making.images import SIDES, ImageError, ImageMaker, Picture
from akira.security.paths import PathViolation, real

from ..schema import Asking, Parameter, Requirement, Tool, ToolContext, ToolError, ToolResult

#: The picture made to be asked about, waiting to be saved: one, for one call.
_SHOWN: dict[tuple, Picture] = {}
_SHOWN_LOCK = threading.Lock()


def _key(arguments: dict) -> tuple:
    return (str(arguments["prompt"]), str(arguments["path"]), _side(arguments.get("width")),
            _side(arguments.get("height")), int(arguments.get("seed", -1)))


def _target(arguments: dict):
    wanted = str(arguments["path"]).strip()
    if not wanted.lower().endswith(".png"):
        raise ToolError("A picture is saved as a .png file.")
    try:
        path = real(wanted)
    except (PathViolation, OSError, ValueError) as exc:
        raise ToolError(f"{wanted} cannot be written: {exc}") from None
    if path.exists():
        raise ToolError(f"{path} already exists; choose a new name.")
    if not path.parent.is_dir():
        raise ToolError(f"{path.parent} is not a folder.")
    return path


def _side(value) -> int:
    """The allowed side nearest \a value: models ask for 800 by 600, and SDXL
    works in steps of 64, so asking again would only waste a step."""
    try:
        wanted = int(value or 512)
    except (TypeError, ValueError):
        wanted = 512
    return min(SIDES, key=lambda side: (abs(side - wanted), side))


def _make(arguments: dict) -> Picture:
    try:
        return ImageMaker().make(str(arguments["prompt"]),
                                 width=_side(arguments.get("width")),
                                 height=_side(arguments.get("height")),
                                 seed=int(arguments.get("seed", -1)))
    except ImageError as exc:
        raise ToolError(str(exc)) from None


def _describe(arguments: dict, context: ToolContext) -> Asking:
    path = _target(arguments)
    picture = _make(arguments)
    with _SHOWN_LOCK:
        _SHOWN.clear()
        _SHOWN[_key(arguments)] = picture
    return Asking(f"Save this picture as a new file:\n{path}\n\n"
                  f"It shows: {picture.prompt}\n"
                  f"{picture.width} by {picture.height}, seed {picture.seed}, "
                  f"made in {picture.seconds:g} seconds.", picture.png, kind="image/png")


def _run(arguments: dict, context: ToolContext) -> ToolResult:
    path = _target(arguments)
    with _SHOWN_LOCK:
        picture = _SHOWN.pop(_key(arguments), None)
    if picture is None:
        picture = _make(arguments)
    try:
        # "x": never over a file that appeared since it was checked.
        with path.open("xb") as stream:
            stream.write(picture.png)
    except OSError as exc:
        raise ToolError(f"{path} could not be written: {exc}") from None
    return ToolResult.success(
        f"Saved a {picture.width} by {picture.height} picture to {path} (seed {picture.seed}).",
        data={"path": str(path), "seed": picture.seed})


make_image = Tool(
    name="make_image",
    summary=("Make a picture from a description, on this computer's graphics card, and save it "
             "as a new PNG where the person allows writing. The person sees the picture before "
             "it is saved. Describe what it shows plainly: subject, setting, style, light."),
    parameters=(Parameter("prompt", "string", "What the picture shows."),
                Parameter("path", "string", "Full path of the new .png file."),
                Parameter("width", "integer", "Width in pixels, 384 to 1024; rounded to a "
                                              "step of 64.",
                          required=False, default=512),
                Parameter("height", "integer", "Height in pixels, 384 to 1024; rounded to a "
                                               "step of 64.",
                          required=False, default=512),
                Parameter("seed", "integer", "A number to make the same picture again; -1 for a "
                                             "new one.", required=False, default=-1)),
    requires=(Requirement("files.write", scope_from="path"),),
    reversible=False,
    run=_run,
    describe=_describe,
)


ALL = (make_image,)
