"""What an agent is told about an STM32CubeMX project it works in, from the project's
own files."""

from __future__ import annotations

from akira.core.agents.workspaces import notes

MAIN_C = """#include "main.h"
/* USER CODE BEGIN Includes */
/* USER CODE END Includes */
SPI_HandleTypeDef hspi1;
UART_HandleTypeDef hlpuart1;
/* USER CODE BEGIN PD */
/* USER CODE END PD */
int main(void)
{
  MX_SPI1_Init();
  /* USER CODE BEGIN 2 */
  /* USER CODE END 2 */
}
static void MX_SPI1_Init(void)
{
  hspi1.Instance = SPI1;
  hspi1.Init.Mode = SPI_MODE_MASTER;
  hspi1.Init.FirstBit = SPI_FIRSTBIT_LSB;
}
static void MX_GPIO_Init(void)
{
  GPIO_InitStruct.Pin = LCD_CS_Pin;
}
"""

MAIN_H = """#define LCD_CS_Pin GPIO_PIN_6
#define LCD_CS_GPIO_Port GPIOB
#define T_SWO_Pin GPIO_PIN_3
#define T_SWO_GPIO_Port GPIOB
"""

CMAKE = "target_sources(${CMAKE_PROJECT_NAME} PRIVATE\n    # Add user sources here\n)\n"


def project(tmp_path):
    (tmp_path / "Core" / "Src").mkdir(parents=True)
    (tmp_path / "Core" / "Inc").mkdir(parents=True)
    (tmp_path / "Display.ioc").write_text("SPI1.Mode=SPI_MODE_MASTER\n")
    (tmp_path / "Core" / "Src" / "main.c").write_text(MAIN_C)
    (tmp_path / "Core" / "Inc" / "main.h").write_text(MAIN_H)
    (tmp_path / "CMakeLists.txt").write_text(CMAKE)
    return tmp_path


def test_an_agent_is_told_how_a_cubemx_project_is_laid_out(tmp_path):
    said = notes(str(project(tmp_path)), lambda path: True)
    assert "STM32CubeMX project (Display.ioc)" in said
    assert f"main.c is {tmp_path / 'Core' / 'Src' / 'main.c'}" in said
    assert "USER CODE blocks: Includes, PD, 2" in said
    assert "SPI_HandleTypeDef hspi1; UART_HandleTypeDef hlpuart1;" in said
    assert "never define it again" in said
    assert "MX_SPI1_Init sets: Mode = SPI_MODE_MASTER, FirstBit = SPI_FIRSTBIT_LSB" in said
    assert "LCD_CS_Pin (GPIO_PIN_6) on LCD_CS_GPIO_Port (GPIOB)" in said
    assert "T_SWO" not in said, "the debugger's pin is not one to use"
    assert "under the line `# Add user sources here`" in said


def test_only_files_the_person_allowed_are_read(tmp_path):
    folder = project(tmp_path)
    said = notes(str(folder), lambda path: path.name != "main.c")
    assert "STM32CubeMX project" in said
    assert "hspi1" not in said and "MX_SPI1_Init" not in said
    assert "LCD_CS_Pin" in said


def test_any_other_folder_gets_nothing(tmp_path):
    (tmp_path / "main.c").write_text(MAIN_C)
    assert notes(str(tmp_path), lambda path: True) == ""
    assert notes("", lambda path: True) == ""
