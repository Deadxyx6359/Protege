"""Firmware: a chip's registers from its own header, boards through ST's programmer,
serial ports, STM32CubeMX projects, and the tools agents use for them. ST's programs
and the boards are stand-ins; nothing here touches hardware."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from akira.core.firmware import boards, cubemx, registers
from akira.core.permissions import AuditLog, Policy, SecretStore
from akira.core.tools import default_registry
from akira.core.tools.schema import ToolContext

HEADER = """
#define PERIPH_BASE           (0x40000000UL) /*!< Peripheral base address */
#define APB2PERIPH_BASE       (PERIPH_BASE + 0x00010000UL)
#define SPI1_BASE             (APB2PERIPH_BASE + 0x3000UL)
#define GPIOA_BASE            (0x48000000UL)
typedef struct
{
  __IO uint32_t CR1;      /*!< SPI Control register 1, Address offset: 0x00 */
  __IO uint32_t CR2;      /*!< SPI Control register 2, Address offset: 0x04 */
  uint32_t RESERVED1[2];  /*!< Reserved */
  __IO uint16_t DR;       /*!< data register */
} SPI_TypeDef;
typedef struct
{
  __IO uint32_t MODER;
  __IO uint32_t AFR[2];
} GPIO_TypeDef;
#define SPI1                ((SPI_TypeDef *) SPI1_BASE)
#define GPIOA               ((GPIO_TypeDef *) GPIOA_BASE)
#define SPI_CR1_MSTR_Pos            (2U)
#define SPI_CR1_MSTR_Msk            (0x1UL << SPI_CR1_MSTR_Pos)
#define SPI_CR1_MSTR                SPI_CR1_MSTR_Msk           /*!<Master Selection */
#define SPI_CR1_BR_Pos              (3U)
#define SPI_CR1_BR_Msk              (0x7UL << SPI_CR1_BR_Pos)
#define SPI_CR1_BR                  SPI_CR1_BR_Msk             /*!<Baud Rate Control */
#define SPI_CR1_LSBFIRST_Pos        (7U)
#define SPI_CR1_LSBFIRST_Msk        (0x1UL << SPI_CR1_LSBFIRST_Pos)
#define SPI_CR1_LSBFIRST            SPI_CR1_LSBFIRST_Msk       /*!<Frame Format */
"""


# -- registers ---------------------------------------------------------------------------------


def test_a_register_is_found_by_name_from_the_header():
    mapped = registers.DeviceMap.from_header(HEADER)
    _peripheral, register, address = mapped.find("spi1.cr2")
    assert address == 0x40013004 and register.size == 4
    assert mapped.find("SPI1.DR")[2] == 0x40013010, "after CR2 and two reserved words"
    assert mapped.find("GPIOA.AFR[1]")[2] == 0x48000008


def test_a_value_is_said_field_by_field():
    mapped = registers.DeviceMap.from_header(HEADER)
    _peripheral, register, address = mapped.find("SPI1.CR1")
    said = registers.described("SPI1.CR1", register, address, 0xBC)
    assert said.splitlines()[0] == "SPI1.CR1 (0x40013000) = 0x000000BC"
    assert "  MSTR = 1  [bit 2]  (Master Selection)" in said
    assert "  BR = 7  [bits 5:3]  (Baud Rate Control)" in said
    assert "  LSBFIRST = 1  [bit 7]  (Frame Format)" in said


def test_a_name_not_there_says_what_is():
    mapped = registers.DeviceMap.from_header(HEADER)
    with pytest.raises(KeyError, match="it has CR1, CR2, DR"):
        mapped.find("SPI1.CR3")
    with pytest.raises(KeyError, match="there is SPI1"):
        mapped.find("SPI2.CR1")


def test_the_device_header_is_found_for_a_part(tmp_path):
    include = tmp_path / "Drivers" / "CMSIS" / "Device" / "ST" / "STM32G4xx" / "Include"
    include.mkdir(parents=True)
    (include / "stm32g474xx.h").write_text(HEADER)
    assert registers.header_for("STM32G474RETx", [tmp_path]) == include / "stm32g474xx.h"
    assert registers.header_for("STM32F401RE", [tmp_path]) is None


# -- ST's programmer -----------------------------------------------------------------------------


class Programmer:
    """Stands in for STM32_Programmer_CLI: answers by its arguments, keeps them."""

    def __init__(self, monkeypatch, out, code=0):
        self.calls = []
        monkeypatch.setattr(boards, "programmer", lambda: Path("STM32_Programmer_CLI.exe"))

        def run(argv, **_):
            self.calls.append(argv[1:])
            return SimpleNamespace(returncode=code, stdout=out, stderr="")

        monkeypatch.setattr(boards.subprocess, "run", run)


PROBES = """===== STLink Interface =====
-------- Connected ST-LINK Probes List --------
ST-Link Probe 0 :
   ST-LINK SN  : 004A00383234510A33353533
   ST-LINK FW  : V3J7M2
   Board Name  : NUCLEO-G474RE
"""


def test_the_connected_probes_are_listed(monkeypatch):
    Programmer(monkeypatch, PROBES)
    assert boards.probes() == [boards.Probe("004A00383234510A33353533", "NUCLEO-G474RE",
                                            "V3J7M2")]


def test_memory_is_read_without_stopping_the_chip(monkeypatch):
    fake = Programmer(monkeypatch, "Reading 32-bit memory content\n\n0x40013000 : 0000037C "
                                   "00000700\n")
    assert boards.read_words(0x40013000, 2) == [0x37C, 0x700]
    assert fake.calls[0][:3] == ["-c", "port=SWD", "mode=HOTPLUG"], "hot-plug: no reset, no halt"
    assert fake.calls[0][3:] == ["-r32", "0x40013000", "8"]
    with pytest.raises(boards.BoardError, match="word's address"):
        boards.read_words(0x40013002)


def test_a_board_not_there_is_said_with_what_to_check(monkeypatch):
    Programmer(monkeypatch, "Error: No STM32 target found!", code=1)
    with pytest.raises(boards.BoardError, match="plugged in by USB"):
        boards.read_words(0x40013000)


def test_flashing_writes_verifies_and_restarts(monkeypatch, tmp_path):
    fake = Programmer(monkeypatch, "Memory Programming ...\nFile download complete\n"
                                   "Download verified successfully\nMCU Reset\n")
    image = tmp_path / "Display.elf"
    image.write_bytes(b"\x7fELF")
    said = boards.flash(image)
    assert fake.calls[0] == ["-c", "port=SWD", "-w", str(image), "-v", "-rst"]
    assert "Download verified successfully" in said
    binary = tmp_path / "Display.bin"
    binary.write_bytes(b"\0")
    boards.flash(binary)
    assert fake.calls[1][2:5] == ["-w", str(binary), "0x08000000"], "a .bin goes to flash's start"
    with pytest.raises(boards.BoardError, match="built program"):
        boards.flash(tmp_path / "main.c")


def test_without_the_programmer_it_says_where_to_get_it(monkeypatch):
    monkeypatch.setattr(boards, "programmer", lambda: None)
    with pytest.raises(boards.BoardError, match="STM32CubeProgrammer"):
        boards.probes()


def test_a_serial_port_is_named_like_one(monkeypatch):
    with pytest.raises(boards.BoardError, match="serial port's name"):
        boards.listen("COM6; del *.*")


# -- STM32CubeMX ---------------------------------------------------------------------------------


IOC = """#MicroXplorer Configuration settings - do not modify
Mcu.UserName=STM32G474RETx
Mcu.IP0=NVIC
Mcu.IP1=RCC
Mcu.IP2=SPI1
Mcu.IP3=SYS
PA5.Signal=SPI1_SCK
PA5.GPIO_Label=LCD_CLK
PB6.Signal=GPIO_Output
PB6.GPIO_Label=LCD_CS
PB6.PinState=GPIO_PIN_RESET
SPI1.FirstBit=SPI_FIRSTBIT_LSB
SPI1.BaudRatePrescaler=SPI_BAUDRATEPRESCALER_128
SPI1.IPParameters=FirstBit,BaudRatePrescaler
RCC.SYSCLKFreq_VALUE=170000000
ProjectManager.TargetToolchain=CMake
VP_SYS_VS_Systick.Signal=SYS_VS_Systick
"""


def test_a_cubemx_setup_is_said_in_a_few_lines(tmp_path):
    (tmp_path / "Display.ioc").write_text(IOC)
    said = cubemx.summary(cubemx.project_file(tmp_path))
    assert said.startswith("The person's STM32CubeMX project, Display.ioc: STM32G474RETx, "
                           "system clock 170 MHz, built with CMake.")
    assert "PA5 SPI1_SCK (LCD_CLK); PB6 GPIO_Output (LCD_CS), starts reset" in said
    assert "SPI1: FirstBit SPI_FIRSTBIT_LSB, BaudRatePrescaler SPI_BAUDRATEPRESCALER_128." in said
    assert "VP_" not in said and "IPParameters" not in said


def test_code_is_generated_with_cubemx_s_own_java_and_a_script(monkeypatch, tmp_path):
    (tmp_path / "Display.ioc").write_text(IOC)
    home = tmp_path / "STM32CubeMX"
    (home / "jre" / "bin").mkdir(parents=True)
    (home / "jre" / "bin" / "java.exe").write_text("")
    (home / "STM32CubeMX.exe").write_text("")
    monkeypatch.setattr(cubemx, "installed", lambda: home)
    seen = {}

    def run(argv, **options):
        seen["argv"] = argv
        seen["script"] = Path(argv[-1]).read_text(encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="OK\nOK\nBye\n", stderr="")

    monkeypatch.setattr(cubemx.subprocess, "run", run)
    said = cubemx.generate(tmp_path)
    assert said.startswith("Generated the code of Display.ioc again")
    assert seen["argv"][-2] == "-q" and str(home / "STM32CubeMX.exe") in seen["argv"]
    assert seen["script"] == f'config load "{tmp_path / "Display.ioc"}"\nproject generate\nexit\n'


def test_a_folder_without_an_ioc_is_not_generated(tmp_path):
    with pytest.raises(cubemx.CubeMXError, match="not an STM32CubeMX project"):
        cubemx.generate(tmp_path)


# -- the tools -----------------------------------------------------------------------------------


class Confirm:
    def __init__(self, answer=True):
        self.answer, self.asked = answer, []

    def __call__(self, summary):
        self.asked.append(str(summary))
        return self.answer


def context(tmp_path, *grants, confirm=None, workspace=""):
    policy = Policy()
    for capability in grants:
        scoped = capability in ("files.read", "files.write", "shell.run")
        policy.grant(capability, (str(tmp_path),) if scoped else ())
    return ToolContext(policy=policy, audit=AuditLog(tmp_path / "audit.jsonl"),
                       secrets=SecretStore(tmp_path / "secrets"),
                       confirm=confirm or Confirm(), attended=True, workspace=workspace)


def project(tmp_path):
    (tmp_path / "Display.ioc").write_text(IOC)
    include = tmp_path / "Drivers" / "CMSIS" / "Device" / "ST" / "STM32G4xx" / "Include"
    include.mkdir(parents=True)
    (include / "stm32g474xx.h").write_text(HEADER)
    return tmp_path


def test_a_register_is_read_and_explained_through_the_tool(tmp_path, monkeypatch):
    project(tmp_path)
    monkeypatch.setattr(boards, "read_words", lambda address, count=1: [0xBC])
    result = default_registry().invoke(
        "read_register", {"register": "SPI1.CR1"},
        context(tmp_path, "device.read", "files.read", workspace=str(tmp_path)))
    assert result.ok, result.content
    assert "SPI1.CR1 (0x40013000) = 0x000000BC" in result.content
    assert "LSBFIRST = 1" in result.content


def test_boards_are_not_read_without_the_permission(tmp_path):
    result = default_registry().invoke("read_register", {"register": "SPI1.CR1"},
                                       context(tmp_path, "files.read"))
    assert not result.ok and "Not permitted" in result.content


def test_flashing_asks_every_time_and_says_what_is_replaced(tmp_path, monkeypatch):
    (tmp_path / "build" / "Debug").mkdir(parents=True)
    image = tmp_path / "build" / "Debug" / "Display.elf"
    image.write_bytes(b"\x7fELF" + b"\0" * 4096)
    flashed = []
    monkeypatch.setattr(boards, "flash", lambda path: flashed.append(path) or "Download verified")
    confirm = Confirm()
    ctx = context(tmp_path, "device.write", "files.read", confirm=confirm)
    for _ in range(2):
        result = default_registry().invoke("flash_firmware", {"path": str(tmp_path)}, ctx)
        assert result.ok, result.content
    assert flashed == [image, image]
    assert len(confirm.asked) == 2, "asked each time, not once for the run"
    assert "The program on the board now is replaced" in confirm.asked[0]
    declined = context(tmp_path, "device.write", "files.read", confirm=Confirm(False))
    assert not default_registry().invoke("flash_firmware", {"path": str(image)}, declined).ok
    assert len(flashed) == 2


def test_the_program_written_is_the_one_the_person_was_shown(tmp_path, monkeypatch):
    (tmp_path / "build" / "Debug").mkdir(parents=True)
    shown = tmp_path / "build" / "Debug" / "Display.elf"
    shown.write_bytes(b"\x7fELF" + b"\0" * 4096)
    flashed = []
    monkeypatch.setattr(boards, "flash", lambda path: flashed.append(path) or "Download verified")

    class BuildFinishes(Confirm):
        # While the person reads the question, a build writes a newer program.
        def __call__(self, summary):
            newer = tmp_path / "build" / "Release.elf"
            newer.write_bytes(b"\x7fELF" + b"\1" * 8192)
            later = time.time() + 60
            os.utime(newer, (later, later))
            return super().__call__(summary)

    ctx = context(tmp_path, "device.write", "files.read", confirm=BuildFinishes())
    result = default_registry().invoke("flash_firmware", {"path": str(tmp_path)}, ctx)
    assert result.ok and flashed == [shown], "not the build the person said yes to"

    class Rebuilt(Confirm):
        # The very file shown is written again before the answer.
        def __call__(self, summary):
            shown.write_bytes(b"\x7fELF" + b"\2" * 2048)
            return super().__call__(summary)

    ctx = context(tmp_path, "device.write", "files.read", confirm=Rebuilt())
    result = default_registry().invoke("flash_firmware", {"path": str(shown)}, ctx)
    assert not result.ok and "changed after the person was asked" in result.content
    assert flashed == [shown]


def test_pins_are_looked_up_through_the_tool(tmp_path):
    result = default_registry().invoke(
        "stm32_pins", {"folder": str(tmp_path), "board": "NUCLEO-G474RE", "pins": "D13 D11"},
        context(tmp_path, "files.read"))
    assert result.ok and "D11 is PA7, D13 is PA5" in result.content


def test_vendor_names_are_found_in_the_package(tmp_path):
    project(tmp_path)
    (tmp_path / "Drivers" / "STM32G4xx_HAL_Driver" / "Inc").mkdir(parents=True)
    (tmp_path / "Drivers" / "STM32G4xx_HAL_Driver" / "Inc" / "stm32g4xx_hal_spi.h").write_text(
        "#define SPI_FIRSTBIT_MSB (0x00000000U)\n#define SPI_FIRSTBIT_LSB SPI_CR1_LSBFIRST\n"
        "HAL_StatusTypeDef HAL_SPI_Transmit(SPI_HandleTypeDef *hspi, const uint8_t *pData, "
        "uint16_t Size, uint32_t Timeout);\n")
    result = default_registry().invoke(
        "find_vendor_names", {"folder": str(tmp_path), "words": "spi firstbit",
                              "chip": "STM32G474RE"}, context(tmp_path, "files.read"))
    assert result.ok and "SPI_FIRSTBIT_LSB" in result.content and "SPI_FIRSTBIT_MSB" in result.content
    transmit = default_registry().invoke(
        "find_vendor_names", {"folder": str(tmp_path), "words": "HAL_SPI_Transmit",
                              "chip": "STM32G474RE"}, context(tmp_path, "files.read"))
    assert "const uint8_t *pData" in transmit.content


def test_the_chat_judges_the_persons_cubemx_setup(tmp_path):
    from akira.core.brain.grounding import Grounder, HeaderIndex

    project(tmp_path)
    grounder = Grounder(lambda: [], lambda path: True,
                        index=HeaderIndex(tmp_path / "headers.json"),
                        projects=lambda: [tmp_path])
    found = grounder("Is my CubeMX setup right for an SPI display?")
    assert found.subject is not None and found.subject.family == "stm32g4"
    assert "The person's STM32CubeMX project, Display.ioc" in found.reference
    assert "judge it against what the person wants to do" in found.reference
    unread = Grounder(lambda: [], lambda path: path.suffix != ".ioc",
                      index=HeaderIndex(tmp_path / "h2.json"), projects=lambda: [tmp_path])
    assert unread("Is my CubeMX setup right?").subject is None, "only what may be read"
