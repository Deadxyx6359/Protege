# Claude → Codex: firmware help, from a replica of the Sharp display project

The person asked Claude to rebuild their "STM32 Sharp display hello world"
project with Akira alone, fixing Akira along the way, to see how far it gets
on a problem like that. Nothing in the interface changed; this is for anyone
working on chat answers about hardware, or on the agents.

## What was tried

A copy of the person's CubeMX project with their driver and code taken out
(`scratch/replica`, ignored by git), then:

1. The chat, asked the person's original question with the wiring in words.
2. The software team (architect, implementer, reviewer), asked to write the
   driver into the project, call it from `main.c`, add it to the build and
   build it, with Adafruit's Arduino driver linked as the reference.

## What changed in Akira

- **Pins** (`akira/core/brain/pins.py`): a board's Arduino-style connector
  map (NUCLEO-G474RE, checked against Mbed's published map), what every pin
  can carry and what the board puts on it, from STM32CubeMX's database when
  its folder is in the library, a wire-by-wire check of wiring the person
  describes with a verdict, and a "Check the pins:" line under an answer that
  misreads the board or the chip.
- **Grounding**: wiring words (CLK, DI, CS, SDA) count as the bus they belong
  to; CubeMX's own names (`MX_SPI1_Init`, `hspi1`, `SPI1_SCK`, `GPIO_Output`)
  are no longer called made up.
- **Reading code on the web**: a GitHub file link is read from GitHub's file
  site (asked about like any site); source code is kept whole up to 9,500
  characters; research reads the search result most about the question.
- **Agents**: `edit_file` (one piece of a file, found once and replaced, asked
  each time); `build_project` (CMake presets, under `shell.run`, asked once per
  piece of work); notes on an STM32CubeMX project's layout given to any agent
  working in one (`akira/core/agents/workspaces.py`); the architect may read a
  page the task gives; the implementer has 16 steps and room for a whole file;
  old tool results are cut when a run outgrows the model's window; Windows
  paths with single backslashes in a tool call no longer lose the call; and an
  answer that only says it is coming is not taken for the answer.

## What it showed

- **The chat** went from the wrong pins (D13 read as PA13), an OLED's Arduino
  library and Arduino C++, to the right pins, SPI1 on PA5 and PA7 with PB6 as a
  GPIO chip select, the right clock mode, and the person's wiring confirmed.
  It still did not know the display's protocol (least significant bit first,
  chip select active high, VCOM toggled), even with Adafruit's driver read for
  it: the 8B model called that driver "not suitable" rather than taking the
  protocol from it.
- **The team**, over four runs, came to find its way around the project, write
  the driver's two files, add the file to `CMakeLists.txt` with `edit_file`,
  build, and get the compiler's errors back. It never wrote a working driver:
  each was a placeholder that sent the text's bytes straight to the display.
  The architect read Adafruit's driver and planned without its protocol.
- **The coding model** (Qwen2.5-Coder-7B) as the implementer built the project
  untouched and said it would show "Hello World!". That is why an agent that
  could change files and only checked them is now told it changed nothing.

So: the plumbing for firmware work is there, and the pins are now right, but
writing a driver from a part's protocol is beyond the local models. A larger
model on the same route, or the person writing the protocol into the task, is
what would close the gap.

## Watch out for

- `pins.BOARDS` holds only maps checked against a published source. Add a
  board only the same way; a guessed map is worse than none.
- STM32CubeMX's database is read only when its folder is in the library and
  allowed for reading, like any other file.
