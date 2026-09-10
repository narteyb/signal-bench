// SPDX-License-Identifier: Apache-2.0
#include "task_stub.h"

#include <Arduino.h>

#include "protocol.h"

#define STUB_DURATION_US 1200
#define STUB_JSON_OUTPUT "[0.42,0.31,0.27]"

void task_stub_run(const char *task_id, int iterations)
{
    (void)task_id;

    for (int iter_id = 0; iter_id < iterations; iter_id++) {
        protocol_emit_result(iter_id, STUB_DURATION_US, STUB_JSON_OUTPUT);
        delay(1);
    }

    protocol_emit_done(iterations);
}
