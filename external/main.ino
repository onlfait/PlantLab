#include <WiFi.h>
#include <HTTPClient.h>
#include <time.h>

/*
  ============================================================================
  PlantLab – Soil Moisture Sensor (ESP32-C3)
  ----------------------------------------------------------------------------
  This firmware reads a capacitive soil moisture sensor, smooths ADC readings,
  converts them to a percentage using calibration values, and periodically
  sends the data to a PlantLab backend over HTTP.

  Target board: XIAO ESP32-C3
  ============================================================================
*/


// ============================================================================
// WIFI CONFIGURATION
// ============================================================================
// Credentials of the local PlantLab WiFi network (Raspberry Pi AP)
static const char* WIFI_SSID = "PlantLab";
static const char* WIFI_PASS = "plantlab2026"; // Adjust if needed

// Base URL of the PlantLab backend
// Example: http://192.168.157.39:8000
static const char* BASE_URL = "http://plantlab.local:8000";


// ============================================================================
// SENSOR IDENTIFICATION
// ============================================================================
// Logical identifier of this sensor node (used by the backend)
static const char* SENSOR_ID = "S1";


// ============================================================================
// HARDWARE CONFIGURATION
// ============================================================================
// ADC pin connected to the capacitive soil moisture sensor
// XIAO ESP32-C3: GPIO2 is usually mapped to A0
static const int ADC_PIN = 2;


// ============================================================================
// CALIBRATION VALUES
// ============================================================================
// IMPORTANT:
// These values are sensor- and setup-specific and MUST be measured manually.
//
// Typical procedure:
//  - DRY_ADC: sensor exposed to air (completely dry)
//  - WET_ADC: sensor inserted in very wet soil or water
//
// Higher ADC value usually means drier soil.
static int DRY_ADC = 3000;
static int WET_ADC = 1600;


// ============================================================================
// SAMPLING & TRANSMISSION SETTINGS
// ============================================================================
static const uint32_t SAMPLE_PERIOD_MS = 1000;   // ADC sampling interval (1s)
static const uint32_t SEND_PERIOD_MS   = 15000;  // HTTP send interval (15s, test value)
static const int SMOOTH_WINDOW = 20;              // Moving average window size


// ============================================================================
// INTERNAL STATE
// ============================================================================
static uint32_t lastSampleMs = 0;
static uint32_t lastSendMs   = 0;

static int samples[SMOOTH_WINDOW];
static int sampleIndex = 0;
static bool windowFilled = false;


// ============================================================================
// UTILITY FUNCTIONS
// ============================================================================
static int clampInt(int v, int lo, int hi) {
  if (v < lo) return lo;
  if (v > hi) return hi;
  return v;
}

// Map a raw ADC value to a percentage based on calibration values
// WET_ADC  -> 100%
// DRY_ADC  -> 0%
static float mapToPercent(int adc) {
  if (DRY_ADC == WET_ADC) return 0.0f;

  float pct = (float)(DRY_ADC - adc) * 100.0f /
              (float)(DRY_ADC - WET_ADC);

  if (pct < 0.0f)   pct = 0.0f;
  if (pct > 100.0f) pct = 100.0f;
  return pct;
}

// Read raw ADC value (ESP32 ADC is typically 12-bit: 0–4095)
static int readAdcRaw() {
  return analogRead(ADC_PIN);
}

// Read ADC value and apply moving average smoothing
// Optionally returns the last raw value via rawOut
static float readAdcSmoothed(int* rawOut) {
  int raw = readAdcRaw();
  if (rawOut) *rawOut = raw;

  samples[sampleIndex] = raw;
  sampleIndex = (sampleIndex + 1) % SMOOTH_WINDOW;
  if (sampleIndex == 0) windowFilled = true;

  long sum = 0;
  int n = windowFilled ? SMOOTH_WINDOW : sampleIndex;
  if (n <= 0) n = 1;

  for (int i = 0; i < n; i++) {
    sum += samples[i];
  }

  return (float)sum / (float)n;
}

// Send a JSON payload via HTTP POST
static bool httpPostJson(const char* url, const char* json) {
  HTTPClient http;
  http.begin(url);
  http.addHeader("Content-Type", "application/json");

  int code = http.POST((uint8_t*)json, strlen(json));
  http.end();

  return (code >= 200 && code < 300);
}

// Ensure WiFi connection (blocking with timeout)
static void ensureWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED &&
         (millis() - start) < 15000) {
    delay(250);
  }
}

// Return current Unix epoch time if available
// If time is not synchronized, returns 0.
// The backend can timestamp the data instead.
static uint32_t epochNow() {
  time_t now;
  time(&now);

  // Arbitrary threshold to detect invalid time
  if (now < 1700000000) return 0;
  return (uint32_t)now;
}


// ============================================================================
// SETUP
// ============================================================================
void setup() {
  Serial.begin(115200);
  delay(200);

  pinMode(ADC_PIN, INPUT);

  // Pre-fill smoothing buffer to avoid startup spikes
  for (int i = 0; i < SMOOTH_WINDOW; i++) {
    samples[i] = readAdcRaw();
  }

  ensureWiFi();

  Serial.println("PlantLab sensor started");
  Serial.print("WiFi status: ");
  Serial.println(WiFi.status());

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("IP: ");
    Serial.println(WiFi.localIP());
  }
}


// ============================================================================
// MAIN LOOP
// ============================================================================
void loop() {
  uint32_t nowMs = millis();

  // 1) Periodic sampling
  if (nowMs - lastSampleMs >= SAMPLE_PERIOD_MS) {
    lastSampleMs = nowMs;

    int raw = 0;
    float avg = readAdcSmoothed(&raw);
    float pct = mapToPercent((int)avg);

    Serial.print("raw=");
    Serial.print(raw);
    Serial.print(" avg=");
    Serial.print(avg, 1);
    Serial.print(" pct=");
    Serial.println(pct, 1);
  }

  // 2) Periodic data transmission
  if (nowMs - lastSendMs >= SEND_PERIOD_MS) {
    lastSendMs = nowMs;

    ensureWiFi();
    if (WiFi.status() != WL_CONNECTED) {
      Serial.println("WiFi not connected, skipping send");
      return;
    }

    int raw = 0;
    float avg = readAdcSmoothed(&raw);
    float pct = mapToPercent((int)avg);

    char url[256];
    snprintf(url, sizeof(url), "%s/api/ingest", BASE_URL);

    // Minimal JSON payload (ArduinoJson not required)
    char payload[256];
    uint32_t ts = epochNow();
    snprintf(
      payload, sizeof(payload),
      "{\"sensor_id\":\"%s\",\"adc\":%d,\"percent\":%.1f,\"ts\":%u}",
      SENSOR_ID, (int)avg, pct, (unsigned)ts
    );

    bool ok = httpPostJson(url, payload);
    Serial.print("POST ");
    Serial.print(url);
    Serial.print(" -> ");
    Serial.println(ok ? "OK" : "FAIL");
  }
}
