// SPDX-License-Identifier: Apache-2.0
/* signal-bench firmware skeleton: ESP32-S3 wake-word target.
 *
 * T1.6 scope: compile-verified USB-serial protocol implementation with a
 * canned task stub. Phase 1 hardware bring-up replaces the stub with real
 * inference code.
 */

#include <inttypes.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#include "driver/gpio.h"
#include "esp_chip_info.h"
#include "esp_err.h"
#include "esp_flash.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "protocol.h"
#include "sdkconfig.h"
#include "task_stub.h"

#if CONFIG_BT_ENABLED
#include "esp_bt.h"
#endif

#if CONFIG_ESP_WIFI_ENABLED
#include "esp_wifi.h"
#endif

#ifndef SIGNAL_BENCH_VERSION
#define SIGNAL_BENCH_VERSION "unknown"
#endif

static const char *TAG = "signal-bench";

/* DevKitC-1 onboard LED is on GPIO 48 (RGB LED data pin).
 * Replace with a regular GPIO for boards with a discrete LED.
 */
#define LED_GPIO GPIO_NUM_48

static void log_chip_info(void)
{
    esp_chip_info_t chip_info;
    uint32_t flash_size_bytes = 0;
    esp_chip_info(&chip_info);
    esp_flash_get_size(NULL, &flash_size_bytes);

    ESP_LOGI(TAG, "signal-bench v%s - ESP32-S3 firmware skeleton", SIGNAL_BENCH_VERSION);
    ESP_LOGI(
        TAG,
        "chip: %d cores, rev %d, flash %" PRIu32 "MB",
        chip_info.cores,
        chip_info.revision,
        flash_size_bytes / (1024U * 1024U)
    );
    ESP_LOGI(TAG, "ready (T1.6 protocol scaffold; canned task stub only)");
}

static void warn_if_unexpected_error(const char *action, esp_err_t err)
{
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "%s failed: %s", action, esp_err_to_name(err));
    }
}

static void disable_radios(void)
{
#if CONFIG_BT_ENABLED
    esp_bt_controller_status_t bt_status = esp_bt_controller_get_status();
    if (bt_status == ESP_BT_CONTROLLER_STATUS_ENABLED) {
        warn_if_unexpected_error("esp_bt_controller_disable", esp_bt_controller_disable());
    }

    bt_status = esp_bt_controller_get_status();
    if (bt_status == ESP_BT_CONTROLLER_STATUS_INITED) {
        warn_if_unexpected_error("esp_bt_controller_deinit", esp_bt_controller_deinit());
    }
#else
    ESP_LOGI(TAG, "Bluetooth controller not enabled in sdkconfig");
#endif

#if CONFIG_ESP_WIFI_ENABLED
    esp_err_t err = esp_wifi_stop();
    if (err != ESP_OK && err != ESP_ERR_WIFI_NOT_INIT) {
        warn_if_unexpected_error("esp_wifi_stop", err);
    }

    err = esp_wifi_deinit();
    if (err != ESP_OK && err != ESP_ERR_WIFI_NOT_INIT) {
        warn_if_unexpected_error("esp_wifi_deinit", err);
    }
#else
    ESP_LOGI(TAG, "WiFi not enabled in sdkconfig");
#endif

    ESP_LOGI(TAG, "radio disable path completed");
}

static void init_ready_led(void)
{
    gpio_reset_pin(LED_GPIO);
    gpio_set_direction(LED_GPIO, GPIO_MODE_OUTPUT);
    gpio_set_level(LED_GPIO, 1);
}

static bool has_run_prefix(const char *line)
{
    while (*line == ' ' || *line == '\t') {
        line++;
    }

    return strncmp(line, "RUN", 3) == 0
        && (line[3] == ' ' || line[3] == '\t' || line[3] == '\n' || line[3] == '\0');
}

static void run_protocol_loop(void)
{
    char line[SB_PROTOCOL_MAX_LINE_LEN] = {0};
    char task_id[SB_PROTOCOL_MAX_TASK_ID_LEN] = {0};
    int iterations = 0;

    ESP_LOGI(TAG, "USB-serial protocol ready: RUN -> RESULT* -> DONE");

    while (fgets(line, sizeof(line), stdin) != NULL) {
        if (protocol_parse_run(line, task_id, sizeof(task_id), &iterations)) {
            task_stub_run(task_id, iterations);
            memset(task_id, 0, sizeof(task_id));
            iterations = 0;
            continue;
        }

        if (has_run_prefix(line)) {
            protocol_emit_err(ERR_EINVAL, "invalid RUN frame");
        } else {
            protocol_emit_err(ERR_EUNKNOWN, "expected RUN <task_id> <iterations>");
        }
    }

    protocol_emit_err(ERR_EINTERNAL, "serial input closed");
}

void app_main(void)
{
    log_chip_info();
    disable_radios();
    init_ready_led();
    run_protocol_loop();

    while (true) {
        vTaskDelay(portMAX_DELAY);
    }
}
