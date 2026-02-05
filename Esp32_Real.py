import network
import time
import ubinascii
import ujson as json
import urandom
import math
from collections import deque

from umqtt.simple import MQTTClient


class ESP32_Real:
    def __init__(self, ssid, password, broker_ip="192.168.1.101", broker_port=1883):
        self.wlan = network.WLAN(network.STA_IF)
        self.wlan.active(True)
        mac = ubinascii.hexlify(self.wlan.config("mac")).decode()
        self.ESP_ID = mac[-4:] 
        
        self.msg_queue = deque((), 64) 
        self.others = {}

        self.tag = "NotSet"
        self.cords = (0.0, 0.0)

        #mqtt
        self.BROKER_IP = broker_ip
        self.BROKER_PORT = broker_port

        self.TOPIC2 = f"hub/{self.ESP_ID}/command"
        self.TOPIC3 = "hub/uwb/command"
        self.TOPIC6 = f"hub/uwb/uwb" 

        self.TOPIC_REG = "hub/ESP32_Manager/register"
        self.TOPIC_UPD = "hub/ESP32_Manager/update"
        self.TOPIC_SOLVER_REG = "hub/solver/register"
        self.TOPIC_UWB_BCAST = "hub/uwb/uwb"
        self.TOPIC_DATA = f"hub/{self.ESP_ID}/data"

        self._wifi_connect(ssid, password)
        self._mqtt_connect()
        
        self.count = 0
        self.mean = 0.0
        self.M2 = 0.0
        self.start_samples = 200
        self.max_error = 0.5
        self.number_of_samples = 200
        
        self.list_distance = []
        self.list_dispersion = []

        first_reg_payload = {
            "id": self.ESP_ID
            }
            
        self._publish(self.TOPIC_REG, first_reg_payload, qos1=True)

        print("Booted as:", self.ESP_ID)

    def _wifi_connect(self, ssid, password, timeout_s=20):
        print("Connecting WiFi...")
        self.wlan.connect(ssid, password)

        t0 = time.ticks_ms()
        while not self.wlan.isconnected():
            if time.ticks_diff(time.ticks_ms(), t0) > timeout_s * 1000:
                raise RuntimeError("WiFi connect timeout")
            time.sleep(0.2)

        print("WiFi:", self.wlan.ifconfig())

    def _mqtt_connect(self):
        self.client = MQTTClient(
            client_id=self.ESP_ID.encode(),
            server=self.BROKER_IP,
            port=self.BROKER_PORT,
            keepalive=60,
        )
        self.client.set_callback(self._on_message)
        self.client.connect()

        self.client.subscribe(self.TOPIC2.encode())
        self.client.subscribe(self.TOPIC3.encode())
        self.client.subscribe(self.TOPIC6.encode())

        print("MQTT connected, subscribed:", self.TOPIC2, self.TOPIC3, self.TOPIC6)

    def _publish(self, topic: str, payload: dict, qos1: bool = False):
        msg = json.dumps(payload).encode()
        t = topic.encode()
        try:
            if qos1:
                self.client.publish(t, msg, qos=1)
            else:
                self.client.publish(t, msg)
        except TypeError:
            
            self.client.publish(t, msg)

    def _on_message(self, topic, msg):
        
        try:
            self.msg_queue.append((topic, msg))
        except IndexError:
         
            pass

    def config(self, data):
        self.ESP_ID = data.get("id")
        self.tag = data.get("tag")
        x = float(data.get("x"))
        y = float(data.get("y"))
        self.cords = (x, y)
        
        self.TOPIC2 = f"hub/{self.ESP_ID}/command"
        self.TOPIC6 = f"hub/{self.ESP_ID}/uwb"
        self.TOPIC_DATA = f"hub/{self.ESP_ID}/data"

        self.client.subscribe(self.TOPIC2.encode())
        self.client.subscribe(self.TOPIC6.encode())
        
      
        update_payload = {
            "id": self.ESP_ID, 
            "x": x, 
            "y": y, 
            "tag": self.tag
            }
            
        self._publish(self.TOPIC_UPD, update_payload, qos1=True)
        
        print(f"config finished: {self.ESP_ID}, {self.tag}, {x}, {y}")

    def register(self):
        x, y = self.cords
        registration_payload = {
            "esp_id": self.ESP_ID, 
            "x": x, 
            "y": y, 
            "tag": self.tag
            }
            
        self._publish(self.TOPIC_SOLVER_REG, registration_payload, qos1=True)

    def send_measurement(self, qos1=False):
        x, y = self.cords
        payload = {
            "tag": self.tag,
            "esp_id": self.ESP_ID,
            "distance": self.list_distance,
            "dispersion": self.list_dispersion,
            "x": x,
            "y": y,
        }
        
        print("sending data")
        self._publish(self.TOPIC_DATA, payload, qos1)

    def add(self, value: float):
        
        if self.count < self.start_samples:
            accept = True
        else:
            
            accept = abs(value - self.mean) <= self.max_error

        if accept:
            self.count += 1
            delta = value - self.mean
            self.mean += delta / self.count
            delta2 = value - self.mean
            self.M2 += delta * delta2

    #Welford’s online algorithm readout
    def get_dispersion(self):
        if self.count < 2:
            return 0.0
        variance = self.M2 / (self.count - 1)
        return variance ** 0.5

    def generate_distance(self, real_distance, standard_diviation = 0.3):
        #generate  random intiger divide by max intiger offset to +- 0.5 multiply by standard diviation
        #default 0.3 (+- 15cm should be standard for real uwb)
        noise = (urandom.getrandbits(16) / 65535.0 - 0.5) * standard_diviation
        
        #small chance for error data (1 in 128)
        #will add 0.5 to 3 meters
        if urandom.getrandbits(7) == 0:
            noise += 0.5 + (urandom.getrandbits(16) / 65535.0) * 2.5
            
        return real_distance + noise

    def make_mesurements(self, number_of_mesurments, real_distance):
        self.count = 0
        self.mean = 0.0
        self.M2 = 0.0

        for _ in range(number_of_mesurments):
            d = self.generate_distance(real_distance)
            self.add(d)

        self.list_distance.append(self.mean)
        self.list_dispersion.append(self.get_dispersion())
        
        print(self.list_distance)
        print(self.list_dispersion)

    def start_measurement(self):
        print("Starting measurement routine...")
        
        self.list_distance = []
        self.list_dispersion = []

        x1, y1 = self.cords

        print(self.ESP_ID)

        
        for other_id, info in sorted(self.others.items()):
            
            print(other_id)
            
            x2, y2 = info.get("cords", (None, None))
            tag = info.get("tag")

            if tag != "anch":
                continue

            if other_id == self.ESP_ID:
                self.list_distance.append(0.0)
                self.list_dispersion.append(0.0)
                continue

            dx = x2 - x1
            dy = y2 - y1
            real_dist = math.sqrt(dx*dx + dy*dy)

            if self.tag == "anch":
                
                self.make_mesurements(1500, real_dist)
            else:
                self.make_mesurements(20, real_dist)

        self.send_measurement()

   
    def handle_command(self, data):
        command = data.get("command")

        if command == "start_measurement":
            self.start_measurement()

        elif command == "start_tag":
            print("not avalible on real esp due to thread limit")

        elif command == "uwb":
            time.sleep(int(self.ESP_ID.split("_")[-1]) * 0.05)

            payload = {"type": "uwb", "id": self.ESP_ID, "cords": self.cords, "tag": self.tag}
            self._publish(self.TOPIC_UWB_BCAST, payload, qos1=True)
            print("sending my self to others")

    
    def process_one(self):
        if not self.msg_queue:
            return

        topic, msg = self.msg_queue.popleft()

        try:
            
            topic_s = topic.decode()
            parts = topic_s.split("/")
            uuid = parts[1] if len(parts) > 1 else ""

            data = json.loads(msg.decode())
            typ = data.get("type")
            
            print(data)
            print(typ)

            if uuid in (self.ESP_ID, "uwb"):
                if typ in ("config", "final_config"):
                    self.config(data)
                    if typ == "final_config":
                        self.register()

                elif typ == "command":
                    
                    self.handle_command(data)

                elif typ == "uwb":
                    self.others[data.get("id")] = {"cords": data.get("cords"), "tag": data.get("tag")}

                else:
                    print("unknown type:", typ)

        except Exception as e:
            print("process error:", e)

    def loop_forever(self):
        while True:
            
            self.client.check_msg()

            
            for _ in range(5):
                self.process_one()


            time.sleep_ms(5)



node = ESP32_Real(
    ssid="",
    password="",
    broker_ip="192.168.1.101",
    broker_port=1883
)
node.loop_forever()


