// SPDX-License-Identifier: Apache-2.0
#include "protocol.h"

#include <Arduino.h>
#include <stdio.h>
#include <string.h>

bool protocol_parse_run(
    const char *line,
    char *out_task_id,
    size_t task_id_len,
    int *out_iterations
)
{
    char task_id[SB_PROTOCOL_MAX_TASK_ID_LEN] = {0};
    char extra = '\0';
    int iterations = 0;

    if (line == NULL || out_task_id == NULL || out_iterations == NULL || task_id_len == 0U) {
        return false;
    }

    int parsed = sscanf(line, " RUN %63s %d %c", task_id, &iterations, &extra);
    if (parsed != 2 || iterations <= 0) {
        return false;
    }

    if (strlen(task_id) >= task_id_len) {
        return false;
    }

    strncpy(out_task_id, task_id, task_id_len);
    out_task_id[task_id_len - 1U] = '\0';
    *out_iterations = iterations;
    return true;
}

void protocol_emit_result(int iter_id, int duration_us, const char *json_output)
{
    Serial.print("RESULT ");
    Serial.print(iter_id);
    Serial.print(' ');
    Serial.print(duration_us);
    Serial.print(' ');
    Serial.println(json_output == NULL ? "null" : json_output);
    Serial.flush();
}

void protocol_emit_done(int total_iterations)
{
    Serial.print("DONE ");
    Serial.println(total_iterations);
    Serial.flush();
}

void protocol_emit_err(const char *symbolic_code, const char *message)
{
    Serial.print("ERR ");
    Serial.print(symbolic_code == NULL ? ERR_EINTERNAL : symbolic_code);
    Serial.print(' ');
    Serial.println(message == NULL ? "internal error" : message);
    Serial.flush();
}
