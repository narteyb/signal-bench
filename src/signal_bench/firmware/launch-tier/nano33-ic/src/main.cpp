
#include <Arduino.h>
#include <Chirale_TensorFlowLite.h>
#include <tensorflow/lite/micro/micro_interpreter.h>
#include <tensorflow/lite/micro/micro_mutable_op_resolver.h>
#include <tensorflow/lite/schema/schema_generated.h>

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
  if (!parse_run(line.c_str(), task_id, sizeof(task_id), &iterations)) {
    emit_err("EINVAL", "expected RUN <task_id> <iterations>");
    return;
  }
  digitalWrite(LED_BUILTIN, LOW);
  run_task(task_id, iterations);
  digitalWrite(LED_BUILTIN, HIGH);
}
