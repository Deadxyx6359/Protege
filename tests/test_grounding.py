"""Answering about a chip from its own library files, and saying when it could not."""

from __future__ import annotations

from pathlib import Path

import pytest

from akira.core.brain.grounding import (Grounder, HeaderIndex, subject_of, symbols_in, teaching,
                                        topics_of)

#: Enough of ST's STM32G4 HAL, in its own layout and style, to check an answer against.
G4 = {
    "Drivers/STM32G4xx_HAL_Driver/Inc/stm32g4xx_hal_adc.h": """
/** @defgroup ADC_sampling_times ADC group regular sampling time */
#define ADC_SAMPLETIME_2CYCLES_5    (LL_ADC_SAMPLINGTIME_2CYCLES_5)
#define ADC_SAMPLETIME_6CYCLES_5    (LL_ADC_SAMPLINGTIME_6CYCLES_5)
#define ADC_SAMPLETIME_247CYCLES_5  (LL_ADC_SAMPLINGTIME_247CYCLES_5)
#define ADC_SAMPLETIME_640CYCLES_5  (LL_ADC_SAMPLINGTIME_640CYCLES_5)
#define ADC_REGULAR_RANK_1          (LL_ADC_REG_RANK_1)
#define ADC_CHANNEL_0               (LL_ADC_CHANNEL_0)
#define ADC_CHANNEL_1               (LL_ADC_CHANNEL_1)
#define ADC_SINGLE_ENDED            (LL_ADC_SINGLE_ENDED)
#define ADC_CLOCK_SYNC_PCLK_DIV2    (LL_ADC_CLOCK_SYNC_PCLK_DIV2)
#define ADC_RESOLUTION_12B          (LL_ADC_RESOLUTION_12B)
#define ADC_SCAN_DISABLE            (0x00000000UL)
#define ADC_EXTERNALTRIGCONVEDGE_NONE (0x00000000UL)
#define ADC_SOFTWARE_START          (0x00000001UL)
#define ADC_DATAALIGN_RIGHT         (LL_ADC_DATA_ALIGN_RIGHT)
#define ADC_EOC_SINGLE_CONV         (ADC_ISR_EOC)
typedef struct
{
  uint32_t ClockPrescaler;
  uint32_t Resolution;
} ADC_InitTypeDef;
typedef struct
{
  uint32_t Channel;
  uint32_t Rank;
  uint32_t SamplingTime;
} ADC_ChannelConfTypeDef;
typedef struct __ADC_HandleTypeDef
{
  ADC_TypeDef *Instance;
  ADC_InitTypeDef Init;
} ADC_HandleTypeDef;
HAL_StatusTypeDef       HAL_ADC_Init(ADC_HandleTypeDef *hadc);
HAL_StatusTypeDef       HAL_ADC_Start(ADC_HandleTypeDef *hadc);
HAL_StatusTypeDef       HAL_ADC_Stop(ADC_HandleTypeDef *hadc);
HAL_StatusTypeDef       HAL_ADC_PollForConversion(ADC_HandleTypeDef *hadc, uint32_t Timeout);
uint32_t                HAL_ADC_GetValue(const ADC_HandleTypeDef *hadc);
HAL_StatusTypeDef       HAL_ADC_ConfigChannel(ADC_HandleTypeDef *hadc, const ADC_ChannelConfTypeDef *pConfig);
""",
    "Drivers/STM32G4xx_HAL_Driver/Inc/stm32g4xx_hal_adc_ex.h": """
HAL_StatusTypeDef       HAL_ADCEx_Calibration_Start(ADC_HandleTypeDef *hadc, uint32_t SingleDiff);
""",
    "Drivers/STM32G4xx_HAL_Driver/Inc/stm32g4xx_hal_rcc.h": """
#define __HAL_RCC_ADC12_CLK_ENABLE()   do { __IO uint32_t tmpreg; } while(0)
#define __HAL_RCC_GPIOA_CLK_ENABLE()   do { __IO uint32_t tmpreg; } while(0)
""",
    "Drivers/STM32G4xx_HAL_Driver/Inc/stm32g4xx_hal_gpio.h": """
typedef struct
{
  uint32_t Pin;
  uint32_t Mode;
} GPIO_InitTypeDef;
#define GPIO_PIN_0                 ((uint16_t)0x0001)
#define GPIO_MODE_ANALOG           MODE_ANALOG
#define GPIO_NOPULL                (0x00000000U)
void              HAL_GPIO_Init(GPIO_TypeDef *GPIOx, const GPIO_InitTypeDef *GPIO_Init);
""",
    "Drivers/STM32G4xx_HAL_Driver/Inc/stm32g4xx_hal_def.h": """
typedef enum
{
  HAL_OK       = 0x00U,
  HAL_ERROR    = 0x01U,
} HAL_StatusTypeDef;
""",
    "Drivers/STM32G4xx_HAL_Driver/Inc/stm32g4xx_hal.h": """
HAL_StatusTypeDef HAL_Init(void);
void HAL_Delay(uint32_t Delay);
""",
    "Projects/NUCLEO-G474RE/Examples/ADC/Inc/main.h": """
#define ADC_SAMPLETIME_480CYCLES 99
""",
}

#: The answer Akira gave, as it gave it: STM32F4 names on a G4.
AKIRA = """Here is the program:

```c
#include "main.h"
#define ADCx_CLK_ENABLE() __HAL_RCC_ADC1_CLK_ENABLE()
ADC_HandleTypeDef hadc1;
static void MX_ADC1_Init(void);
int main(void)
{
  HAL_Init();
  MX_ADC1_Init();
  while (1)
  {
    uint32_t adc_value = HAL_ADC_GetValue(&hadc1);
    HAL_Delay(1000);
  }
}
static void MX_ADC1_Init(void)
{
  ADC_ChannelConfTypeDef sConfig = {0};
  hadc1.Init.ClockPrescaler = ADC_CLOCK_SYNC_PCLK_DIV2;
  hadc1.Init.Resolution = ADC_RESOLUTION_12B;
  if (HAL_ADC_Init(&hadc1) != HAL_OK) { Error_Handler(); }
  sConfig.Channel = ADC_CHANNEL_0;
  sConfig.SamplingTime = ADC_SAMPLETIME_480CYCLES;
  HAL_ADC_ConfigChannel(&hadc1, &sConfig);
  GPIO_InitTypeDef GPIO_InitStruct = {0};
  GPIO_InitStruct.Mode = GPIO_MODE_ANALOG;
}
```
"""

QUESTION = ("I have a ST NucleoG474RE, and I want to use an analog pin to see if it can read mV. "
            "Don't write the program for me, teach me how to go about making this program.")


@pytest.fixture
def sdk(tmp_path):
    root = tmp_path / "STM32Cube_FW_G4"
    for rel, text in G4.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def grounder(folders, tmp_path):
    return Grounder(lambda: list(folders), lambda path: True,
                    HeaderIndex(tmp_path / "headers.json"))


@pytest.mark.parametrize("text, name, family", [
    ("I have a ST NucleoG474RE", "STM32G474RE", "stm32g4"),
    ("using an STM32F411 blackpill", "STM32F411", "stm32f4"),
    ("my Nucleo-L476RG board", "STM32L476RG", "stm32l4"),
    ("an ESP32-S3 devkit", "ESP32-S3", "esp32"),
    ("Raspberry Pi Pico", "Raspberry Pi Pico", "pico"),
])
def test_the_chip_a_question_names(text, name, family):
    subject = subject_of(text)
    assert (subject.name, subject.family) == (name, family)


def test_no_chip_is_no_subject():
    assert subject_of("How do I sort a list in Python?") is None


def test_the_peripheral_a_question_needs():
    assert topics_of(QUESTION) == ("adc", "gpio")
    assert "uart" in topics_of("print it with printf over serial")


def test_header_names_are_read_as_declared():
    names = symbols_in(G4["Drivers/STM32G4xx_HAL_Driver/Inc/stm32g4xx_hal_adc.h"])
    assert {"ADC_SAMPLETIME_247CYCLES_5", "ADC_REGULAR_RANK_1", "ADC_HandleTypeDef",
            "ADC_ChannelConfTypeDef", "HAL_ADC_GetValue", "HAL_ADC_PollForConversion"} <= names
    assert "ADC_SAMPLETIME_480CYCLES" not in names


def test_the_f4_names_in_akiras_answer_are_caught(sdk, tmp_path):
    grounding = grounder([sdk], tmp_path)(QUESTION)
    assert grounding.documented and grounding.banner == ""
    note = grounding.check(AKIRA)
    assert "ADC_SAMPLETIME_480CYCLES" in note and "ADC_SAMPLETIME_640CYCLES_5" in note
    assert "__HAL_RCC_ADC1_CLK_ENABLE" in note and "__HAL_RCC_ADC12_CLK_ENABLE" in note
    # The person's own names, and names the library has, are not flagged.
    for fine in ("ADCx_CLK_ENABLE", "MX_ADC1_Init", "adc_value", "HAL_ADC_GetValue",
                 "ADC_CLOCK_SYNC_PCLK_DIV2", "Error_Handler", "GPIO_InitTypeDef"):
        assert f"`{fine}`" not in note
    assert note.startswith("\n\nCheck before using: 2 of the")


def test_an_example_projects_headers_are_not_the_library(sdk, tmp_path):
    # Projects/ held a main.h defining the F4 name; it must not make it look right.
    assert "ADC_SAMPLETIME_480CYCLES" in grounder([sdk], tmp_path)(QUESTION).check(AKIRA)


def test_names_that_are_all_there_are_said_to_be_checked(sdk, tmp_path):
    good = ("```c\nHAL_ADCEx_Calibration_Start(&hadc1, ADC_SINGLE_ENDED);\n"
            "HAL_ADC_Start(&hadc1);\nHAL_ADC_PollForConversion(&hadc1, 10);\n```")
    note = grounder([sdk], tmp_path)(QUESTION).check(good)
    assert note.startswith("\n\nChecked: the 4 STM32G474RE library names")
    assert "compare them with the datasheet" in note


def test_the_model_is_given_the_real_names_before_it_answers(sdk, tmp_path):
    reference = grounder([sdk], tmp_path)(QUESTION).reference
    assert "ADC_SAMPLETIME_640CYCLES_5" in reference and "ADC_REGULAR_RANK_1" in reference
    assert "HAL_ADC_PollForConversion" in reference and "HAL_ADCEx_Calibration_Start" in reference
    assert "__HAL_RCC_ADC12_CLK_ENABLE" in reference
    assert "ADC_SAMPLETIME_480CYCLES" not in reference
    assert "say so plainly instead of guessing" in reference


def test_with_nothing_to_check_against_it_says_so_first(tmp_path):
    grounding = grounder([], tmp_path)(QUESTION)
    assert not grounding.documented
    assert grounding.banner.startswith("**Not checked:** nothing on this computer documents "
                                       "the STM32G474RE")
    assert "unverified" in grounding.reference and grounding.check(AKIRA) == ""


def test_a_datasheet_passage_documents_it_without_headers(tmp_path):
    grounding = grounder([], tmp_path)(QUESTION, found="[DS12288.pdf] STM32G474xB/xC/xE: PA0 "
                                                       "ADC12_IN1")
    assert grounding.documented and grounding.banner == ""
    assert "passages from their documents" in grounding.reference


def test_another_familys_headers_do_not_count(sdk, tmp_path):
    grounding = grounder([sdk], tmp_path)("How do I read an analog pin on an STM32F411?")
    assert grounding.headers == [] and grounding.banner.startswith("**Not checked:**")


def test_the_headers_are_read_once_and_kept(sdk, tmp_path):
    index = HeaderIndex(tmp_path / "headers.json")
    first = index.headers([sdk], lambda path: True)
    assert (tmp_path / "headers.json").is_file()
    again = HeaderIndex(tmp_path / "headers.json").headers([sdk], lambda path: True)
    assert {h.path for h in first} == {h.path for h in again}


def test_headers_it_may_not_read_are_left_out(sdk, tmp_path):
    index = HeaderIndex(tmp_path / "headers.json")
    assert index.headers([sdk], lambda path: False) == []


@pytest.mark.parametrize("text, teach", [
    (QUESTION, True), ("Walk me through setting up a timer", True),
    ("How do I go about wiring this?", True), ("Write a function that reverses a list", False),
    ("Give me the code for blinking an LED", False),
])
def test_asking_to_be_taught(text, teach):
    assert teaching(text) is teach


def test_names_written_in_the_sentences_are_checked_too(sdk, tmp_path):
    taught = ("Set the sampling time with `ADC_SAMPLETIME_480CYCLES`, then call "
              "`HAL_ADC_Start()`.\n\n```c\nHAL_ADC_PollForConversion(&hadc1, 10);\n```")
    note = grounder([sdk], tmp_path)(QUESTION).check(taught)
    assert "`ADC_SAMPLETIME_480CYCLES`" in note and "1 of the 3" in note


def test_the_model_is_told_not_to_cite_pages_it_has_not_read(tmp_path):
    assert "Never cite a page" in grounder([], tmp_path)(QUESTION).reference


# -- registers, and names in sentences (checked against ST's own G4 package, 2026-09-30) ----------


def _g4():
    from akira.core.brain.grounding import Grounding, Header, Subject

    symbols = {"ADC_CR_ADEN", "ADC_CR_ADSTART", "ADC_CR_ADCAL", "ADC_SQR1_SQ1", "ADC_SQR4_SQ15",
               "ADC_DR_RDATA", "ADC_CFGR_CONT", "ADC12_COMMON_BASE", "RCC_AHB2ENR_ADC12EN",
               "HAL_ADC_Start"}
    return Grounding(subject=Subject("STM32G474RE", "stm32g4"), documented=True,
                     headers=[Header(Path("stm32g474xx.h"), symbols)])


def test_a_register_another_family_has_is_found_in_a_sentence():
    """ADC1->SQR5 and ADC_CR2_ADON are an STM32F1's, written in a sentence, and not checked."""
    note = _g4().check("Set the channel in ADC1->SQR1, start with ADC_CR_ADSTART and read "
                       "ADC1->DR. On older parts you would write ADC1->SQR5 and ADC_CR2_ADON.")
    assert note.startswith("\n\nCheck before using: 2 of the 5 STM32G474RE library names")
    assert "- `ADC1->SQR5` (the closest there: `ADC1->SQR4`, `ADC1->SQR1`)" in note
    assert "- `ADC_CR2_ADON` (the closest there: `ADC_CR_ADEN`" in note
    assert "`ADC1->DR`" not in note and "`ADC1->SQR1`" not in note.split("closest")[0]


def test_registers_the_headers_know_pass_and_a_peripheral_they_do_not_is_not_judged():
    note = _g4().check("```c\nADC1->CR |= ADC_CR_ADEN;\nADC1->CFGR |= ADC_CFGR_CONT;\n"
                       "GPIOA->MODER |= 3;\n```")
    assert note.startswith("\n\nChecked: the 4 STM32G474RE library names in this answer are all")
