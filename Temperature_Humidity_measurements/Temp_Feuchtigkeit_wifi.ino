#include <WiFi.h>
#include <HTTPClient.h>
#include "DHT.h"
#include "SPIFFS.h"
#include "time.h"

// === DHT Sensor ===
#define DHTPIN 4
#define DHTTYPE DHT22
DHT dht(DHTPIN, DHTTYPE);

// === Accsessing wlan and Database ===


void setup() {
  Serial.begin(115200);
  dht.begin();
  SPIFFS.begin(true);

  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) delay(1000);

  // NTP-Zeit holen
  configTime(0, 0, "pool.ntp.org", "time.nist.gov");
  while (time(nullptr) < 100000) {
    delay(500);
    Serial.print(".");
  }

  sendCachedData();
}

// === Daten senden mit Zeitstempel ===
void sendToInflux(float temperature, float humidity, time_t timestamp) {
  HTTPClient http;
  String url = String(server) + "/api/v2/write?org=" + org + "&bucket=" + bucket + "&precision=s";
  http.begin(url);
  http.addHeader("Authorization", "Token " + String(token));
  http.addHeader("Content-Type", "text/plain");

  // Zeitstempel als Unix-Time (Sekunden seit 1970)
  String data = "klima,ort=wohnzimmer temperatur=" + String(temperature) + ",feuchtigkeit=" + String(humidity) + " " + String(timestamp);
  int status = http.POST(data);
  Serial.println("POST Status: " + String(status));
  http.end();
}

// === Cache speichern (Temperatur, Feuchtigkeit, Zeitstempel) ===
void cacheData(float temperature, float humidity, time_t timestamp) {
  File file = SPIFFS.open("/cache.txt", FILE_APPEND);
  if (file) {
    file.printf("%.2f,%.2f,%lu\n", temperature, humidity, (unsigned long)timestamp);
    file.close();
    Serial.println("Daten gecacht.");
  } else {
    Serial.println("Fehler beim Schreiben in Cache.");
  }
}

// === Cache auslesen und senden ===
void sendCachedData() {
  File file = SPIFFS.open("/cache.txt");
  if (!file) return;

  Serial.println("Sende gecachte Daten...");

  while (file.available()) {
    String line = file.readStringUntil('\n');
    float t, h;
    unsigned long ts;
    if (sscanf(line.c_str(), "%f,%f,%lu", &t, &h, &ts) == 3) {
      sendToInflux(t, h, (time_t)ts);
      delay(100); // kleine Pause
    }
  }

  file.close();
  SPIFFS.remove("/cache.txt"); // Lösche Cache nach dem Senden
  Serial.println("Cache gesendet und gelöscht.");
}

void loop() {
  const uint32_t loopStartUs = micros();

  // Zeit für das Auslesen des DHT22 messen
  const uint32_t sensorStartUs = micros();

  float temp_raw = dht.readTemperature();
  float hum_raw = dht.readHumidity();

  const uint32_t sensorDurationUs = micros() - sensorStartUs;

  // Kalibrierung
  // Letzte Kalibrierung: 27.09.2026
  float humidity = hum_raw;
  float temperature = temp_raw;

  Serial.println("\n=== Geschwindigkeitsmessung ===");
  Serial.printf("DHT-Auslesezeit: %lu us (%.2f ms)\n",
                (unsigned long)sensorDurationUs,
                sensorDurationUs / 1000.0);

  if (isnan(humidity) || isnan(temperature)) {
    Serial.println("Sensorfehler!");
    delay(30000);
    return;
  }

  Serial.printf("Temperatur: %.2f °C\n", temperature);
  Serial.printf("Luftfeuchtigkeit: %.2f %%\n", humidity);

  time_t now_ts = time(nullptr);

  // Zeit der Speicherung bzw. Übertragung messen
  const uint32_t transferStartMs = millis();

  if (WiFi.status() == WL_CONNECTED) {
    sendToInflux(temperature, humidity, now_ts);
    sendCachedData();
  } else {
    cacheData(temperature, humidity, now_ts);
  }

  const uint32_t transferDurationMs = millis() - transferStartMs;
  const uint32_t totalDurationUs = micros() - loopStartUs;

  Serial.printf("Übertragungs-/Speicherzeit: %lu ms\n",
                (unsigned long)transferDurationMs);

  Serial.printf("Gesamtdauer: %.2f ms\n",
                totalDurationUs / 1000.0);

  delay(30000);
}