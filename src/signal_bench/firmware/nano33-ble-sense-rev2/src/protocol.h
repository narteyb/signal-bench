// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <stddef.h>

#define SB_PROTOCOL_MAX_LINE_LEN 160
#define SB_PROTOCOL_MAX_TASK_ID_LEN 64

#define ERR_EUNKNOWN "EUNKNOWN"
#define ERR_EINVAL "EINVAL"
#define ERR_EINFER "EINFER"
#define ERR_EINTERNAL "EINTERNAL"
#define ERR_ETIMEOUT "ETIMEOUT"
#define ERR_EHW "EHW"
#define ERR_ETEST "ETEST"

bool protocol_parse_run(
    const char *line,
    char *out_task_id,
    size_t task_id_len,
    int *out_iterations
);

void protocol_emit_result(int iter_id, int duration_us, const char *json_output);
void protocol_emit_done(int total_iterations);
void protocol_emit_err(const char *symbolic_code, const char *message);
