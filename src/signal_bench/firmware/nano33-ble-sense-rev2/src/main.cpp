// SPDX-License-Identifier: Apache-2.0
/* signal-bench firmware skeleton: Nano 33 BLE Sense Rev2 wake-word target.
 *
 * T1.7 scope: compile-verified USB-serial protocol implementation with a
 * canned task stub. Phase 1 hardware bring-up replaces the stub with real
 * inference code.
 */

#include <Arduino.h>
#include <string.h>

#include "protocol.h"
#include "task_stub.h"

static bool has_run_prefix(const char *line)
{
    while (*line == ' ' || *line == '\t') {
        line++;
    }

    return strncmp(line, "RUN", 3) == 0
        && (line[3] == ' ' || line[3] == '\t' || line[3] == '\n' || line[3] == '\0');
}

static void handle_line(const char *line)
{
    char task_id[SB_PROTOCOL_MAX_TASK_ID_LEN] = {0};
    int iterations = 0;

    if (protocol_parse_run(line, task_id, sizeof(task_id), &iterations)) {
        task_stub_run(task_id, iterations);
        return;
    }

    if (has_run_prefix(line)) {
        protocol_emit_err(ERR_EINVAL, "invalid RUN frame");
    } else {
        protocol_emit_err(ERR_EUNKNOWN, "expected RUN <task_id> <iterations>");
    }
}

void setup()
{
    Serial.begin(115200);
    while (!Serial) {
        delay(10);
    }
    Serial.setTimeout(1000);

    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, HIGH);

    /* Radio invariant: this scaffold never initializes the BLE stack, so the
     * nRF52840 radio remains idle. Nano 33 BLE Sense Rev2 has no WiFi.
     * Sensors are deliberately left uninitialized until a real TinyML task
     * needs them during Phase 1+ hardware bring-up.
     */
}

void loop()
{
    if (!Serial.available()) {
        delay(1);
        return;
    }

    String line = Serial.readStringUntil('\n');
    handle_line(line.c_str());
}
