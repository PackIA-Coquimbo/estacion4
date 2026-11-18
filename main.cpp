#include <Arduino.h>   // necesario si se compila como .cpp (en el Arduino IDE renombrar a .ino)
#include <Servo.h>

// =====================================================================
// Estación 4 - Arduino: servo de las cajas + barrera infrarroja + botón de lote
//
// Habla con estacion4.py por USB serial (9600 baudios), una orden por línea:
//   PC -> Arduino:  "C1".."C4"  mover el servo a la caja 1..4
//                   "P"         ping (responde "PONG")
//   Arduino -> PC:  "LISTO"     terminó el setup
//                   "FRUTA"     una fruta cortó la barrera infrarroja antes del servo
//                   "BOTON"     el operario apretó el botón de nuevo lote
//                   "OK C3"     servo movido
//                   "ERROR ..." orden desconocida
//
// La decisión (qué caja) la toma el PC. El Arduino solo mide y mueve.
// =====================================================================

// Pines
const int PIN_SERVO   = 9;   // PWM, señal del servo
const int PIN_BARRERA = 2;   // sensor IR (módulo de obstáculo: LOW cuando hay fruta)
const int PIN_BOTON   = 3;   // botón a GND (se usa la resistencia interna pull-up)

// Ángulo del servo para cada caja (índice 1..4). Ajustar con la maqueta.
// Caja 1 = Pasable, 2 = Buena-Chica, 3 = Buena-Mediana, 4 = Buena-Grande
const int ANGULO_CAJA[5] = {90, 30, 70, 110, 150};
const int ANGULO_REPOSO  = 90;

// Si el sensor IR entrega HIGH cuando detecta, cambiar a HIGH
const int NIVEL_FRUTA_PRESENTE = LOW;

// Tiempos anti-rebote
const unsigned long REBOTE_BARRERA_MS = 80;
const unsigned long REBOTE_BOTON_MS   = 250;

Servo miServo;
String linea = "";

bool barreraAnterior = false;
unsigned long ultimoCambioBarrera = 0;
bool botonAnterior = HIGH;
unsigned long ultimoBoton = 0;

void setup() {
  Serial.begin(9600);
  pinMode(PIN_BARRERA, INPUT);
  pinMode(PIN_BOTON, INPUT_PULLUP);
  miServo.attach(PIN_SERVO);
  miServo.write(ANGULO_REPOSO);
  Serial.println("LISTO");
}

void procesarOrden(String orden) {
  orden.trim();
  if (orden.length() == 0) return;

  if (orden == "P") {
    Serial.println("PONG");
    return;
  }
  if (orden.length() == 2 && orden.charAt(0) == 'C') {
    int caja = orden.charAt(1) - '0';
    if (caja >= 1 && caja <= 4) {
      miServo.write(ANGULO_CAJA[caja]);
      Serial.print("OK C");
      Serial.println(caja);
      return;
    }
  }
  Serial.print("ERROR orden desconocida: ");
  Serial.println(orden);
}

void leerSerial() {
  // Lectura sin bloquear: se arma la línea carácter por carácter
  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c == '\n') {
      procesarOrden(linea);
      linea = "";
    } else if (c != '\r' && linea.length() < 20) {
      linea += c;
    }
  }
}

void revisarBarrera() {
  bool hayFruta = digitalRead(PIN_BARRERA) == NIVEL_FRUTA_PRESENTE;
  unsigned long ahora = millis();
  if (hayFruta != barreraAnterior && ahora - ultimoCambioBarrera > REBOTE_BARRERA_MS) {
    ultimoCambioBarrera = ahora;
    barreraAnterior = hayFruta;
    if (hayFruta) {
      Serial.println("FRUTA");    // se avisa solo al entrar la fruta, no al salir
    }
  }
}

void revisarBoton() {
  bool estado = digitalRead(PIN_BOTON);
  unsigned long ahora = millis();
  if (estado == LOW && botonAnterior == HIGH && ahora - ultimoBoton > REBOTE_BOTON_MS) {
    ultimoBoton = ahora;
    Serial.println("BOTON");
  }
  botonAnterior = estado;
}

void loop() {
  leerSerial();
  revisarBarrera();
  revisarBoton();
  // Sin delay(): el loop debe ser rápido para no perder frutas en la barrera
}
