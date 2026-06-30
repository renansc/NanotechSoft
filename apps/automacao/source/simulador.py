import os
import random
import time

import requests

URL = os.getenv(
    "SENSOR_API_URL",
    "http://localhost:5000/api/leitura"
)
MOTOR_ID = int(os.getenv("MOTOR_ID", "1"))
INTERVALO = float(os.getenv("SENSOR_INTERVAL", "5"))


def gerar_payload():
    return {
        "motor_id": MOTOR_ID,
        "rpm": random.randint(1700, 1800),
        "temperatura": round(
            random.uniform(35, 80),
            2
        ),
        "vibracao": round(
            random.uniform(0.10, 0.90),
            2
        )
    }


if __name__ == "__main__":
    while True:
        payload = gerar_payload()

        try:
            response = requests.post(
                URL,
                json=payload,
                timeout=10
            )
            response.raise_for_status()
            print(payload, flush=True)
        except requests.RequestException as error:
            print(
                f"Falha ao enviar leitura: {error}",
                flush=True
            )

        time.sleep(INTERVALO)
