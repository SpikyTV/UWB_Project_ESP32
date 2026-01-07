#dont remember what imports are in use
import _thread
import threading
import time
import json
import requests
import random
import math
import running_value_calculation
import paho.mqtt.client as mqtt

class ESP32:
    def __init__(self, x, y, brokerIP, ID, tag):
        
        self.ESP_ID = "esp32_" + str(ID)
        
        self.DATA_TOPIC = f"hub/{self.ESP_ID}/data"
        self.REG_TOPIC  = f"hub/{self.ESP_ID}/register"
        self.COMMAND_TOPIC = f"hub/{self.ESP_ID}/command"
        
        self.cords = x, y
        self.target = x, y
        
        self.id = 0 #idk
        self.tag = tag
        self.brokerIP = brokerIP

        self.count = 0
        self.mean = 0.0
        self.M2 = 0.0
        self.start_samples = 200
        self.max_error = 0.5
        self.number_of_samples = 200

        self.received_command = False
        self.payload = None

        self.esp_objects = []

        self.list_distance = []
        self.list_dispersion = []
        
        t = threading.Thread(target=self.running)
        t.daemon = True
        t.start()

    def set_esp_objects(self, esp_obj):
        self.esp_objects = esp_obj

    def get_x_y(self):
        return self.cords
        
    def on_connect(self, client, userdata, flags, rc):
        print("Connected to broker")
        
        if rc == 0:
            print("Connected to MQTT broker")
            self.client.subscribe(self.COMMAND_TOPIC)
        else:
            print(f"Connection failed (rc={rc})")

        # One-time (per connection) registration
        x, y = self.cords
        registration_payload = {
            "esp_id": self.ESP_ID,
            "x": x,
            "y": y,
            "tag": self.tag
        }

        #on connect sends register topic with 1 send garanteed
        self.client.publish(self.REG_TOPIC, json.dumps(registration_payload), qos=1) 
        
    def on_message(self, client, userdata, msg):
        if msg.topic == self.COMMAND_TOPIC:
            self.payload = json.loads(msg.payload)
            self.received_command = True
    
    #message to send mesurements to server
    def send_measurement(self):
        x, y = self.cords
        
        payload = {
            "tag": self.tag,
            "id": self.ESP_ID,
            "list_a": self.list_distance,
            "list_b": self.list_dispersion,
            "x": x,
            "y": y
        }
        
        self.client.publish(self.DATA_TOPIC, json.dumps(payload), qos=0)

    #running value
    def add(self, value: float):
        # Always take first start_samples measurements
        if self.count < self.start_samples:
            accept = True
        else:
            # Accept only if within max_error from current mean
            accept = abs(value - self.mean) <= self.max_error

        if accept:
            self.count += 1
            delta = value - self.mean
            self.mean += delta / self.count
            delta2 = value - self.mean
            self.M2 += delta * delta2
        else:
            pass

    def get_mean(self) -> float:
        return self.mean

    def get_dispersion(self) -> float:
        if self.count < 2:
            return 0.0
        variance = self.M2 / (self.count - 1)
        return variance ** 0.5

    def make_mesurements(self, number_of_mesurments, real_distance):

        self.count = 0
        self.mean = 0.0
        self.M2 = 0.0

        for _ in range(number_of_mesurments):
            distance = running_value_calculation.generate_distance(real_distance)
            self.add(distance)

        self.list_distance.append(round(abs(self.get_mean()), 2))
        self.list_dispersion.append(round(abs(self.get_dispersion()), 2))
    
    def start_measurement(self):
       print("Starting measurement routine...")
       
       self.list_distance = []
       self.list_dispersion = []

       for esp in self.esp_objects:
           # Skip measuring distance to itself
           if self.ESP_ID == esp.ESP_ID:
            self.list_distance.append(0)
            self.list_dispersion.append(0)
            continue

           other_esp_coords = esp.get_x_y()

           #dont ask me I dont remember (real distance)
           x1, y1 = self.cords
           x2, y2 = other_esp_coords
           distance = math.sqrt((x2 - x1)**2 + (y2 - y1)**2)

           if self.tag == "anch":
                self.make_mesurements(1500, distance)
           elif self.tag == "tag":
                #only 20 samples per anchor when you are tag (expecte to take around 0.05 sec)
                self.make_mesurements(20, distance)
       
       print("sending data")
       self.send_measurement()
       
    def pick_new_target(self):
        self.target = (
            random.uniform(0, 20),
            random.uniform(0, 20)
        )
        self.speed = random.uniform(2, 8)  # m/s
        
    def update(self):
        dt = 1 / 60
        
        x, y = self.cords
        tx, ty = self.target

        dx = tx - x
        dy = ty - y
        distance = math.hypot(dx, dy)

        if distance < 0.1:
            self.pick_new_target()
            return

        dx /= distance
        dy /= distance

        x += dx * self.speed * dt
        y += dy * self.speed * dt

        self.cords = (x, y)
        
    def run_cords(self):
        self.pick_new_target()
        
        while True:
            self.update()
            time.sleep(1/60)
        

    def running(self):
        
        self.client = mqtt.Client(client_id=self.ESP_ID)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.connect(self.brokerIP, 1883)
        self.client.loop_start()
        
        while True:
            if not self.received_command:
                time.sleep(0.01)
                continue

            if self.payload.get("command") == "start_measurement":
                self.start_measurement()
                self.payload = None
                self.received_command = False
            elif self.payload.get("command") == "start_tag":
                t = threading.Thread(target=self.run_cords)
                t.daemon = True
                t.start()
                while True:
                    self.start_measurement()
                    time.sleep(0.1)
                self.payload = None
                self.received_command = False

          



