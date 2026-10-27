#include <Servo.h>

// Pin PWM donde donde se conecta el cable señal del servo
const int PIN_SERVO = 9; 

// angulos para mover el brazo (recordar 180 es full derecha y 90 es centrado)
const int ANGULO_IZQUIERDA = 45;
const int ANGULO_CENTRO    = 90;
const int ANGULO_DERECHA   = 135;

// Objeto para controlar el servomotor
Servo miServo;


// esto es mas de logica, la variable esta simula la decisión tomada por el sistema, por ejemplo ahora toma los valores default de -1, 0 y 1.
int estadoDeseado = 0; 

void setup() {
  Serial.begin(9600);

  // Vincular el objeto Servo al pin 
  miServo.attach(PIN_SERVO);

  // Posición inicial por defecto al encender el circuito
  miServo.write(ANGULO_CENTRO);
  Serial.print("Servo inicializado en ");
  Serial.println(ANGULO_CENTRO);
}


//idealmente aqui desarrollamos el como leeremos las variables que nos den, o que nosotros mismos trabajemos
void loop() {

  // por si las dudas: .write() envía una señal de manera continua, si la variable no cambia, el servo mantendra su ultimo estado
  switch (estadoDeseado) {
    case -1:
      miServo.write(ANGULO_IZQUIERDA);
      break;

    case 0:
      miServo.write(ANGULO_CENTRO);
      break;

    case 1:
      miServo.write(ANGULO_DERECHA);
      break;

    default:
      // esto es en caso de error, hay q configurarlo en el sistema como tal, ya que este mismo debera de detener o evitar el error, esto es solo como debera de responder el brazo/tubo
      miServo.write(ANGULO_CENTRO);
      break;
  }

  // delay en el loop, definir luego con los tiempos de respuesta esperados
  delay(20); 
}