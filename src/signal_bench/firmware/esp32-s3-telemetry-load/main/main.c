// SPDX-License-Identifier: Apache-2.0
#include <inttypes.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

#include "driver/gpio.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define IDLE_SECONDS 10
#define LOAD_SECONDS 15
#define RELEASE_SECONDS 10
#define LOAD_TASK_STACK_WORDS 4096
#define LOAD_TASK_PRIORITY 1
#define LOAD_TASK_COUNT 2
#define STATUS_GPIO GPIO_NUM_2

static volatile bool g_load_enabled = false;
static volatile uint32_t g_sink = 0;

static void delay_seconds(uint32_t seconds)
{
    vTaskDelay(pdMS_TO_TICKS(seconds * 1000U));
}

static void set_status_gpio(bool on)
{
    gpio_set_level(STATUS_GPIO, on ? 1 : 0);
}

static void configure_status_gpio(void)
{
    gpio_config_t config = {
        .pin_bit_mask = 1ULL << STATUS_GPIO,
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config(&config);
    set_status_gpio(false);
}

static void load_worker(void *arg)
{
    uintptr_t salt = (uintptr_t)arg + 0x9e3779b9U;
    uint32_t x = 0x1234567U ^ (uint32_t)salt;

    while (true) {
        if (!g_load_enabled) {
            vTaskDelay(pdMS_TO_TICKS(20));
            continue;
        }

        int64_t stop_at_us = esp_timer_get_time() + 5000;
        while (g_load_enabled && esp_timer_get_time() < stop_at_us) {
            x ^= x << 13;
            x ^= x >> 17;
            x ^= x << 5;
            x += 0x6d2b79f5U + (uint32_t)salt;
            g_sink ^= x;
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}

static void start_load_tasks(void)
{
    for (uintptr_t i = 0; i < LOAD_TASK_COUNT; ++i) {
        char name[16];
        snprintf(name, sizeof(name), "load%u", (unsigned)i);
        xTaskCreate(
            load_worker,
            name,
            LOAD_TASK_STACK_WORDS,
            (void *)i,
            LOAD_TASK_PRIORITY,
            NULL
        );
    }
}

void app_main(void)
{
    configure_status_gpio();
    start_load_tasks();
    printf("signal-bench esp32-s3 telemetry-load ready version=%s\n", SIGNAL_BENCH_VERSION);

    uint32_t cycle = 1;
    while (true) {
        g_load_enabled = false;
        set_status_gpio(false);
        printf("cycle=%" PRIu32 " phase=idle seconds=%u\n", cycle, IDLE_SECONDS);
        delay_seconds(IDLE_SECONDS);

        g_load_enabled = true;
        set_status_gpio(true);
        printf("cycle=%" PRIu32 " phase=load seconds=%u\n", cycle, LOAD_SECONDS);
        delay_seconds(LOAD_SECONDS);

        g_load_enabled = false;
        set_status_gpio(false);
        printf("cycle=%" PRIu32 " phase=release seconds=%u sink=%" PRIu32 "\n",
               cycle,
               RELEASE_SECONDS,
               g_sink);
        delay_seconds(RELEASE_SECONDS);
        ++cycle;
    }
}
