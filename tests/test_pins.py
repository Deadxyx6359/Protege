"""Which pin is which: a board's connector, what a chip's pins can be, and the
person's wiring checked against both.

STM32CubeMX's database is a stand-in here, a chip file and a board file in the
same shape as the real ones, so nothing depends on it being installed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from akira.core.brain import pins
from akira.core.brain.grounding import Grounder, HeaderIndex

CHIP = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<Mcu Family="STM32G4" RefName="STM32G474R(B-C-E)Tx" xmlns="http://mcd.rou.st.com/modules.php?name=mcu">
    <IP InstanceName="SPI1" Name="SPI"/>
    <IP InstanceName="SPI2" Name="SPI"/>
    <IP InstanceName="I2C1" Name="I2C"/>
    <Pin Name="PA4" Type="I/O"><Signal Name="SPI1_NSS"/><Signal Name="GPIO"/></Pin>
    <Pin Name="PA5" Type="I/O"><Signal Name="SPI1_SCK"/><Signal Name="TIM2_CH1"/><Signal Name="GPIO"/></Pin>
    <Pin Name="PA6" Type="I/O"><Signal Name="SPI1_MISO"/><Signal Name="GPIO"/></Pin>
    <Pin Name="PA7" Type="I/O"><Signal Name="SPI1_MOSI"/><Signal Name="GPIO"/></Pin>
    <Pin Name="PA10" Type="I/O"><Signal Name="USART1_RX"/><Signal Name="GPIO"/></Pin>
    <Pin Name="PA11" Type="I/O"><Signal Name="SPI2_MOSI"/><Signal Name="GPIO"/></Pin>
    <Pin Name="PA13" Type="I/O"><Signal Name="SYS_JTMS-SWDIO"/><Signal Name="GPIO"/></Pin>
    <Pin Name="PB3" Type="I/O"><Signal Name="SPI1_SCK"/><Signal Name="GPIO"/></Pin>
    <Pin Name="PB6" Type="I/O"><Signal Name="TIM4_CH1"/><Signal Name="GPIO"/></Pin>
    <Pin Name="PB8-BOOT0" Type="I/O"><Signal Name="I2C1_SCL"/><Signal Name="GPIO"/></Pin>
    <Pin Name="PB9" Type="I/O"><Signal Name="I2C1_SDA"/><Signal Name="GPIO"/></Pin>
    <Pin Name="PB13" Type="I/O"><Signal Name="SPI2_SCK"/><Signal Name="GPIO"/></Pin>
    <Pin Name="VDD" Type="Power"/>
</Mcu>
"""

BOARD_FILE = "PA13.GPIO_Label=T_SWDIO\nPB3.GPIO_Label=T_SWO\nPA2.GPIO_Label=LPUART1_TX\n"

WIRED = "display VIN to the Nucleo's 5V, GND to GND, CLK to D13, DI to D11, CS to D10."


@pytest.fixture
def database(tmp_path) -> Path:
    db = tmp_path / "STM32CubeMX" / "db"
    (db / "mcu").mkdir(parents=True)
    (db / "mcu" / "STM32G474R(B-C-E)Tx.xml").write_text(CHIP, encoding="utf-8")
    (db / "mcu" / "STM32G474V(B-C-E)Tx.xml").write_text(CHIP, encoding="utf-8")
    boards = db / "plugins" / "boardmanager" / "boards"
    boards.mkdir(parents=True)
    (boards / "M42_Nucleo_NUCLEO-G474RE_STM32G474RE_Board.ioc").write_text(BOARD_FILE)
    return db


@pytest.fixture
def chip(database):
    board = pins.board_of("nucleo g474re")
    return pins.chip_pins([database.parent], lambda path: True, board.part, board)


def test_a_board_is_known_by_how_people_write_it():
    for written in ("NUCLEO-G474RE", "nucleo g474re", "my Nucleo G474RE", "nucleo_g474re"):
        assert pins.board_of(written).part == "STM32G474RE", written
    assert pins.board_of("nucleo f401re") is None, "only boards whose map was checked"


def test_connector_names_are_the_boards_pins_not_pin_numbers():
    board = pins.board_of("nucleo g474re")
    assert pins.pins_named("CLK to D13, DI to D11, CS to D10, and an LED on PA9",
                           board) == ["PA5", "PA7", "PB6", "PA9"]
    assert pins.pins_named("LD2 and A2", board) == ["PA4"], "LD2 is not D2"


def test_the_chip_is_found_by_its_package_in_the_database(chip):
    assert chip.signals["PA5"] == ["SPI1_SCK", "TIM2_CH1"]
    assert "PB8" in chip.signals and "VDD" not in chip.signals
    assert chip.pins_for("SPI1_SCK") == ["PA5", "PB3"]
    assert {"SPI1", "SPI2", "I2C1"} <= chip.instances
    assert chip.board_uses["PB3"] == "T_SWO"


def test_a_part_without_its_package_is_not_guessed(database):
    # Pins are numbered per package: STM32G474 alone could be either file.
    assert pins.chip_pins([database], lambda path: True, "STM32G474") is None


def test_nothing_is_read_that_the_person_did_not_allow(database):
    assert pins.chip_pins([database], lambda path: False, "STM32G474RE") is None


def test_the_facts_say_what_each_named_pin_can_be(chip):
    board = pins.board_of("nucleo g474re")
    said = pins.facts(board, chip, pins.pins_named(WIRED, board), ("spi",))
    assert "D10 is PB6, D11 is PA7, D13 is PA5" in said
    assert "PA5: on this board it is also the green user LED, LD2" in said
    assert "it can be SPI1_SCK" in said
    assert "PB6: it has no SPI signal" in said
    assert "SPI1_SCK on PA5 or PB3" in said


def test_the_wiring_is_checked_and_the_verdict_said_outright(chip):
    board = pins.board_of("nucleo g474re")
    said = pins.wiring(WIRED, board, chip)
    assert "CLK on D13 (PA5): right, PA5 can be SPI1_SCK" in said
    assert "CS on D10 (PB6): a chip select is a plain GPIO output" in said
    assert said.endswith("The wiring works, on SPI1: tell the person so, and do not tell "
                         "them to change it.")


def test_wiring_on_a_pin_that_cannot_carry_the_signal_is_said_to_need_changing(chip):
    board = pins.board_of("nucleo g474re")
    said = pins.wiring("CLK to D2, DI to D11, CS to D10", board, chip)
    assert "PA10 cannot be any SCK signal; it would have to move to one of PA5, PB13, PB3" in said
    assert said.endswith("The wiring needs changing, as said above.")


def test_wires_on_different_peripherals_do_not_work_together(chip):
    said = pins.wiring("CLK to PB13, DI to PA7", pins.board_of("nucleo g474re"), chip)
    assert "different peripherals" in said


def test_an_answer_that_misreads_the_board_or_the_chip_is_caught(chip):
    board = pins.board_of("nucleo g474re")
    answer = ("- **Display CLK** to **Nucleo D13 (PA13)**\n"
              "- Assign PA10, PA11, PA13 to SPI2_NSS, SPI2_SCK, SPI2_MOSI respectively\n"
              "- CS to D10 (SPI1_NSS)\n"
              "- CLK to D13 (SPI1_SCK)\n"
              "- NSS (SPI1_NSS): not used, PB6 is the chip select instead")
    found = pins.check(answer, board, chip)
    assert "D13 is PA5 on the NUCLEO-G474RE, not PA13" in found
    assert any(f.startswith("SPI2_SCK cannot be on PA10, PA11, PA13") for f in found)
    assert not any(f.startswith("SPI2_MOSI") for f in found), "PA11 can be SPI2_MOSI"
    assert any(f.startswith("SPI1_NSS cannot be on PB6") for f in found)
    assert len([f for f in found if f.startswith("SPI1_NSS")]) == 1, \
        "a line saying it is not used pairs nothing"


def test_grounding_gives_the_pins_and_checks_them(database, tmp_path):
    grounder = Grounder(lambda: [database], lambda path: True,
                        index=HeaderIndex(tmp_path / "headers.json"))
    found = grounder("My nucleo g474re: " + WIRED + " How do I set up the SPI?")
    assert found.documented, "the database documents the chip's pins"
    assert "The wiring works, on SPI1" in found.reference
    assert "D13 is PA5" in found.reference
    note = found.check("Connect CLK to D13 (PA13).")
    assert "Check the pins: D13 is PA5 on the NUCLEO-G474RE, not PA13" in note


def test_names_stm32cubemx_writes_are_real_without_a_header(database, tmp_path):
    header = tmp_path / "stm32g4xx_hal_spi.h"
    header.write_text("#define SPI_FIRSTBIT_LSB (0x1U)\nHAL_StatusTypeDef "
                      "HAL_SPI_Transmit(SPI_HandleTypeDef *h, uint8_t *d, uint16_t n, "
                      "uint32_t t);\n", encoding="utf-8")
    grounder = Grounder(lambda: [database, tmp_path], lambda path: True,
                        index=HeaderIndex(tmp_path / "headers.json"))
    found = grounder("SPI on my nucleo g474re")
    note = found.check("Call `MX_SPI1_Init()` and `MX_GPIO_Init()`, set PA5 to `SPI1_SCK` "
                       "and PB6 to `GPIO_Output`, then `HAL_SPI_Transmit(&hspi1, ...)` with "
                       "`SPI_FIRSTBIT_LSB`, but not `SPI_FIRSTBIT_LSBX`.")
    assert "`SPI_FIRSTBIT_LSBX`" in note
    for real in ("MX_SPI1_Init", "MX_GPIO_Init", "SPI1_SCK", "GPIO_Output", "hspi1"):
        assert f"`{real}`" not in note, real
