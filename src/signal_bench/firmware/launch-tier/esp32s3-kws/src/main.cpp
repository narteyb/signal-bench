
#include <Arduino.h>
#include <Chirale_TensorFlowLite.h>
#include <tensorflow/lite/micro/micro_interpreter.h>
#include <tensorflow/lite/micro/micro_mutable_op_resolver.h>
#include <tensorflow/lite/schema/schema_generated.h>

#include <stdlib.h>

#include "input_data.h"
#include "model_data.h"

#ifndef SIGNAL_BENCH_VERSION
#define SIGNAL_BENCH_VERSION "unknown"
#endif

#ifdef SIGNAL_BENCH_USE_USART1_PA9_PA10
static HardwareSerial BenchSerial(PA10, PA9);
#define SIGNAL_BENCH_SERIAL BenchSerial
#else
#define SIGNAL_BENCH_SERIAL Serial
#endif

alignas(16) static uint8_t tensor_arena[kTensorArenaBytes];
alignas(16) static int8_t eval_input_buffer[kInputElements];
static tflite::MicroMutableOpResolver<8> resolver;
static const tflite::Model *model = nullptr;
static tflite::MicroInterpreter *interpreter = nullptr;
static TfLiteTensor *input_tensor = nullptr;
static TfLiteTensor *output_tensor = nullptr;
static bool init_ok = false;
static const char *init_error = "not initialized";

static bool parse_run(const char *line, char *task_id, size_t task_id_len, int *iterations) {
  while (*line == ' ' || *line == '\t') {
    line++;
  }
  if (strncmp(line, "RUN", 3) != 0 || (line[3] != ' ' && line[3] != '\t')) {
    return false;
  }
  char parsed_task[24] = {0};
  int parsed_iterations = 0;
  if (sscanf(line + 3, "%23s %d", parsed_task, &parsed_iterations) != 2) {
    return false;
  }
  if (parsed_iterations <= 0) {
    return false;
  }
  strncpy(task_id, parsed_task, task_id_len - 1);
  *iterations = parsed_iterations;
  return true;
}

static bool parse_eval(
    const char *line,
    char *task_id,
    size_t task_id_len,
    int *sample_index,
    const char **payload) {
  while (*line == ' ' || *line == '\t') {
    line++;
  }
  if (strncmp(line, "EVAL", 4) != 0 || (line[4] != ' ' && line[4] != '\t')) {
    return false;
  }
  const char *cursor = line + 4;
  while (*cursor == ' ' || *cursor == '\t') {
    cursor++;
  }
  size_t task_len = 0;
  while (cursor[task_len] != '\0' && cursor[task_len] != ' ' && cursor[task_len] != '\t') {
    task_len++;
  }
  if (task_len == 0 || task_len >= task_id_len) {
    return false;
  }
  memcpy(task_id, cursor, task_len);
  task_id[task_len] = '\0';
  cursor += task_len;
  while (*cursor == ' ' || *cursor == '\t') {
    cursor++;
  }
  char *endptr = nullptr;
  long parsed_index = strtol(cursor, &endptr, 10);
  if (endptr == cursor || parsed_index < 0) {
    return false;
  }
  cursor = endptr;
  while (*cursor == ' ' || *cursor == '\t') {
    cursor++;
  }
  if (*cursor == '\0') {
    return false;
  }
  *sample_index = static_cast<int>(parsed_index);
  *payload = cursor;
  return true;
}

static int base64_value(char value) {
  if (value >= 'A' && value <= 'Z') {
    return value - 'A';
  }
  if (value >= 'a' && value <= 'z') {
    return value - 'a' + 26;
  }
  if (value >= '0' && value <= '9') {
    return value - '0' + 52;
  }
  if (value == '+') {
    return 62;
  }
  if (value == '/') {
    return 63;
  }
  return -1;
}

static int decode_base64_int8(const char *payload, int8_t *output, int output_capacity) {
  int accumulator = 0;
  int bits = -8;
  int output_len = 0;
  for (const char *cursor = payload; *cursor != '\0'; cursor++) {
    const char ch = *cursor;
    if (ch == '\r' || ch == '\n' || ch == ' ' || ch == '\t') {
      break;
    }
    if (ch == '=') {
      break;
    }
    const int decoded = base64_value(ch);
    if (decoded < 0) {
      return -1;
    }
    accumulator = (accumulator << 6) | decoded;
    bits += 6;
    if (bits >= 0) {
      if (output_len >= output_capacity) {
        return -1;
      }
      output[output_len++] = static_cast<int8_t>((accumulator >> bits) & 0xff);
      bits -= 8;
    }
  }
  return output_len;
}

static void emit_err(const char *code, const char *message) {
  SIGNAL_BENCH_SERIAL.print("ERR ");
  SIGNAL_BENCH_SERIAL.print(code);
  SIGNAL_BENCH_SERIAL.print(" ");
  SIGNAL_BENCH_SERIAL.println(message);
}

static void emit_done(int iterations) {
  SIGNAL_BENCH_SERIAL.print("DONE ");
  SIGNAL_BENCH_SERIAL.println(iterations);
}

static int argmax_int8(const int8_t *values, int count) {
  int best_index = 0;
  int8_t best_value = values[0];
  for (int i = 1; i < count; i++) {
    if (values[i] > best_value) {
      best_value = values[i];
      best_index = i;
    }
  }
  return best_index;
}

static float ad_mse(const int8_t *input_values, const int8_t *output_values) {
  float total = 0.0f;
  for (int i = 0; i < kOutputElements; i++) {
    const float in_value = (static_cast<int>(input_values[i]) - kInputZeroPoint) * kInputScale;
    const float out_value = (static_cast<int>(output_values[i]) - kOutputZeroPoint) * kOutputScale;
    const float diff = in_value - out_value;
    total += diff * diff;
  }
  return total / static_cast<float>(kOutputElements);
}

static void emit_result(int iter_id, uint32_t duration_us, int sample_index) {
  SIGNAL_BENCH_SERIAL.print("RESULT ");
  SIGNAL_BENCH_SERIAL.print(iter_id);
  SIGNAL_BENCH_SERIAL.print(" ");
  SIGNAL_BENCH_SERIAL.print(duration_us);
  SIGNAL_BENCH_SERIAL.print(" ");
  if (strcmp(kTaskId, "ad") == 0) {
    const float score = ad_mse(&kInputs[sample_index * kInputElements], output_tensor->data.int8);
    SIGNAL_BENCH_SERIAL.print("{\"sample\":");
    SIGNAL_BENCH_SERIAL.print(sample_index);
    SIGNAL_BENCH_SERIAL.print(",\"label\":");
    SIGNAL_BENCH_SERIAL.print(kLabels[sample_index]);
    SIGNAL_BENCH_SERIAL.print(",\"score\":");
    SIGNAL_BENCH_SERIAL.print(score, 6);
    SIGNAL_BENCH_SERIAL.print(",\"arena_used\":");
    SIGNAL_BENCH_SERIAL.print(static_cast<unsigned long>(interpreter->arena_used_bytes()));
    SIGNAL_BENCH_SERIAL.println("}");
  } else {
    const int pred = argmax_int8(output_tensor->data.int8, kOutputElements);
    SIGNAL_BENCH_SERIAL.print("{\"sample\":");
    SIGNAL_BENCH_SERIAL.print(sample_index);
    SIGNAL_BENCH_SERIAL.print(",\"label\":");
    SIGNAL_BENCH_SERIAL.print(kLabels[sample_index]);
    SIGNAL_BENCH_SERIAL.print(",\"pred\":");
    SIGNAL_BENCH_SERIAL.print(pred);
    SIGNAL_BENCH_SERIAL.print(",\"correct\":");
    SIGNAL_BENCH_SERIAL.print(pred == kLabels[sample_index] ? "true" : "false");
    SIGNAL_BENCH_SERIAL.print(",\"arena_used\":");
    SIGNAL_BENCH_SERIAL.print(static_cast<unsigned long>(interpreter->arena_used_bytes()));
    SIGNAL_BENCH_SERIAL.println("}");
  }
}

static void run_task(const char *task_id, int iterations) {
  if (strcmp(task_id, kTaskId) != 0) {
    emit_err("EINVAL", "firmware task mismatch");
    return;
  }
  if (!init_ok) {
    emit_err("EHW", init_error);
    emit_err("EHW", init_error);
    emit_err("EHW", init_error);
    return;
  }
  if (input_tensor->bytes < kInputElements || output_tensor->bytes < kOutputElements) {
    emit_err("EINFER", "tensor byte count too small");
    return;
  }
  for (int iter = 0; iter < iterations; iter++) {
    const int sample_index = iter % kSampleCount;
    memcpy(input_tensor->data.int8, &kInputs[sample_index * kInputElements], kInputElements);
    const uint32_t t0 = micros();
    const TfLiteStatus status = interpreter->Invoke();
    const uint32_t elapsed = micros() - t0;
    if (status != kTfLiteOk) {
      emit_err("EINFER", "Invoke failed");
      continue;
    }
    emit_result(iter, elapsed, sample_index);
  }
  emit_done(iterations);
}

static void run_eval(const char *task_id, int sample_index, const char *payload) {
  if (strcmp(task_id, kTaskId) != 0) {
    emit_err("EINVAL", "firmware task mismatch");
    return;
  }
  if (strcmp(kTaskId, "kws") != 0 && strcmp(kTaskId, "ad") != 0) {
    emit_err("EINVAL", "EVAL supports kws and ad only");
    return;
  }
  if (!init_ok) {
    emit_err("EHW", init_error);
    return;
  }
  if (input_tensor->bytes < kInputElements || output_tensor->bytes < kOutputElements) {
    emit_err("EINFER", "tensor byte count too small");
    return;
  }
  const int decoded_len = decode_base64_int8(payload, eval_input_buffer, kInputElements);
  if (decoded_len != kInputElements) {
    emit_err("EBADLEN", "decoded tensor length mismatch");
    return;
  }
  memcpy(input_tensor->data.int8, eval_input_buffer, kInputElements);
  const uint32_t t0 = micros();
  const TfLiteStatus status = interpreter->Invoke();
  const uint32_t elapsed = micros() - t0;
  if (status != kTfLiteOk) {
    emit_err("EINFER", "Invoke failed");
    return;
  }
  if (strcmp(kTaskId, "ad") == 0) {
    const float score = ad_mse(eval_input_buffer, output_tensor->data.int8);
    SIGNAL_BENCH_SERIAL.print("SCORE ");
    SIGNAL_BENCH_SERIAL.print(sample_index);
    SIGNAL_BENCH_SERIAL.print(" ");
    SIGNAL_BENCH_SERIAL.print(elapsed);
    SIGNAL_BENCH_SERIAL.print(" ");
    SIGNAL_BENCH_SERIAL.println(score, 6);
    return;
  }
  const int pred = argmax_int8(output_tensor->data.int8, kOutputElements);
  SIGNAL_BENCH_SERIAL.print("PRED ");
  SIGNAL_BENCH_SERIAL.print(sample_index);
  SIGNAL_BENCH_SERIAL.print(" ");
  SIGNAL_BENCH_SERIAL.print(elapsed);
  SIGNAL_BENCH_SERIAL.print(" ");
  SIGNAL_BENCH_SERIAL.println(pred);
}

static void init_model() {
  if (strcmp(kTaskId, "kws") == 0) {
    resolver.AddAveragePool2D();
    resolver.AddConv2D();
    resolver.AddDepthwiseConv2D();
    resolver.AddFullyConnected();
    resolver.AddQuantize();
    resolver.AddReshape();
    resolver.AddSoftmax();
  } else if (strcmp(kTaskId, "ic") == 0) {
    resolver.AddAdd();
    resolver.AddAveragePool2D();
    resolver.AddConv2D();
    resolver.AddFullyConnected();
    resolver.AddReshape();
    resolver.AddSoftmax();
  } else if (strcmp(kTaskId, "ad") == 0) {
    resolver.AddFullyConnected();
  } else {
    init_error = "unknown task resolver";
    return;
  }
  model = tflite::GetModel(kModelData);
  if (model->version() != TFLITE_SCHEMA_VERSION) {
    init_error = "schema version mismatch";
    return;
  }
  static tflite::MicroInterpreter static_interpreter(
      model, resolver, tensor_arena, kTensorArenaBytes);
  interpreter = &static_interpreter;
  if (interpreter->AllocateTensors() != kTfLiteOk) {
    init_error = "AllocateTensors failed";
    return;
  }
  input_tensor = interpreter->input(0);
  output_tensor = interpreter->output(0);
  if (input_tensor == nullptr || output_tensor == nullptr) {
    init_error = "missing tensor";
    return;
  }
  init_ok = true;
  init_error = "";
}

void setup() {
  SIGNAL_BENCH_SERIAL.begin(115200);
  uint32_t start_ms = millis();
  while (!SIGNAL_BENCH_SERIAL && millis() - start_ms < 3000) {
    delay(10);
  }
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, HIGH);
  init_model();
}

void loop() {
  if (!SIGNAL_BENCH_SERIAL.available()) {
    delay(1);
    return;
  }
  String line = SIGNAL_BENCH_SERIAL.readStringUntil('\n');
  char task_id[24] = {0};
  int iterations = 0;
  int sample_index = 0;
  const char *payload = nullptr;
  if (parse_run(line.c_str(), task_id, sizeof(task_id), &iterations)) {
    digitalWrite(LED_BUILTIN, LOW);
    run_task(task_id, iterations);
    digitalWrite(LED_BUILTIN, HIGH);
    return;
  }
  if (parse_eval(line.c_str(), task_id, sizeof(task_id), &sample_index, &payload)) {
    digitalWrite(LED_BUILTIN, LOW);
    run_eval(task_id, sample_index, payload);
    digitalWrite(LED_BUILTIN, HIGH);
    return;
  }
  emit_err("EINVAL", "expected RUN <task_id> <iterations> or EVAL <task_id> <sample_index> <base64-int8-input>");
  return;
}
